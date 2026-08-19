from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock


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
        orchestrator_manifest = tomllib.loads((skill.parent / "env" / "pixi.toml").read_text(encoding="utf-8"))
        self.assertEqual({"python"}, set(orchestrator_manifest["dependencies"]))
        self.assertIn("py_compile", orchestrator_manifest["tasks"]["smoke"])
        orchestrator_runner = (skill.parent / "scripts" / "run.py").read_text(encoding="utf-8")
        self.assertIn("cs-conductor-runtime", orchestrator_runner)
        self.assertNotIn('"runtime_controller.py"', orchestrator_runner)
        runtime_manifest = tomllib.loads((ROOT / ".claude" / "skills" / "cs-conductor-runtime" / "env" / "pixi.toml").read_text(encoding="utf-8"))
        for dependency in ("jsonschema", "pandas", "pyarrow"):
            self.assertIn(dependency, runtime_manifest["dependencies"])
            self.assertIn(dependency, runtime_manifest["tasks"]["smoke"])
        self.assertFalse((ROOT / ".claude" / "agents" / "cs-conductor-orchestrator.md").exists())
        self.assertTrue((ROOT / ".claude" / "agents" / "cs-conductor-executor.md").is_file())
        self.assertTrue((ROOT / ".claude" / "agents" / "cs-conductor-interpreter.md").is_file())

        executor = (ROOT / ".claude" / "agents" / "cs-conductor-executor.md").read_text(encoding="utf-8")
        frontmatter = executor.split("---", 2)[1]
        executor_tools = next(line for line in frontmatter.splitlines() if line.startswith("tools:"))
        self.assertNotIn("Agent", executor_tools)
        self.assertNotIn("Skill", executor_tools)
        for instruction in ("short-lived", "execute exactly once", "End after this single Runtime call", "never start a second packet"):
            self.assertIn(instruction, executor)

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
            self.assertTrue(packet["execution_contracts"])
            self.assertTrue(all(contract["command_argv"][0] == RUNTIME.RUNTIME_PYTHON_TOKEN for contract in packet["execution_contracts"]))
            for contract in packet["execution_contracts"]:
                scratch = Path(contract["scratch"])
                skill_output = Path(contract["skill_output"])
                self.assertEqual(scratch / "output", skill_output)
                output_option = contract["command_argv"].index("--output-dir")
                self.assertEqual(str(skill_output), contract["command_argv"][output_option + 1])
                self.assertFalse(skill_output.exists())
            control = json.loads((run_root / "conductor_control.json").read_text(encoding="utf-8"))
            validated = RUNTIME._validate_execution_packet(run_root, control, packet_path, response["executor_token"])
            self.assertEqual(response["packet_id"], validated["packet_id"])

            heartbeat = json.loads(self.command("heartbeat", "--run-root", str(run_root), "--lease-token", lease, "--action-token", action).stdout)
            self.assertNotEqual(action, heartbeat["action_token"])
            changed = json.loads((run_root / "conductor_control.json").read_text(encoding="utf-8"))
            with self.assertRaises(PermissionError):
                RUNTIME._validate_execution_packet(run_root, changed, packet_path, response["executor_token"])

    def test_skill_command_hash_is_independent_of_controller_python(self) -> None:
        capability = RUNTIME.catalog()["D001"]
        control = {"run": {"project": "test", "run_id": "run-013", "input": "input.csv", "smiles_column": "smiles"}}
        node = {
            "node_id": "N000001", "capability_id": "D001", "skill_name": capability["skill_name"],
            "assigned_round": "RND0001", "kind": "description", "input_nodes": [], "parameters": {},
        }
        snapshot = {"nodes": [node]}
        scratch = ROOT / "scratch" / "N000001" / "ATT0001"
        with mock.patch.object(RUNTIME.sys, "executable", "/orchestrator/env/python"):
            prepared = RUNTIME._skill_command(ROOT, control, snapshot, node, "ATT0001", scratch)
            prepared_resolved = RUNTIME._resolve_skill_command(prepared)
        with mock.patch.object(RUNTIME.sys, "executable", "/runtime/env/python"):
            executed = RUNTIME._skill_command(ROOT, control, snapshot, node, "ATT0001", scratch)
            executed_resolved = RUNTIME._resolve_skill_command(executed)

        self.assertEqual(RUNTIME.RUNTIME_PYTHON_TOKEN, prepared[0])
        self.assertEqual(str(scratch / "output"), prepared[prepared.index("--output-dir") + 1])
        self.assertEqual(prepared, executed)
        self.assertEqual(RUNTIME.value_hash(prepared), RUNTIME.value_hash(executed))
        self.assertEqual("/orchestrator/env/python", prepared_resolved[0])
        self.assertEqual("/runtime/env/python", executed_resolved[0])
        self.assertEqual(prepared_resolved[1:], executed_resolved[1:])
        with self.assertRaises(PermissionError):
            RUNTIME._resolve_skill_command(["/unexpected/python", *prepared[1:]])

    def test_direct_structure_skills_receive_resolved_smiles_column(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "input.csv"
            source.write_text(
                "compound_id,Standardized_SMILES,pIC50\nCMP1,CCO,5.1\nCMP2,CCN,5.4\n",
                encoding="utf-8",
            )
            run_root = base / "run"
            self.command(
                "init", "--input", str(source), "--endpoint", "pIC50", "--higher-is-better",
                "--project", "test", "--parallel-limit", "2", "--run-id", "smiles-column",
                "--output-dir", str(run_root),
            )
            control = json.loads((run_root / "conductor_control.json").read_text(encoding="utf-8"))
            self.assertEqual("Standardized_SMILES", control["run"]["smiles_column"])
            description_capability = RUNTIME.catalog()["D001"]
            description_node = {
                "node_id": "N000100", "capability_id": "D001",
                "skill_name": description_capability["skill_name"], "assigned_round": "RND0001",
                "kind": "description", "input_nodes": [], "parameters": {},
            }
            description_command = RUNTIME._skill_command(
                ROOT, control, {"nodes": [description_node]}, description_node, "ATT0001",
                base / "D001" / "ATT0001",
            )
            self.assertEqual(
                "Standardized_SMILES",
                description_command[description_command.index("--smiles-column") + 1],
            )
            for capability_id in ("C001", "C002", "C003", "C004"):
                capability = RUNTIME.catalog()[capability_id]
                node = {
                    "node_id": f"N{int(capability_id[1:]):06d}", "capability_id": capability_id,
                    "skill_name": capability["skill_name"], "assigned_round": "RND0001",
                    "kind": "clustering", "input_nodes": [], "parameters": {"min_cluster_size": 5},
                }
                command = RUNTIME._skill_command(
                    ROOT, control, {"nodes": [node]}, node, "ATT0001", base / capability_id / "ATT0001",
                )
                option = command.index("--smiles-column")
                self.assertEqual("Standardized_SMILES", command[option + 1])

            for capability_id in ("A006", "A009", "A013"):
                capability = RUNTIME.catalog()[capability_id]
                node = {
                    "node_id": f"N{100 + int(capability_id[1:]):06d}", "capability_id": capability_id,
                    "skill_name": capability["skill_name"], "assigned_round": "RND0001",
                    "kind": "analysis", "input_nodes": [], "parameters": {}, "scope": {"mode": "global"},
                }
                command = RUNTIME._skill_command(
                    ROOT, control, {"nodes": [node]}, node, "ATT0001", base / capability_id / "ATT0001",
                )
                option = command.index("--smiles-column")
                self.assertEqual("Standardized_SMILES", command[option + 1])

            capability = RUNTIME.catalog()["A001"]
            nonstructure_node = {
                "node_id": "N000201", "capability_id": "A001", "skill_name": capability["skill_name"],
                "assigned_round": "RND0001", "kind": "analysis", "input_nodes": [],
                "parameters": {}, "scope": {"mode": "global"},
            }
            nonstructure_command = RUNTIME._skill_command(
                ROOT, control, {"nodes": [nonstructure_node]}, nonstructure_node, "ATT0001",
                base / "A001" / "ATT0001",
            )
            self.assertNotIn("--smiles-column", nonstructure_command)

    def test_runtime_passes_only_the_canonical_description_result_downstream(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        control = {
            "run": {
                "project": "test", "run_id": "run-013", "input": "input.csv",
                "endpoint": "pIC50", "higher_is_better": True, "smiles_column": "smiles",
            }
        }
        description_capability = RUNTIME.catalog()["D001"]
        description = {
            "node_id": "N000001", "capability_id": "D001", "skill_name": description_capability["skill_name"],
            "assigned_round": "RND0001", "kind": "description", "input_nodes": [], "parameters": {},
            "output_ref": str(base / "description" / "N000001"),
        }
        description_output = Path(description["output_ref"])
        description_output.mkdir(parents=True)
        (description_output / "features.csv").write_text("compound_id,f1\nC001,1\nC002,2\n", encoding="utf-8")
        RUNTIME.write_json(
            description_output / "result.json",
            {
                "document_type": "description_result", "schema_version": "1.0.0", "node_id": "N000001", "capability_id": "D001",
                "payload": "features.csv", "row_count": 2, "feature_count": 1,
                "value_semantics": "dense_continuous", "natural_metric": "euclidean",
                "feature_columns": ["f1"], "quality_flags": [], "created_at": RUNTIME.utc_now(),
            },
        )
        for capability_id, kind in (("C005", "clustering"), ("A003", "analysis"), ("A004", "analysis")):
            capability = RUNTIME.catalog()[capability_id]
            node = {
                "node_id": f"N{int(capability_id[1:]) + 10:06d}", "capability_id": capability_id,
                "skill_name": capability["skill_name"], "assigned_round": "RND0001", "kind": kind,
                "input_nodes": [description["node_id"]], "parameters": {}, "scope": {"mode": "global"},
            }
            command = RUNTIME._skill_command(
                ROOT, control, {"nodes": [description, node]}, node, "ATT0001",
                base / capability_id / "ATT0001",
            )
            option = command.index("--description-result")
            self.assertEqual(str(Path(description["output_ref"]) / "result.json"), command[option + 1])

    def test_canonical_result_identity_and_artifact_paths_are_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "description" / "N000001"
            output.mkdir(parents=True)
            node = {
                "node_id": "N000001", "capability_id": "D001", "kind": "description",
                "output_ref": str(output),
            }
            payload = output / "features.csv"
            payload.write_text("compound_id,f1\nC001,1\n", encoding="utf-8")
            result = {
                "document_type": "description_result", "schema_version": "1.0.0",
                "node_id": "N000001", "capability_id": "D001", "payload": payload.name,
                "row_count": 1, "feature_count": 1, "value_semantics": "dense_continuous",
                "natural_metric": "euclidean", "feature_columns": ["f1"], "quality_flags": [],
                "created_at": RUNTIME.utc_now(),
            }
            RUNTIME.write_json(output / "result.json", result)
            self.assertEqual(payload, RUNTIME._primary_payload(node))
            result["capability_id"] = "D002"
            RUNTIME.write_json(output / "result.json", result)
            with self.assertRaises(Exception):
                RUNTIME._canonical_result(node)
            with self.assertRaises(ValueError):
                RUNTIME._skill_artifact_path(root, "../escaped.json")

    def test_init_requires_explicit_smiles_column_only_when_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "input.csv"
            source.write_text(
                "compound_id,parent_smiles,product_smiles,pIC50\nCMP1,CCO,CCN,5.1\n",
                encoding="utf-8",
            )
            failed = self.command(
                "init", "--input", str(source), "--endpoint", "pIC50", "--higher-is-better",
                "--project", "test", "--parallel-limit", "1", "--run-id", "ambiguous",
                "--output-dir", str(base / "failed-run"), ok=False,
            )
            self.assertIn("Ambiguous SMILES columns", failed.stderr)
            run_root = base / "explicit-run"
            self.command(
                "init", "--input", str(source), "--smiles-column", "product_smiles",
                "--endpoint", "pIC50", "--higher-is-better", "--project", "test",
                "--parallel-limit", "1", "--run-id", "explicit", "--output-dir", str(run_root),
            )
            control = json.loads((run_root / "conductor_control.json").read_text(encoding="utf-8"))
            self.assertEqual("product_smiles", control["run"]["smiles_column"])

    def test_legacy_run_without_smiles_metadata_uses_deterministic_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "input.csv"
            source.write_text(
                "compound_id,source_SMILES_text,pIC50\nCMP1,CCO,5.1\nCMP2,CCN,5.4\n",
                encoding="utf-8",
            )
            control = {"run": {"project": "test", "run_id": "legacy", "input": str(source)}}
            capability = RUNTIME.catalog()["C001"]
            node = {
                "node_id": "N000001", "capability_id": "C001", "skill_name": capability["skill_name"],
                "assigned_round": "RND0001", "kind": "clustering", "input_nodes": [],
                "parameters": {"min_cluster_size": 5},
            }
            command = RUNTIME._skill_command(
                ROOT, control, {"nodes": [node]}, node, "ATT0001", base / "scratch" / "ATT0001",
            )
            option = command.index("--smiles-column")
            self.assertEqual("source_SMILES_text", command[option + 1])

    def test_legacy_run_can_record_explicit_smiles_column_when_resumed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "input.csv"
            source.write_text(
                "compound_id,molecule_text,pIC50\nCMP1,CCO,5.1\nCMP2,CCN,5.4\n",
                encoding="utf-8",
            )
            run_root = base / "run"
            self.command(
                "init", "--input", str(source), "--smiles-column", "molecule_text",
                "--endpoint", "pIC50", "--higher-is-better", "--project", "test",
                "--parallel-limit", "1", "--run-id", "legacy-explicit", "--output-dir", str(run_root),
            )
            control_path = run_root / "conductor_control.json"
            legacy_control = json.loads(control_path.read_text(encoding="utf-8"))
            legacy_control["run"].pop("smiles_column")
            RUNTIME.write_json(control_path, legacy_control)
            prepared = json.loads(self.command(
                "prepare-round", "--run-root", str(run_root), "--objective", "legacy resume",
                "--walltime-minutes", "60", "--parallel-limit", "1", "--approve-high-cost",
            ).stdout)
            control_key = (run_root / "runtime" / "control_authority.key").read_text(encoding="utf-8").strip()
            self.command(
                "authorize-round", "--run-root", str(run_root), "--control-key", control_key,
                "--request-file", prepared["request_file"],
                "--authorization-token", prepared["authorization_token"],
            )
            resumed = json.loads(self.command(
                "resume-round", "--run-root", str(run_root), "--control-key", control_key,
                "--owner-id", "legacy-main", "--smiles-column", "molecule_text",
            ).stdout)
            self.assertTrue(resumed["lease_acquired"])
            control = json.loads(control_path.read_text(encoding="utf-8"))
            self.assertEqual("molecule_text", control["run"]["smiles_column"])

    def test_runtime_management_files_do_not_dirty_skill_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scratch = Path(temporary) / "ATT0001"
            scratch.mkdir()
            skill_output = RUNTIME._skill_output_dir(scratch)
            logical = [RUNTIME.RUNTIME_PYTHON_TOKEN, "empty-output-check"]
            script = (
                "from pathlib import Path; import sys; "
                "output=Path(sys.argv[1]); "
                "assert not output.exists(), 'skill output was pre-created'; "
                "output.mkdir(); (output/'ok.txt').write_text('ok', encoding='utf-8')"
            )
            outcome = RUNTIME._run_one(
                [sys.executable, "-c", script, str(skill_output)],
                scratch / "run.log",
                scratch / "process.json",
                30,
                RUNTIME.value_hash(logical),
            )

            self.assertEqual(0, outcome["returncode"])
            self.assertTrue((scratch / "tmp").is_dir())
            self.assertTrue((scratch / "process.json").is_file())
            self.assertEqual("ok", (skill_output / "ok.txt").read_text(encoding="utf-8"))
            process = json.loads((scratch / "process.json").read_text(encoding="utf-8"))
            self.assertEqual(RUNTIME.value_hash(logical), process["command_hash"])
            self.assertEqual(sys.executable, process["runtime_python"])

    def test_only_empty_or_recovery_scratch_can_be_reused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scratch = Path(temporary) / "ATT0001"
            scratch.mkdir()
            RUNTIME._validate_attempt_scratch(scratch, recovery_allowed=False)
            recovery = scratch / "recovery"
            recovery.mkdir()
            RUNTIME._validate_attempt_scratch(scratch, recovery_allowed=True)
            with self.assertRaises(FileExistsError):
                RUNTIME._validate_attempt_scratch(scratch, recovery_allowed=False)
            (scratch / "process.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                RUNTIME._validate_attempt_scratch(scratch, recovery_allowed=True)

    def test_invalid_execution_contract_does_not_create_attempt_scratch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_root, lease, action = self.active_basic_round(Path(temporary))
            response = json.loads(self.command(
                "prepare-execution-packet", "--run-root", str(run_root),
                "--lease-token", lease, "--action-token", action, "--timeout-minutes", "5",
            ).stdout)
            packet = json.loads(Path(response["packet_path"]).read_text(encoding="utf-8"))
            scratch_paths = [Path(contract["scratch"]) for contract in packet["execution_contracts"]]
            original = RUNTIME._skill_command

            def changed_command(*arguments: object, **keywords: object) -> list[str]:
                command = original(*arguments, **keywords)
                return [*command, "--unexpected-contract-change"]

            arguments = argparse.Namespace(
                run_root=str(run_root), packet=response["packet_path"], executor_token=response["executor_token"],
                recovery_command=None, recovery_manifest=None,
            )
            with mock.patch.object(RUNTIME, "_skill_command", side_effect=changed_command):
                with self.assertRaises(PermissionError):
                    RUNTIME.cmd_execute_packet(arguments)
            self.assertTrue(all(not path.exists() for path in scratch_paths))

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
            base = [RUNTIME.RUNTIME_PYTHON_TOKEN, "skill-launch.py", "--node-id", "N000001", "--metric", "euclidean", "--input", "old.csv"]
            changed = [RUNTIME.RUNTIME_PYTHON_TOKEN, "skill-launch.py", "--node-id", "N000001", "--metric", "manhattan", "--input", "old.csv"]
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
