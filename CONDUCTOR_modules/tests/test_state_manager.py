from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / "CONDUCTOR_modules"
STATE_MANAGER = ROOT / ".claude" / "skills" / "cs-conductor-orchestrator" / "scripts" / "state_manager.py"
SPEC = importlib.util.spec_from_file_location("state_manager_v43", STATE_MANAGER)
assert SPEC and SPEC.loader
STATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STATE)


class StateManagerTests(unittest.TestCase):
    def cli(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(STATE_MANAGER), *arguments], cwd=ROOT,
            check=check, text=True, capture_output=True,
        )

    def initialize(self, directory: Path, run_id: str = "unit_run") -> Path:
        input_path = MODULES / "tests" / "data" / "small_sar.csv"
        self.cli(
            "init", "--input", str(input_path), "--endpoint", "pIC50", "--higher-is-better",
            "--assay-column", "assay", "--project", "unit", "--parallel-limit", "3",
            "--run-id", run_id, "--output-dir", str(directory), "--request", "Round 1 unit test",
        )
        return directory / "state.json"

    def test_init_creates_multiround_state_and_derived_indices(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = self.initialize(Path(directory))
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual("2.0.0", state["schema_version"])
            self.assertEqual("RND0001", state["round_control"]["active_round_id"])
            self.assertEqual(2, state["round_control"]["next_round_number"])
            self.assertEqual("comprehensive-multiround-v1", state["run"]["profile_id"])
            self.assertEqual(0, state["id_counters"]["description_node"])
            for key in ["coverage", "group", "evidence_digest", "salience", "questions", "relations", "findings", "hypotheses", "requests"]:
                self.assertIn(key, state["indices"])
            self.assertTrue((state_path.parent / "summaries" / "state_summary.json").is_file())
            self.assertTrue((state_path.parent / "rounds" / "RND0001" / "round_request.md").is_file())

    def test_basic_plan_is_comprehensive_and_uses_one_bundle_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = self.initialize(Path(directory))
            self.cli("plan-basic", "--state", str(state_path))
            state = json.loads(state_path.read_text(encoding="utf-8"))
            nodes = state["execution_graph"]["nodes"]
            descriptions = [node for node in nodes if node["stage"] == "description"]
            groupings = [node for node in nodes if node["stage"] == "grouping"]
            catalog = json.loads((MODULES / "catalog" / "catalog.json").read_text(encoding="utf-8"))
            expected_descriptions = {item["capability_id"] for item in catalog["capabilities"] if item["stage"] == "description"}
            self.assertEqual(expected_descriptions, {node["capability_id"] for node in descriptions})
            root_groupings = {node["capability_id"] for node in groupings if not node["dependencies"]}
            self.assertTrue({"C001", "C002", "C003", "C004"}.issubset(root_groupings))
            self.assertIn("C011", root_groupings)
            self.assertEqual(47, len(groupings))
            gated = {node["capability_id"] for node in nodes if node["human_approval"] == "bundle_pending"}
            self.assertEqual({"D016", "D019", "D020"}, gated)
            self.assertEqual("pending", state["run"]["high_cost_bundle"]["status"])
            self.assertRegex(state["run"]["high_cost_bundle"]["scope_hash"], r"^[a-f0-9]{64}$")
            self.assertTrue(all(node["node_id"].startswith("ND") for node in descriptions))
            self.assertTrue(all(node["node_id"].startswith("NG") for node in groupings))

    def test_bundle_decision_and_round_pause_resume_are_auditable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = self.initialize(Path(directory))
            self.cli("plan-basic", "--state", str(state_path))
            self.cli("approve-basic-bundle", "--state", str(state_path), "--approve", "--rationale", "one-time approval")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual("approved", state["run"]["high_cost_bundle"]["status"])
            self.assertEqual(state["run"]["high_cost_bundle"]["scope_hash"], state["run"]["high_cost_bundle"]["decided_scope_hash"])
            self.assertTrue(all(node["human_approval"] == "approved" for node in state["execution_graph"]["nodes"] if node["capability_id"] in {"D016", "D019", "D020"}))
            self.cli("round-end", "--state", str(state_path), "--round-id", "RND0001", "--status", "paused", "--reason", "checkpoint")
            paused = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual("RND0001", paused["round_control"]["active_round_id"])
            self.assertEqual("paused", paused["round_control"]["rounds"][0]["status"])
            self.cli("round-start", "--state", str(state_path), "--round-id", "RND0001", "--request", "resume")
            resumed = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual("active", resumed["round_control"]["rounds"][0]["status"])

    def test_package_change_requires_explicit_approval_before_new_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = self.initialize(Path(directory))
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["run"]["package_snapshot"]["files"]["catalog"]["sha256"] = "0" * 64
            STATE.write_state(state_path, state)

            resumed = json.loads(self.cli("resume", "--state", str(state_path)).stdout)
            self.assertTrue(resumed["package_changed"])
            self.assertEqual("approval_required", resumed["package_change_gate"]["status"])
            blocked = self.cli("plan-basic", "--state", str(state_path), check=False)
            self.assertNotEqual(0, blocked.returncode)
            self.assertIn("Package change approval is required", blocked.stderr)

            accepted = json.loads(self.cli(
                "approve-package-change", "--state", str(state_path), "--approve",
                "--rationale", "accept reviewed package for the unit Run",
            ).stdout)
            self.assertEqual("clear", accepted["status"])
            self.cli("plan-basic", "--state", str(state_path))
            updated = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(1, len(updated["run"]["package_snapshot_history"]))
            self.assertEqual("clear", updated["run"]["package_change_gate"]["status"])

    def test_analysis_signatures_are_non_repeating_and_dag_cycles_fail(self) -> None:
        signature_a = STATE.analysis_signature("A006", ["ND0002"], {"metric": "tanimoto", "output_dir": "A"}, {"scope_mode": "global"})
        signature_b = STATE.analysis_signature("A006", ["ND0002"], {"metric": "tanimoto", "output_dir": "B"}, {"scope_mode": "global"})
        self.assertEqual(signature_a, signature_b)
        cyclic = {"execution_graph": {"nodes": [{"node_id": "ND0001"}, {"node_id": "NG0001"}], "edges": [{"source": "ND0001", "target": "NG0001"}, {"source": "NG0001", "target": "ND0001"}]}}
        with self.assertRaisesRegex(ValueError, "acyclic"):
            STATE.validate_dag(cyclic)

    def test_group_index_maps_local_labels_to_run_global_boolean_columns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = self.initialize(root)
            result = json.loads(self.cli("add", "--state", str(state_path), "--capability-id", "C001", "--reason", "unit Grouping").stdout)
            node = result["node"]
            membership = root / "membership.csv"
            registry = root / "registry.json"
            with membership.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["compound_id", "cluster_id", "membership_value", "membership_reason"])
                writer.writeheader()
                for number in range(1, 7):
                    writer.writerow({"compound_id": f"CMPD_{number:03d}", "cluster_id": "local_scaffold", "membership_value": 1 if number <= 3 else 0, "membership_reason": "unit"})
            registry.write_text(json.dumps([{"group_id": "local_scaffold", "grouping_type": "partition", "sample_count": 3, "parameters": {}}]), encoding="utf-8")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            STATE.update_group_index(state_path, state, STATE.state_nodes(state)[node["node_id"]], membership, registry)
            STATE.write_state(state_path, state)
            updated = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(1, updated["indices"]["group"]["group_count"])
            registry_path = Path(updated["indices"]["group"]["registry_path"])
            with registry_path.open(encoding="utf-8", newline="") as handle:
                row = next(csv.DictReader(handle))
            self.assertRegex(row["group_id"], r"^G[0-9]{6}$")
            matrix_path = Path(updated["indices"]["group"]["matrix_shards"][0]["path"])
            with matrix_path.open(encoding="utf-8", newline="") as handle:
                matrix = list(csv.DictReader(handle))
            self.assertIn(row["group_id"], matrix[0])
            self.assertEqual("True", matrix[0][row["group_id"]])
            self.assertEqual("False", matrix[-1][row["group_id"]])

    def test_question_skip_blocks_deep_dive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = self.initialize(Path(directory))
            question = json.loads(self.cli(
                "question-add", "--state", str(state_path), "--title", "unit question",
                "--rationale", "test gate", "--deep-dive-potential", "--priority", "high",
            ).stdout)
            self.cli("question-decision", "--state", str(state_path), "--question-id", question["question_id"], "--decision", "skip", "--rationale", "human skip")
            rejected = self.cli("plan-deep-dive", "--state", str(state_path), "--question-id", question["question_id"], check=False)
            self.assertNotEqual(0, rejected.returncode)
            self.assertIn("Human decision is skip", rejected.stderr)

    def test_deep_dive_bundles_target_sibling_global_and_between_group_controls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = self.initialize(root)
            description = json.loads(self.cli(
                "add", "--state", str(state_path), "--capability-id", "D002", "--reason", "deep-dive representation",
            ).stdout)["node"]
            grouping = json.loads(self.cli(
                "add", "--state", str(state_path), "--capability-id", "C001", "--reason", "deep-dive Grouping",
            ).stdout)["node"]
            membership = root / "deep_membership.csv"
            registry = root / "deep_registry.json"
            with membership.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["compound_id", "cluster_id", "membership_value", "membership_reason"])
                writer.writeheader()
                for number in range(1, 7):
                    compound_id = f"CMPD_{number:03d}"
                    writer.writerow({"compound_id": compound_id, "cluster_id": "left", "membership_value": int(number <= 3), "membership_reason": "unit"})
                    writer.writerow({"compound_id": compound_id, "cluster_id": "right", "membership_value": int(number > 3), "membership_reason": "unit"})
            registry.write_text(json.dumps([
                {"group_id": "left", "grouping_type": "partition", "sample_count": 3, "parameters": {}},
                {"group_id": "right", "grouping_type": "partition", "sample_count": 3, "parameters": {}},
            ]), encoding="utf-8")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            STATE.state_nodes(state)[description["node_id"]]["status"] = "succeeded"
            STATE.state_nodes(state)[grouping["node_id"]]["status"] = "succeeded"
            STATE.update_group_index(state_path, state, STATE.state_nodes(state)[grouping["node_id"]], membership, registry)
            STATE.write_state(state_path, state)
            group_rows = STATE.read_csv_rows(Path(state["indices"]["group"]["registry_path"]))
            target_group = group_rows[0]["group_id"]
            sibling_group = group_rows[1]["group_id"]

            blocked_question = json.loads(self.cli(
                "question-add", "--state", str(state_path), "--title", "do not deepen yet",
                "--rationale", "negative gate", "--no-deep-dive-potential", "--target-group", target_group,
                "--operator", "A006",
            ).stdout)
            blocked = self.cli("plan-deep-dive", "--state", str(state_path), "--question-id", blocked_question["question_id"], check=False)
            self.assertNotEqual(0, blocked.returncode)
            self.assertIn("explicit human allow", blocked.stderr)

            question = json.loads(self.cli(
                "question-add", "--state", str(state_path), "--title", "compare the landscape",
                "--rationale", "target, sibling and global controls", "--deep-dive-potential",
                "--target-group", target_group, "--operator", "A006",
            ).stdout)
            planned = json.loads(self.cli(
                "plan-deep-dive", "--state", str(state_path), "--question-id", question["question_id"],
            ).stdout)["planned_nodes"]
            updated = json.loads(state_path.read_text(encoding="utf-8"))
            nodes = [STATE.state_nodes(updated)[node_id] for node_id in planned]
            scopes = {node["parameters"].get("scope_mode") for node in nodes}
            self.assertEqual({"global", "within-group", "between-groups"}, scopes)
            self.assertTrue(any(node["parameters"].get("target_group") == sibling_group for node in nodes))
            self.assertTrue(any(
                node["parameters"].get("target_group") == target_group
                and node["parameters"].get("comparison_group") == sibling_group
                for node in nodes
            ))
            history = next(item for item in reversed(updated["history"]) if item["action"] == "deep_dive_planned")
            self.assertIn("global_comparator", history["bundle_roles"])
            self.assertIn("between_group_control", history["bundle_roles"])

    def test_round_handoff_and_interpretation_ids_continue_across_rounds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = self.initialize(root)
            operator = json.loads(self.cli(
                "add", "--state", str(state_path), "--capability-id", "A002", "--reason", "unit Evidence source",
            ).stdout)["node"]
            seeded_state = json.loads(state_path.read_text(encoding="utf-8"))
            STATE.state_nodes(seeded_state)[operator["node_id"]]["status"] = "succeeded"
            STATE.write_state(state_path, seeded_state)
            first = json.loads(self.cli(
                "add-interpretation", "--state", str(state_path), "--reason", "Round 1 review",
                "--focus", "global versus local",
            ).stdout)
            self.assertTrue(first["created"])
            self.assertEqual("NI0001", first["node"]["node_id"])
            first_reservation = json.loads((Path(first["node"]["output_dir"]) / "id_reservation.json").read_text(encoding="utf-8"))
            self.assertEqual("F0001", first_reservation["finding_ids"][0])

            duplicate = json.loads(self.cli(
                "add-interpretation", "--state", str(state_path), "--reason", "retry",
                "--focus", "global versus local",
            ).stdout)
            self.assertFalse(duplicate["created"])
            self.assertEqual("NI0001", duplicate["node"]["node_id"])

            self.cli("round-end", "--state", str(state_path), "--round-id", "RND0001", "--status", "checkpoint", "--reason", "handoff")
            round_root = root / "rounds" / "RND0001"
            for name in [
                "round_manifest.json", "round_summary.json", "round_summary.md",
                "evidence_set_manifest.json", "triage_updates.json", "next_round_brief.json",
            ]:
                self.assertTrue((round_root / name).is_file(), name)
            manifest = json.loads((round_root / "round_manifest.json").read_text(encoding="utf-8"))
            self.assertIn("round_request.md", {item["name"] for item in manifest["artifacts"]})

            self.cli("round-start", "--state", str(state_path), "--round-id", "RND0002", "--request", "Round 2")
            second = json.loads(self.cli(
                "add-interpretation", "--state", str(state_path), "--reason", "Round 2 review",
                "--focus", "global versus local",
            ).stdout)
            self.assertEqual("NI0002", second["node"]["node_id"])
            second_reservation = json.loads((Path(second["node"]["output_dir"]) / "id_reservation.json").read_text(encoding="utf-8"))
            self.assertEqual("F0201", second_reservation["finding_ids"][0])

            third = json.loads(self.cli(
                "add-interpretation", "--state", str(state_path), "--reason", "alternate Round 2 review",
                "--focus", "contradictions only",
            ).stdout)
            self.assertEqual("NI0003", third["node"]["node_id"])


if __name__ == "__main__":
    unittest.main()
