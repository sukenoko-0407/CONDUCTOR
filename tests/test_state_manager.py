from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


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
        high = {"capability_id": "C002", "skill_name": "mcs", "stage": "grouping", "cost": {"class": "high", "human_approval_required": True}}
        first = STATE.add_node(state, low)
        second = STATE.add_node(state, high, [first["node_id"]])
        self.assertEqual([first["node_id"]], [node["node_id"] for node in STATE.runnable_nodes(state)])
        first["status"] = "succeeded"
        self.assertEqual([], STATE.runnable_nodes(state))
        second["human_approval"] = "approved"
        self.assertEqual([second["node_id"]], [node["node_id"] for node in STATE.runnable_nodes(state)])

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

    def test_derived_graph_nodes_can_be_invalidated_by_source(self) -> None:
        state = self.state()
        state["domain_graph"]["nodes"] = [{"group_id": "G1", "source_node_id": "C001:001", "status": "active"}]
        state["evidence_graph"]["nodes"] = [{"evidence_id": "E1", "source_node_id": "A001:001", "status": "active"}]
        STATE.set_derived_graph_status(state, {"C001:001", "A001:001"}, "stale")
        self.assertEqual("stale", state["domain_graph"]["nodes"][0]["status"])
        self.assertEqual("stale", state["evidence_graph"]["nodes"][0]["status"])


if __name__ == "__main__":
    unittest.main()
