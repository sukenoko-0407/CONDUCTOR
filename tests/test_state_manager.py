from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
STATE_MANAGER = ROOT / ".claude" / "skills" / "cs-conductor-orchestrator" / "scripts" / "state_manager.py"
SPEC = importlib.util.spec_from_file_location("state_manager", STATE_MANAGER)
assert SPEC and SPEC.loader
STATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STATE)


class StateLogicTests(unittest.TestCase):
    def state(self) -> dict:
        return {
            "schema_version": "1.0.0",
            "conductor_version": "4.0.0",
            "run": {"run_id": "R", "project": "P", "input": "input.csv", "input_hash": "0" * 64, "endpoint": "pIC50", "higher_is_better": True, "parallel_limit": 2, "created_at": "2026-01-01T00:00:00+00:00"},
            "execution_graph": {"nodes": [], "edges": []},
            "domain_graph": {}, "evidence_graph": {}, "history": [], "updated_at": "2026-01-01T00:00:00+00:00",
        }

    def test_dependencies_and_approval_control_runnable_nodes(self) -> None:
        state = self.state()
        low = {"capability_id": "D001", "skill_name": "description", "stage": "description", "cost": {"class": "low", "human_approval_required": False}}
        high = {"capability_id": "D016", "skill_name": "mordred-3d", "stage": "description", "cost": {"class": "high", "human_approval_required": True}}
        first = STATE.add_node(state, low)
        second = STATE.add_node(state, high, [first["node_id"]])
        self.assertEqual([first["node_id"]], [node["node_id"] for node in STATE.runnable_nodes(state)])
        first["status"] = "succeeded"
        self.assertEqual([], STATE.runnable_nodes(state))
        second["human_approval"] = "approved"
        self.assertEqual([second["node_id"]], [node["node_id"] for node in STATE.runnable_nodes(state)])

    def test_rejected_or_failed_upstream_terminally_skips_blocked_descendants(self) -> None:
        state = self.state()
        capability = {"capability_id": "D016", "skill_name": "mordred-3d", "stage": "description", "cost": {"class": "high", "human_approval_required": True}}
        analysis = {"capability_id": "A001", "skill_name": "profile", "stage": "analysis", "cost": {"class": "low", "human_approval_required": False}}
        interpretation = {"capability_id": "I001", "skill_name": "interpret", "stage": "interpretation", "cost": {"class": "low", "human_approval_required": False}}
        upstream = STATE.add_node(state, capability, phase="wide_shallow", coverage_axis="high_cost_3d")
        dependent = STATE.add_node(state, analysis, [upstream["node_id"]], phase="wide_shallow", coverage_axis="group_activity_profile")
        leaf = STATE.add_node(state, interpretation, [dependent["node_id"]])
        skipped = STATE.skip_blocked_descendants(state, upstream["node_id"], "human rejected high-cost node")
        upstream["status"] = "skipped"
        self.assertEqual({dependent["node_id"], leaf["node_id"]}, set(skipped))
        self.assertEqual("skipped", dependent["status"])
        self.assertEqual("human rejected high-cost node", dependent["skip_reason"])
        self.assertTrue(STATE.wide_shallow_summary(state)["terminal"])

    def test_approval_rejection_command_records_reason_and_propagates_skip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state = self.state()
            capability = {"capability_id": "D016", "skill_name": "mordred-3d", "stage": "description", "cost": {"class": "high", "human_approval_required": True}}
            analysis = {"capability_id": "A001", "skill_name": "profile", "stage": "analysis", "cost": {"class": "low", "human_approval_required": False}}
            upstream = STATE.add_node(state, capability, phase="wide_shallow", coverage_axis="high_cost_3d")
            dependent = STATE.add_node(state, analysis, [upstream["node_id"]], phase="wide_shallow", coverage_axis="group_activity_profile")
            state_path.write_text(json.dumps(state), encoding="utf-8")
            STATE.cmd_approve(SimpleNamespace(state=str(state_path), node_id=upstream["node_id"], approve=False, rationale="budget not approved"))
            recorded = json.loads(state_path.read_text(encoding="utf-8"))
            nodes = {node["node_id"]: node for node in recorded["execution_graph"]["nodes"]}
            self.assertEqual("rejected", nodes[upstream["node_id"]]["human_approval"])
            self.assertEqual("skipped", nodes[upstream["node_id"]]["status"])
            self.assertEqual("skipped", nodes[dependent["node_id"]]["status"])
            self.assertIn("D016:001", nodes[dependent["node_id"]]["skip_reason"])

    def test_downstream_traversal(self) -> None:
        state = self.state()
        state["execution_graph"]["edges"] = [
            {"source": "D001:001", "target": "C001:001", "relation": "depends_on"},
            {"source": "C001:001", "target": "A001:001", "relation": "depends_on"},
        ]
        self.assertEqual({"C001:001", "A001:001"}, STATE.downstream(state, "D001:001"))

    def test_running_nodes_consume_slots_and_failures_are_terminal(self) -> None:
        state = self.state()
        state["run"]["parallel_limit"] = 1
        capability = {"capability_id": "D001", "skill_name": "description", "stage": "description", "cost": {"class": "low", "human_approval_required": False}}
        first = STATE.add_node(state, capability)
        second = STATE.add_node(state, capability)
        first["status"] = "running"
        self.assertEqual([], STATE.runnable_nodes(state))
        first["status"] = "failed"
        self.assertEqual([second["node_id"]], [node["node_id"] for node in STATE.runnable_nodes(state)])

    def test_wide_nodes_are_prioritized_and_gate_interpretation(self) -> None:
        state = self.state()
        state["run"]["parallel_limit"] = 3
        interpretation = {"capability_id": "I001", "skill_name": "interpret", "stage": "interpretation", "cost": {"class": "low", "human_approval_required": False}}
        deep = {"capability_id": "D015", "skill_name": "deep", "stage": "description", "cost": {"class": "medium", "human_approval_required": False}}
        wide = {"capability_id": "D001", "skill_name": "wide", "stage": "description", "cost": {"class": "low", "human_approval_required": False}}
        interpretation_node = STATE.add_node(state, interpretation)
        deep_node = STATE.add_node(state, deep)
        wide_node = STATE.add_node(state, wide, phase="wide_shallow", coverage_axis="physicochemical_2d")
        self.assertEqual([wide_node["node_id"], deep_node["node_id"]], [node["node_id"] for node in STATE.runnable_nodes(state)])
        wide_node["status"] = "succeeded"
        self.assertEqual([deep_node["node_id"], interpretation_node["node_id"]], [node["node_id"] for node in STATE.runnable_nodes(state)])

    def test_derived_graph_nodes_can_be_invalidated_by_source(self) -> None:
        state = self.state()
        state["domain_graph"]["nodes"] = [{"group_id": "G1", "source_node_id": "C001:001", "status": "active"}]
        state["evidence_graph"]["nodes"] = [{"evidence_id": "E1", "source_node_id": "A001:001", "status": "active"}]
        STATE.set_derived_graph_status(state, {"C001:001", "A001:001"}, "stale")
        self.assertEqual("stale", state["domain_graph"]["nodes"][0]["status"])
        self.assertEqual("stale", state["evidence_graph"]["nodes"][0]["status"])

    def test_wide_plan_covers_representative_families_and_binds_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state = self.state()
            state["run"]["input"] = str((ROOT / "tests" / "data" / "small_sar.csv").resolve())
            state_path.write_text(json.dumps(state), encoding="utf-8")

            with redirect_stdout(io.StringIO()):
                STATE.cmd_plan_wide(SimpleNamespace(state=str(state_path)))
            planned = json.loads(state_path.read_text(encoding="utf-8"))
            nodes = planned["execution_graph"]["nodes"]

            description_ids = {node["capability_id"] for node in nodes if node["stage"] == "description"}
            grouping_nodes = [node for node in nodes if node["stage"] == "grouping"]
            analysis_nodes = [node for node in nodes if node["stage"] == "analysis"]
            self.assertEqual({"D001", "D002", "D003", "D004", "D007", "D013", "D017"}, description_ids)
            self.assertEqual(9, len(grouping_nodes))
            self.assertEqual({"C001", "C002", "C003", "C005", "C006", "C007", "C009"}, {node["capability_id"] for node in grouping_nodes})
            self.assertEqual(35, len(analysis_nodes))
            self.assertEqual({f"A{index:03d}" for index in range(1, 11)}, {node["capability_id"] for node in analysis_nodes})

            c005 = [node for node in grouping_nodes if node["capability_id"] == "C005"]
            self.assertEqual({"D002:001"}, {node["input_bindings"]["description"] for node in c005})
            c006 = [node for node in grouping_nodes if node["capability_id"] == "C006"]
            self.assertEqual({"D001:001", "D013:001", "D017:001"}, {node["input_bindings"]["description"] for node in c006})
            c007 = [node for node in grouping_nodes if node["capability_id"] == "C007"]
            self.assertEqual({"D001:001"}, {node["input_bindings"]["description"] for node in c007})
            c009 = [node for node in grouping_nodes if node["capability_id"] == "C009"]
            self.assertEqual({"D002:001"}, {node["input_bindings"]["description"] for node in c009})
            mcs = next(node for node in grouping_nodes if node["capability_id"] == "C002")
            self.assertEqual("not_required", mcs["human_approval"])
            a004 = [node for node in analysis_nodes if node["capability_id"] == "A004"]
            self.assertEqual({"D001:001", "D013:001"}, {node["input_bindings"]["description"] for node in a004})
            a006 = [node for node in analysis_nodes if node["capability_id"] == "A006"]
            self.assertEqual({"D002:001", "D013:001", "D017:001"}, {node["input_bindings"]["description"] for node in a006})
            a001 = [node for node in analysis_nodes if node["capability_id"] == "A001"]
            self.assertEqual({node["node_id"] for node in grouping_nodes}, {node["input_bindings"]["grouping"] for node in a001})

            output_dirs = [node["output_dir"] for node in nodes]
            self.assertEqual(len(output_dirs), len(set(output_dirs)))
            self.assertTrue(all(":" not in Path(path).name for path in output_dirs))
            self.assertEqual(51, len(nodes))
            self.assertEqual("representative-family-wide-v1", planned["wide_shallow_plan"]["profile"])
            self.assertIn("shape_and_3d_pharmacophore", planned["wide_shallow_plan"]["required_axes"]["description"])

            with redirect_stdout(io.StringIO()):
                STATE.cmd_plan_wide(SimpleNamespace(state=str(state_path)))
            replanned = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(51, len(replanned["execution_graph"]["nodes"]))


if __name__ == "__main__":
    unittest.main()
