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
SPEC = importlib.util.spec_from_file_location("conductor_runtime_012", CONTROLLER)
RUNTIME = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(RUNTIME)


class Runtime012Tests(unittest.TestCase):
    def command(self, *arguments: str, ok: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run([sys.executable, str(CONTROLLER), *arguments], cwd=ROOT, text=True, capture_output=True, env=os.environ.copy())
        if ok and result.returncode:
            self.fail(result.stderr or result.stdout)
        if not ok and not result.returncode:
            self.fail("Command unexpectedly succeeded")
        return result

    def initialized(self, base: Path) -> Path:
        source = base / "input.csv"
        source.write_text("compound_id,smiles,pIC50\nCMP1,CCO,5.1\nCMP2,CCN,5.4\n", encoding="utf-8")
        run_root = base / "run"
        self.command("init", "--input", str(source), "--endpoint", "pIC50", "--higher-is-better", "--project", "test", "--parallel-limit", "2", "--run-id", "run-1", "--output-dir", str(run_root))
        return run_root

    def test_round_requires_human_authorization_and_action_token_is_one_use(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_root = self.initialized(Path(temporary))
            control = json.loads((run_root / "conductor_control.json").read_text(encoding="utf-8"))
            self.assertEqual(control["required_action"]["code"], "AWAIT_HUMAN_ROUND")
            self.assertIsNone(control["active_round_id"])
            prepared = json.loads(self.command("prepare-round", "--run-root", str(run_root), "--objective", "test", "--walltime-minutes", "60", "--parallel-limit", "2", "--approve-high-cost").stdout)
            self.assertIsNone(json.loads((run_root / "conductor_control.json").read_text(encoding="utf-8"))["active_round_id"])
            dispatcher_key = (run_root / "runtime" / "dispatcher.key").read_text(encoding="utf-8").strip()
            self.command("authorize-round", "--run-root", str(run_root), "--dispatcher-key", dispatcher_key, "--request-file", prepared["request_file"], "--authorization-token", prepared["authorization_token"])
            resumed = json.loads(self.command("resume-round", "--run-root", str(run_root), "--dispatcher-key", dispatcher_key, "--owner-id", "test-session").stdout)
            lease, action = resumed["lease_token"], resumed["action_token"]
            planned = json.loads(self.command("plan-basic", "--run-root", str(run_root), "--lease-token", lease, "--action-token", action).stdout)
            self.assertNotEqual(action, planned["action_token"])
            reused = self.command("heartbeat", "--run-root", str(run_root), "--lease-token", lease, "--action-token", action, ok=False)
            self.assertIn("Action token", reused.stderr)
            snapshot = json.loads((run_root / "runtime" / "dag_snapshot.json").read_text(encoding="utf-8"))
            self.assertEqual(snapshot["nodes"][0]["node_id"], "N000001")
            self.assertTrue({node["status"] for node in snapshot["nodes"]} <= RUNTIME.NODE_STATES)
            returned = json.loads(self.command("verify-return", "--run-root", str(run_root), "--confirm-returned", "--dispatcher-key", dispatcher_key, "--owner-id", "test-session", "--start-revision", str(resumed["control"]["revision"])).stdout)
            self.assertTrue(returned["lease_reclaimed"])
            self.assertFalse(returned["lease_live"])
            self.assertTrue(returned["automatic_same_round_resume_recommended"])

    def test_required_action_enforces_interpretation_gate(self) -> None:
        control = {"active_round_id": "RND0001", "round_state": "FINALIZING", "lease": {}, "closure": {"interpretation_ready": False, "audit_ready": False}}
        snapshot = {"nodes": [], "rounds": {"RND0001": {"state": "FINALIZING"}}, "plans": {}}
        action = RUNTIME._required_action(Path("."), control, snapshot)
        self.assertEqual(action["code"], "PLAN_INTERPRETATION")
        snapshot["nodes"].append({"node_id": "N000001", "kind": "interpretation", "assigned_round": "RND0001", "status": "pending"})
        self.assertEqual(RUNTIME._required_action(Path("."), control, snapshot)["code"], "WRITE_INTERPRETATION")

    def test_writer_lock_recovers_dead_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / "runtime" / ".writer.lock").mkdir(parents=True)
            (root / "runtime" / ".writer.lock" / "owner.json").write_text(json.dumps({"pid": 99999999, "created_at": RUNTIME.utc_now()}), encoding="utf-8")
            with RUNTIME.writer_lock(root, timeout=1):
                self.assertTrue((root / "runtime" / ".writer.lock").exists())
            self.assertFalse((root / "runtime" / ".writer.lock").exists())

    def test_pending_transaction_trims_partial_ledger_tail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_root = self.initialized(Path(temporary))
            control = json.loads((run_root / "conductor_control.json").read_text(encoding="utf-8"))
            snapshot = json.loads((run_root / "runtime" / "dag_snapshot.json").read_text(encoding="utf-8"))
            revision = control["revision"] + 1
            sequence = control["last_event_sequence"] + 1
            event = RUNTIME._event(sequence, revision, control["last_event_checksum"], "test_recovery", None, None, {"test": True})
            control.update({"revision": revision, "last_event_sequence": sequence, "last_event_checksum": event["checksum"]})
            snapshot.update({"control_revision": revision, "last_event_sequence": sequence})
            RUNTIME.write_json(run_root / "runtime" / "pending_transaction.json", {"schema_version": "1.0.0", "event": event, "control": control, "snapshot": snapshot, "created_at": RUNTIME.utc_now()})
            with (run_root / "runtime" / "event_ledger.jsonl").open("ab") as handle:
                handle.write(b'{"partial":')
                handle.flush()
                os.fsync(handle.fileno())
            recovered = RUNTIME._recover_transaction(run_root)
            self.assertEqual(recovered, [event["event_id"]])
            self.assertEqual(RUNTIME._verify_ledger(run_root), (sequence, event["checksum"]))

    def test_working_set_contract_is_bounded(self) -> None:
        schema = json.loads((ROOT / "CONDUCTOR_modules" / "schemas" / "working_set.schema.json").read_text(encoding="utf-8"))
        self.assertLessEqual(schema["properties"]["candidates"]["maxItems"], 20)
        self.assertEqual(RUNTIME.MAX_CANDIDATES, 20)
        self.assertLessEqual(RUNTIME.MAX_WORKING_SET_BYTES, 64 * 1024)

    def test_interpretation_review_is_bounded_and_balanced(self) -> None:
        cards = []
        for index in range(12):
            cards.append({
                "result_ref": f"N{index + 1:06d}@ATT0001",
                "capability_id": "A001" if index < 8 else "A008",
                "analysis_subject": {
                    "scope_mode": "global" if index % 2 == 0 else "single_cluster",
                    "analysis_description_nodes": ["N000001"],
                },
            })
        manifest = RUNTIME._review_manifest("RND0001", cards, 4)
        self.assertEqual(len(manifest["detailed_result_refs"]), 4)
        self.assertEqual(len(manifest["unreviewed_results"]), 8)
        self.assertFalse(manifest["aggregate_result_refs"])
        selected = {item for item in manifest["detailed_result_refs"]}
        selected_cards = [card for card in cards if card["result_ref"] in selected]
        self.assertEqual({card["capability_id"] for card in selected_cards}, {"A001", "A008"})
        self.assertEqual({card["analysis_subject"]["scope_mode"] for card in selected_cards}, {"global", "single_cluster"})

    def test_reconcile_running_is_a_public_runtime_command(self) -> None:
        parsed = RUNTIME.build_parser().parse_args(["reconcile-running", "--run-root", "run", "--lease-token", "lease", "--action-token", "action"])
        self.assertIs(parsed.func, RUNTIME.cmd_reconcile_running)

    def test_succeeded_node_reuse_is_explicit_in_new_round(self) -> None:
        signature = RUNTIME._signature("D001", [], {"mode": "not_applicable"}, {})
        node = {"node_id": "N000001", "signature": signature, "status": "succeeded", "created_in_round": "RND0001"}
        snapshot = {"nodes": [node], "rounds": {"RND0002": {}}, "counters": {"node": 1}}
        control = {"active_round_id": "RND0002"}
        selected, created = RUNTIME._add_node(snapshot, control, "D001", [], "basic_compute", {"mode": "not_applicable"}, {})
        self.assertFalse(created)
        self.assertIs(selected, node)
        self.assertEqual(snapshot["rounds"]["RND0002"]["reused_node_ids"], ["N000001"])
        self.assertEqual(RUNTIME._round_nodes(snapshot, "RND0002"), [node])

    def test_report_revision_invalidates_previous_interpretation(self) -> None:
        snapshot = {"nodes": [], "rounds": {"RND0001": {"interpretation_revision_required": True}}}
        self.assertEqual(RUNTIME._interpretation_fresh(snapshot, "RND0001"), (False, None))

    def test_init_freezes_canonical_compound_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source.csv"
            source.write_text("molecule_id,smiles,pIC50\nM1,CCO,5.0\nM2,CCN,5.2\n", encoding="utf-8")
            run_root = base / "run"
            self.command("init", "--input", str(source), "--endpoint", "pIC50", "--higher-is-better", "--project", "test", "--parallel-limit", "1", "--run-id", "canonical", "--output-dir", str(run_root))
            control = json.loads((run_root / "conductor_control.json").read_text(encoding="utf-8"))
            canonical = Path(control["run"]["input"])
            self.assertEqual(canonical, run_root / "runtime" / "input.csv")
            self.assertIn("compound_id,molecule_id,smiles,pIC50", canonical.read_text(encoding="utf-8").splitlines()[0])
            source.write_text("changed", encoding="utf-8")
            self.assertEqual(RUNTIME.file_hash(canonical), control["run"]["input_hash"])

    def test_disabled_results_are_not_reused_or_made_runnable(self) -> None:
        disabled = {
            "node_id": "N000001",
            "kind": "description",
            "capability_id": "D001",
            "signature": RUNTIME._signature("D001", [], {"mode": "not_applicable"}, {}),
            "status": "succeeded",
            "result_quality": {"eligible_for_downstream": False},
            "created_in_round": "RND0001",
        }
        pending = {
            "node_id": "N000002",
            "kind": "clustering",
            "capability_id": "C005",
            "status": "pending",
            "assigned_round": "RND0002",
            "input_nodes": ["N000001"],
            "wave": "basic_compute",
        }
        snapshot = {"nodes": [disabled, pending], "rounds": {"RND0002": {}}, "counters": {"node": 2}}
        control = {"active_round_id": "RND0002", "round_state": "ACTIVE", "run": {"parallel_limit": 2}}
        self.assertFalse(RUNTIME._succeeded(snapshot, "description"))
        self.assertFalse(RUNTIME._runnable(control, snapshot))

    def test_interpretation_scope_is_recomputed_from_result_cards(self) -> None:
        def subject(mode: str, clusters: list[str], population: int, analyzed: int) -> dict[str, object]:
            return {
                "scope_mode": mode,
                "cluster_ids": clusters,
                "clustering_input_kind": "none" if mode == "global" else "vector",
                "cluster_source_description_nodes": [] if mode == "global" else ["N000002"],
                "analysis_description_nodes": ["N000001"],
                "clustering_nodes": [] if mode == "global" else ["N000003"],
                "population_count": population,
                "endpoint_valid_count": population,
                "analyzed_count": analyzed,
                "excluded_count": population - analyzed,
                "compound_set_hash": "a" * 64,
                "cluster_overlap": None,
            }

        cards = [
            {"result_ref": "N000010@ATT0001", "capability_id": "A001", "analysis_subject": subject("global", [], 100, 96)},
            {"result_ref": "N000011@ATT0001", "capability_id": "A001", "analysis_subject": subject("single_cluster", ["C000001"], 20, 19)},
        ]
        combined = RUNTIME._combined_subject(cards)
        self.assertEqual(combined["scope_mode"], "global_vs_cluster")
        self.assertEqual(combined["cluster_ids"], ["C000001"])
        insight = {
            "insight_id": "INS000001",
            "supporting_results": [cards[0]["result_ref"]],
            "comparison_results": [cards[1]["result_ref"]],
            "counter_results": [],
            "claim_kind": "difference",
            "title": "GlobalとClusterの差異",
            "observation": "Globalと対象Clusterの解析結果を比較すると、主要指標に明確な差が観察されました。",
            "interpretation": "この差は局所的な化学空間で関係性が変化する可能性を示しますが、追加の反証確認が必要です。",
            "analysis_subject": combined,
            "fact_panel": {
                "operators": ["A001"],
                "result_samples": {cards[0]["result_ref"]: 96, cards[1]["result_ref"]: 19},
            },
        }
        report = {
            "executive_summary": "今回の解析では、Globalと対象Clusterの間で注目すべき差異を確認しました。局所性を考慮した追加検証が必要です。",
            "coverage_summary": "Global解析と単一Cluster解析の両方を対象とし、同一Operatorの結果を直接比較しました。",
            "result_catalog": cards,
            "insights": [insight],
        }
        renderer = RUNTIME._renderer_module()
        self.assertFalse(renderer.quality_issues(report))
        insight["analysis_subject"] = {**combined, "scope_mode": "global", "cluster_ids": []}
        issues = renderer.quality_issues(report)
        self.assertTrue(any("scope_mode does not match" in item for item in issues))
        self.assertTrue(any("Cluster IDs do not match" in item for item in issues))


if __name__ == "__main__":
    unittest.main()
