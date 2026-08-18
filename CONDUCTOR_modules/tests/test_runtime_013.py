from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTROLLER = ROOT / "CONDUCTOR_modules" / "tools" / "runtime_controller.py"
SPEC = importlib.util.spec_from_file_location("conductor_runtime_013", CONTROLLER)
RUNTIME = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(RUNTIME)


class Runtime013Tests(unittest.TestCase):
    def command(self, *arguments: str, ok: bool = True) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            [sys.executable, str(CONTROLLER), *arguments],
            cwd=ROOT,
            text=True,
            capture_output=True,
            env=os.environ.copy(),
        )
        if ok and completed.returncode:
            self.fail(completed.stderr or completed.stdout)
        if not ok and not completed.returncode:
            self.fail("Command unexpectedly succeeded")
        return completed

    def active_basic_round(self, base: Path) -> tuple[Path, str, str]:
        source = base / "input.csv"
        source.write_text("compound_id,smiles,pIC50\nCMP1,CCO,5.1\nCMP2,CCN,5.4\n", encoding="utf-8")
        run_root = base / "run"
        self.command("init", "--input", str(source), "--endpoint", "pIC50", "--higher-is-better", "--project", "test", "--parallel-limit", "2", "--run-id", "run-013", "--output-dir", str(run_root))
        prepared = json.loads(self.command("prepare-round", "--run-root", str(run_root), "--objective", "packet test", "--walltime-minutes", "60", "--parallel-limit", "2", "--approve-high-cost").stdout)
        control_key = (run_root / "runtime" / "control_authority.key").read_text(encoding="utf-8").strip()
        self.command("authorize-round", "--run-root", str(run_root), "--control-key", control_key, "--request-file", prepared["request_file"], "--authorization-token", prepared["authorization_token"])
        resumed = json.loads(self.command("resume-round", "--run-root", str(run_root), "--control-key", control_key, "--owner-id", "main-session").stdout)
        lease, action = resumed["lease_token"], resumed["action_token"]
        planned = json.loads(self.command("plan-basic", "--run-root", str(run_root), "--lease-token", lease, "--action-token", action).stdout)
        return run_root, lease, planned["action_token"]

    def test_main_orchestrator_is_manual_skill_not_agent(self) -> None:
        skill = ROOT / ".claude" / "skills" / "cs-conductor-orchestrator" / "SKILL.md"
        self.assertTrue(skill.is_file())
        self.assertIn("disable-model-invocation: true", skill.read_text(encoding="utf-8"))
        self.assertFalse((ROOT / ".claude" / "agents" / "cs-conductor-orchestrator.md").exists())
        self.assertTrue((ROOT / ".claude" / "agents" / "cs-conductor-executor.md").is_file())
        self.assertTrue((ROOT / ".claude" / "agents" / "cs-conductor-interpreter.md").is_file())

    def test_compact_response_is_bounded_and_does_not_embed_control(self) -> None:
        control = {
            "revision": 7,
            "run": {"run_id": "run"},
            "active_round_id": "RND0002",
            "round_state": "ACTIVE",
            "required_action": {"code": "SCIENTIFIC_DECISION", "reason": "test"},
            "counts": {"succeeded": 5000},
            "closure": {"contract_satisfied": False, "interpretation_ready": False, "audit_ready": False, "outcome": "undetermined"},
            "pointers": {"working_set": "runtime/working_set.json"},
        }
        response = RUNTIME._compact_response(control, action_token="token", detail_pointer="runtime/logs")
        self.assertEqual("0.1.3", response["protocol_version"])
        self.assertNotIn("control", response)
        self.assertLessEqual(len(RUNTIME.canonical_bytes(response)), RUNTIME.MAX_COMPACT_RESPONSE_BYTES)

    def test_execution_packet_is_signed_action_scoped_and_becomes_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_root, lease, action = self.active_basic_round(Path(temporary))
            response = json.loads(self.command("prepare-execution-packet", "--run-root", str(run_root), "--lease-token", lease, "--action-token", action, "--timeout-minutes", "5").stdout)
            self.assertEqual("0.1.3", response["protocol_version"])
            self.assertNotIn("lease_token", response)
            packet_path = Path(response["packet_path"])
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
            self.assertNotIn("lease_token", packet)
            control = json.loads((run_root / "conductor_control.json").read_text(encoding="utf-8"))
            validated = RUNTIME._validate_execution_packet(run_root, control, packet_path, response["executor_token"])
            self.assertEqual(response["packet_id"], validated["packet_id"])

            heartbeat = json.loads(self.command("heartbeat", "--run-root", str(run_root), "--lease-token", lease, "--action-token", action).stdout)
            self.assertNotEqual(action, heartbeat["action_token"])
            changed = json.loads((run_root / "conductor_control.json").read_text(encoding="utf-8"))
            with self.assertRaises(PermissionError):
                RUNTIME._validate_execution_packet(run_root, changed, packet_path, response["executor_token"])

    def test_interpretation_retry_exhaustion_is_a_human_stop(self) -> None:
        control = {
            "active_round_id": "RND0001",
            "round_state": "FINALIZING",
            "blocker": {"code": "INTERPRETATION_RETRY_EXHAUSTED", "node_id": "N000001"},
            "lease": {},
            "closure": {"interpretation_ready": False, "audit_ready": False},
        }
        snapshot = {"nodes": [], "rounds": {"RND0001": {"state": "FINALIZING"}}, "plans": {}}
        action = RUNTIME._required_action(Path("."), control, snapshot)
        self.assertEqual("INTERPRETATION_BLOCKED", action["code"])

    def test_adaptive_recovery_rejects_scientific_parameter_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scratch = root / "runtime" / "scratch" / "RND0001" / "N000001" / "ATT0002"
            recovery = scratch / "recovery"
            recovery.mkdir(parents=True)
            prior = root / "runtime" / "scratch" / "RND0001" / "N000001" / "ATT0001" / "failure_packet.json"
            prior.parent.mkdir(parents=True)
            prior.write_text(json.dumps({"recoverable": True, "classification": "argument_contract_mismatch"}), encoding="utf-8")
            base = [sys.executable, "skill-launch.py", "--node-id", "N000001", "--metric", "euclidean", "--input", "old.csv"]
            changed = [sys.executable, "skill-launch.py", "--node-id", "N000001", "--metric", "manhattan", "--input", "old.csv"]
            command_path = recovery / "command.json"
            command_path.write_text(json.dumps({"node_id": "N000001", "command_argv": changed}), encoding="utf-8")
            manifest = {
                "schema_version": "1.0.0", "node_id": "N000001", "attempt_id": "ATT0002",
                "node_signature": "a" * 64, "failure_classification": "argument_contract_mismatch",
                "reason": "test", "changed_contract_fields": ["option_alias"],
                "scientific_invariants_unchanged": True, "command_hash": RUNTIME.value_hash(changed),
                "temporary_file_hashes": {}, "created_at": RUNTIME.utc_now(),
            }
            manifest_path = recovery / "recovery_manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            packet = {"execution_contracts": [{
                "node_id": "N000001", "attempt_id": "ATT0002", "node_signature": "a" * 64,
                "scratch": str(scratch), "command_argv": base,
                "prior_failure_pointer": str(prior.relative_to(root)),
            }]}
            with self.assertRaises(PermissionError):
                RUNTIME._load_recovery_override(root, packet, str(command_path), str(manifest_path))


if __name__ == "__main__":
    unittest.main()
