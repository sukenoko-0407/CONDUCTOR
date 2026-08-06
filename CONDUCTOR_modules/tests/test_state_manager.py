from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from csv import DictReader
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
MODULE_ROOT = ROOT / "CONDUCTOR_modules"
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
            "domain_graph": {}, "evidence_graph": {}, "interpretation_exploration": STATE.default_exploration_state(), "history": [], "updated_at": "2026-01-01T00:00:00+00:00",
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

    def test_execution_node_ids_are_stage_serial_not_capability_ids(self) -> None:
        state = self.state()
        low_cost = {"class": "low", "human_approval_required": False}
        first_description = STATE.add_node(state, {"capability_id": "D013", "skill_name": "shape", "stage": "description", "cost": low_cost})
        second_description = STATE.add_node(state, {"capability_id": "D013", "skill_name": "shape", "stage": "description", "cost": low_cost}, parameters={"variant": "second"})
        grouping = STATE.add_node(state, {"capability_id": "C002", "skill_name": "mcs", "stage": "grouping", "cost": low_cost})
        operator = STATE.add_node(state, {"capability_id": "A006", "skill_name": "sali", "stage": "analysis", "cost": low_cost}, [first_description["node_id"]])
        interpretation = STATE.add_node(state, {"capability_id": "I001", "skill_name": "interpret", "stage": "interpretation", "cost": low_cost}, [operator["node_id"]])
        self.assertEqual(["D001", "D002", "G001", "O001", "I001"], [
            first_description["node_id"], second_description["node_id"], grouping["node_id"], operator["node_id"], interpretation["node_id"],
        ])
        self.assertEqual("D013", first_description["capability_id"])

    def test_human_directed_interpretation_allocates_next_round_and_binds_previous(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            state_path = temporary / "state.json"
            state = self.state()
            state["run"]["input"] = str((MODULE_ROOT / "tests" / "data" / "small_sar.csv").resolve())
            capabilities = STATE.catalog_by_id(ROOT)
            evidence_node = STATE.add_node(state, capabilities["A002"], phase="wide_shallow", coverage_axis="endpoint_distribution")
            evidence_node.update({"status": "succeeded", "output_dir": str(temporary / "analysis"), "parameters": {}})
            first = STATE.add_node(state, capabilities["I001"], [evidence_node["node_id"]])
            first.update({"status": "succeeded", "output_dir": str(temporary / "interpretation" / "I001"), "parameters": {}})
            state["interpretations"] = [{"interpretation_id": "R:I001", "source_node_id": first["node_id"], "status": "active"}]
            state_path.write_text(json.dumps(state), encoding="utf-8")

            with redirect_stdout(io.StringIO()):
                STATE.cmd_add(SimpleNamespace(
                    state=str(state_path), capability_id="I001", depends_on=evidence_node["node_id"],
                    reason="Human requested a second interpretation round", parameters_json=None,
                    require_approval=False, human_request=True, previous_interpretation_node=first["node_id"],
                    node_id=None,
                ))

            updated = json.loads(state_path.read_text(encoding="utf-8"))
            second = updated["execution_graph"]["nodes"][-1]
            self.assertEqual("I002", second["node_id"])
            self.assertEqual("I001", second["capability_id"])
            self.assertEqual("human_directed", second["phase"])
            self.assertEqual("human", second["request_origin"])
            self.assertEqual(["I001"], second["previous_interpretation_nodes"])
            self.assertEqual(
                [str((temporary / "interpretation" / "I001" / "interpretation.json").resolve())],
                second["parameters"]["previous_interpretation"],
            )
            self.assertNotEqual(first["analysis_signature"], second["analysis_signature"])
            self.assertEqual("human_directed_analysis", STATE.coarse_run_phase(updated))

            updated["execution_graph"]["nodes"][-1]["status"] = "running"
            state_path.write_text(json.dumps(updated), encoding="utf-8")
            output_dir = Path(second["output_dir"])
            output_dir.mkdir(parents=True, exist_ok=True)
            interpretation_path = output_dir / "interpretation.json"
            interpretation_path.write_text(json.dumps({
                "run_id": "R", "interpretation_id": "R:I002", "created_at": "2026-01-02T00:00:00+00:00",
            }), encoding="utf-8")
            event_path = output_dir / "execution_event.json"
            event_path.write_text(json.dumps({
                "schema_version": "1.0.0", "project": "P", "run_id": "R", "node_id": "I002",
                "capability_id": "I001", "skill_name": capabilities["I001"]["skill_name"], "status": "succeeded",
                "input_hash": "1" * 64, "config_hash": "2" * 64, "configuration": second["parameters"],
                "artifacts": [{"type": "interpretation", "path": "interpretation.json", "sha256": STATE.file_hash(interpretation_path)}],
                "warnings": [], "started_at": "2026-01-02T00:00:00+00:00", "finished_at": "2026-01-02T00:01:00+00:00",
            }), encoding="utf-8")
            STATE.cmd_record(SimpleNamespace(state=str(state_path), event=str(event_path)))
            recorded = json.loads(state_path.read_text(encoding="utf-8"))
            interpretation_records = {item["source_node_id"]: item for item in recorded["interpretations"]}
            self.assertEqual("superseded", interpretation_records["I001"]["status"])
            self.assertEqual("I002", interpretation_records["I001"]["superseded_by"])
            self.assertEqual("active", interpretation_records["I002"]["status"])

    def test_discarded_group_remains_discarded_when_source_node_is_recorded_again(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            input_path = temporary / "input.csv"
            input_path.write_text("compound_id,smiles,pIC50\nA,CCO,5\nB,CCN,6\n", encoding="utf-8")
            membership_path = temporary / "cluster_membership.csv"
            membership_path.write_text(
                "cluster_id,compound_id,membership_value,membership_reason\n"
                "G_TEST,A,1,member\nG_TEST,B,0,unassigned\n",
                encoding="utf-8",
            )
            registry_path = temporary / "group_registry.json"
            registry_path.write_text(
                json.dumps([{"group_id": "G_TEST", "group_label": "test", "activity_blind": True}]),
                encoding="utf-8",
            )
            state = self.state()
            state["run"].update({"input": str(input_path), "id_column": "compound_id", "row_count": 2})
            node = {
                "node_id": "C001:001", "capability_id": "C001", "skill_name": "grouping",
                "input_bindings": {},
            }
            state_path = temporary / "state.json"
            STATE.update_group_index(state_path, state, node, membership_path, registry_path)
            STATE.write_state(state_path, state)
            with redirect_stdout(io.StringIO()):
                STATE.cmd_discard_group(SimpleNamespace(state=str(state_path), group_id="G_TEST", reason="low value"))

            discarded_state = json.loads(state_path.read_text(encoding="utf-8"))
            STATE.set_derived_graph_status(discarded_state, {node["node_id"]}, "stale")
            STATE.update_group_index(state_path, discarded_state, node, membership_path, registry_path)
            STATE.write_state(state_path, discarded_state)

            final_state = json.loads(state_path.read_text(encoding="utf-8"))
            registry_rows = STATE.read_csv_rows(Path(final_state["group_index"]["registry_path"]))
            self.assertEqual("discarded", registry_rows[0]["status"])
            self.assertEqual("discarded", final_state["domain_graph"]["nodes"][0]["status"])
            self.assertEqual(0, final_state["group_index"]["active_group_count"])
            self.assertEqual(1, final_state["group_index"]["discarded_group_count"])

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

    def test_failed_execution_event_propagates_terminal_skip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            state_path = temporary / "state.json"
            state = self.state()
            upstream_capability = {"capability_id": "D001", "skill_name": "description", "stage": "description", "cost": {"class": "low", "human_approval_required": False}}
            downstream_capability = {"capability_id": "A004", "skill_name": "correlation", "stage": "analysis", "cost": {"class": "low", "human_approval_required": False}}
            upstream = STATE.add_node(state, upstream_capability)
            downstream = STATE.add_node(state, downstream_capability, [upstream["node_id"]])
            upstream["status"] = "running"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            event = {
                "schema_version": "1.0.0", "project": "P", "run_id": "R", "node_id": upstream["node_id"],
                "capability_id": "D001", "skill_name": "description", "status": "failed",
                "input_hash": "1" * 64, "config_hash": "2" * 64, "configuration": {}, "artifacts": [],
                "warnings": ["worker terminated"], "started_at": "2026-01-01T00:00:00+00:00", "finished_at": "2026-01-01T00:01:00+00:00",
            }
            event_path = temporary / "event.json"
            event_path.write_text(json.dumps(event), encoding="utf-8")
            STATE.cmd_record(SimpleNamespace(state=str(state_path), event=str(event_path)))
            recorded = json.loads(state_path.read_text(encoding="utf-8"))
            nodes = {node["node_id"]: node for node in recorded["execution_graph"]["nodes"]}
            self.assertEqual("failed", nodes[upstream["node_id"]]["status"])
            self.assertEqual("skipped", nodes[downstream["node_id"]]["status"])
            self.assertIn("worker terminated", nodes[downstream["node_id"]]["skip_reason"])

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
            self.assertIn(upstream["node_id"], nodes[dependent["node_id"]]["skip_reason"])

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

    def test_dependency_contract_supports_meta_inputs_and_tracks_local_grouping(self) -> None:
        grouping_a = {"node_id": "C001:001", "stage": "grouping"}
        grouping_b = {"node_id": "C002:001", "stage": "grouping"}
        description = {"node_id": "D002:001", "stage": "description"}
        meta = {"capability_id": "C012", "stage": "grouping", "grouping_kind": "meta", "dependencies": ["grouping"]}
        local_sali = {"capability_id": "A006", "stage": "analysis", "dependencies": ["description"], "scope_support": ["global", "within-group", "between-groups"]}
        STATE.validate_dependency_contract(meta, [grouping_a, grouping_b])
        self.assertEqual(["C001:001", "C002:001"], STATE.dependency_bindings([grouping_a, grouping_b])["grouping"])
        STATE.validate_dependency_contract(local_sali, [description, grouping_a])
        STATE.validate_analysis_scope_contract(local_sali, [description, grouping_a], {"scope_mode": "within-group"})
        with self.assertRaisesRegex(ValueError, "requires a Grouping dependency"):
            STATE.validate_analysis_scope_contract(local_sali, [description], {"scope_mode": "within-group"})
        signature_a = STATE.analysis_signature("A006", ["D002:001"], {"description": "first.csv", "input": "run-a.csv", "metric": "tanimoto"})
        signature_b = STATE.analysis_signature("A006", ["D002:001"], {"description": "copied.csv", "input": "run-b.csv", "metric": "tanimoto"})
        self.assertEqual(signature_a, signature_b)

        state = self.state()
        state["run"]["input"] = str((MODULE_ROOT / "tests" / "data" / "small_sar.csv").resolve())
        state["execution_graph"]["nodes"] = [{
            "node_id": "D002:001", "capability_id": "D002", "skill_name": "description",
            "stage": "description", "status": "succeeded", "dependencies": [], "human_approval": "not_required",
            "output_dir": str((ROOT / "results" / "test-description").resolve()), "parameters": {},
        }]
        analysis_node = {"node_id": "A006:001", "stage": "analysis", "parameters": {"description": "rogue.csv"}, "dependencies": ["D002:001"]}
        capabilities = {
            "D002": {"stage": "description", "output": {"basename": "D002_morgan"}},
            "A006": {"capability_id": "A006", "skill_name": "cs-analysis-sali", "stage": "analysis"},
        }
        with self.assertRaisesRegex(ValueError, "CONDUCTOR-bound parameter description conflicts"):
            STATE.configure_node_io(
                state, analysis_node, capabilities["A006"], capabilities, ROOT / "results" / "test-run",
                {"description": "D002:001"},
            )

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
            state["run"]["input"] = str((MODULE_ROOT / "tests" / "data" / "small_sar.csv").resolve())
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
            self.assertEqual(36, len(analysis_nodes))
            self.assertEqual({f"A{index:03d}" for index in range(1, 11)}, {node["capability_id"] for node in analysis_nodes})
            description_node_by_capability = {
                node["capability_id"]: node["node_id"]
                for node in nodes
                if node["stage"] == "description"
            }

            c005 = [node for node in grouping_nodes if node["capability_id"] == "C005"]
            self.assertEqual({description_node_by_capability["D002"]}, {node["input_bindings"]["description"] for node in c005})
            c006 = [node for node in grouping_nodes if node["capability_id"] == "C006"]
            self.assertEqual({description_node_by_capability[value] for value in ["D001", "D013", "D017"]}, {node["input_bindings"]["description"] for node in c006})
            c007 = [node for node in grouping_nodes if node["capability_id"] == "C007"]
            self.assertEqual({description_node_by_capability["D001"]}, {node["input_bindings"]["description"] for node in c007})
            c009 = [node for node in grouping_nodes if node["capability_id"] == "C009"]
            self.assertEqual({description_node_by_capability["D002"]}, {node["input_bindings"]["description"] for node in c009})
            mcs = next(node for node in grouping_nodes if node["capability_id"] == "C002")
            self.assertEqual("not_required", mcs["human_approval"])
            self.assertEqual([], mcs["dependencies"])
            self.assertEqual(3, mcs["parameters"]["min_cluster_size"])
            self.assertEqual(1000, mcs["parameters"]["max_pairs"])
            self.assertEqual(300, mcs["parameters"]["max_core_groups"])
            self.assertEqual(61453, mcs["parameters"]["random_seed"])
            planned["run"]["parallel_limit"] = 64
            self.assertIn(mcs["node_id"], {node["node_id"] for node in STATE.runnable_nodes(planned)})
            a004 = [node for node in analysis_nodes if node["capability_id"] == "A004"]
            self.assertEqual({description_node_by_capability[value] for value in ["D001", "D013"]}, {node["input_bindings"]["description"] for node in a004})
            a005 = [node for node in analysis_nodes if node["capability_id"] == "A005"]
            self.assertEqual(
                {description_node_by_capability["D004"]: "cosine", description_node_by_capability["D007"]: "tanimoto"},
                {node["input_bindings"]["description"]: node["parameters"]["metric"] for node in a005},
            )
            a006 = [node for node in analysis_nodes if node["capability_id"] == "A006"]
            self.assertEqual({description_node_by_capability[value] for value in ["D002", "D013", "D017"]}, {node["input_bindings"]["description"] for node in a006})
            self.assertEqual(
                {description_node_by_capability["D002"]: "tanimoto", description_node_by_capability["D013"]: "manhattan", description_node_by_capability["D017"]: "tanimoto"},
                {node["input_bindings"]["description"]: node["parameters"]["metric"] for node in a006},
            )
            a001 = [node for node in analysis_nodes if node["capability_id"] == "A001"]
            self.assertEqual({node["node_id"] for node in grouping_nodes}, {node["input_bindings"]["grouping"] for node in a001})
            a009 = [node for node in analysis_nodes if node["capability_id"] == "A009"]
            self.assertEqual({node["node_id"] for node in grouping_nodes if node["capability_id"] in {"C002", "C003"}}, {node["input_bindings"]["grouping"] for node in a009})

            output_dirs = [node["output_dir"] for node in nodes]
            self.assertEqual(len(output_dirs), len(set(output_dirs)))
            self.assertTrue(all(":" not in Path(path).name for path in output_dirs))
            self.assertEqual(52, len(nodes))
            self.assertEqual("representative-family-wide-v1", planned["wide_shallow_plan"]["profile"])
            self.assertIn("shape_and_3d_pharmacophore", planned["wide_shallow_plan"]["required_axes"]["description"])

            with redirect_stdout(io.StringIO()):
                STATE.cmd_plan_wide(SimpleNamespace(state=str(state_path)))
            replanned = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(52, len(replanned["execution_graph"]["nodes"]))

    def test_interpretation_exploration_budget_falsification_and_duplicate_guard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            state_path = temporary / "state.json"
            state = self.state()
            state["run"]["input"] = str((MODULE_ROOT / "tests" / "data" / "small_sar.csv").resolve())
            state["interpretations"] = [{"interpretation_id": "R:I001:seed", "source_node_id": "I001:001", "status": "active"}]
            state["evidence_graph"] = {"nodes": [{"evidence_id": "R:A002:A002-001:0001", "source_node_id": "A002:seed", "status": "active"}], "edges": []}
            state["domain_graph"] = {"nodes": [{"group_id": "G_TEST", "source_node_id": "C001:seed", "status": "active"}], "edges": []}
            state_path.write_text(json.dumps(state), encoding="utf-8")
            STATE.cmd_configure_exploration(SimpleNamespace(state=str(state_path), max_iterations=3, max_additional_nodes=4, walltime_minutes=60, seed=61453))

            plan = json.loads((MODULE_ROOT / "tests" / "data" / "exploration_plan.json").read_text(encoding="utf-8"))
            plan_path = temporary / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                STATE.cmd_register_exploration(SimpleNamespace(state=str(state_path), plan=str(plan_path)))
            registered = json.loads(state_path.read_text(encoding="utf-8"))
            node = registered["execution_graph"]["nodes"][0]
            self.assertEqual("interpretation_exploration", node["phase"])
            self.assertEqual("falsify", node["exploration"]["purpose"])
            self.assertEqual(node["analysis_signature"], registered["interpretation_exploration"]["ledger"][0]["analysis_signature"])

            duplicate = json.loads(json.dumps(plan))
            duplicate["iteration"] = 2
            duplicate["requests"][0]["request_id"] = "REQ-002"
            duplicate_path = temporary / "duplicate.json"
            duplicate_path.write_text(json.dumps(duplicate), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Repeated analysis signature"):
                STATE.cmd_register_exploration(SimpleNamespace(state=str(state_path), plan=str(duplicate_path)))

            missing_falsification = json.loads(json.dumps(plan))
            missing_falsification["iteration"] = 2
            missing_falsification["requests"][0]["request_id"] = "REQ-003"
            missing_falsification["requests"][0]["purpose"] = "characterize"
            missing_falsification["requests"][0]["parameters"] = {"scope_mode": "global", "target_group": "unused"}
            missing_path = temporary / "missing-falsification.json"
            missing_path.write_text(json.dumps(missing_falsification), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "requires a falsification request"):
                STATE.cmd_register_exploration(SimpleNamespace(state=str(state_path), plan=str(missing_path)))

            scoped = json.loads(json.dumps(plan))
            scoped["iteration"] = 2
            scoped["requests"][0]["request_id"] = "REQ-SCOPE-001"
            scoped["requests"][0]["parameters"] = {}
            scoped["requests"][0]["scope"] = {
                "scope_id": "MATCHED-A",
                "mode": "within-group",
                "selection_method": "matched_random",
                "target_group_id": "MATCHED_CONTROL",
                "target_compound_ids": ["CMPD_001", "CMPD_003", "CMPD_005"],
                "source_group_ids": ["G_TEST"],
                "selection_notes": "Seeded unit-test control",
            }
            scoped_path = temporary / "scoped.json"
            scoped_path.write_text(json.dumps(scoped), encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                STATE.cmd_register_exploration(SimpleNamespace(state=str(state_path), plan=str(scoped_path)))
            scoped_state = json.loads(state_path.read_text(encoding="utf-8"))
            scoped_node = scoped_state["execution_graph"]["nodes"][1]
            membership_path = Path(scoped_node["parameters"]["membership"])
            self.assertTrue(membership_path.is_file())
            self.assertEqual("within-group", scoped_node["parameters"]["scope_mode"])
            self.assertTrue(scoped_node["parameters"]["target_group"].startswith("G_SCOPE_"))
            self.assertEqual("MATCHED_CONTROL", scoped_node["exploration"]["scope"]["target_group_label"])
            self.assertEqual(3, scoped_node["exploration"]["scope"]["target_count"])
            self.assertEqual(
                scoped_node["exploration"]["scope"]["compound_set_hash"],
                scoped_state["interpretation_exploration"]["ledger"][1]["scope"]["compound_set_hash"],
            )
            registry_path = Path(scoped_state["group_index"]["registry_path"])
            matrix_path = Path(scoped_state["group_index"]["matrix_shards"][0]["path"])
            self.assertTrue(registry_path.is_file())
            self.assertTrue(matrix_path.name.startswith("Cpd_Group_matrix_G000000_099999"))
            with matrix_path.open(encoding="utf-8", newline="") as handle:
                matrix_rows = list(DictReader(handle))
            group_id = scoped_node["parameters"]["target_group"]
            self.assertEqual("True", next(row for row in matrix_rows if row["compound_id"] == "CMPD_001")[group_id])
            self.assertEqual("False", next(row for row in matrix_rows if row["compound_id"] == "CMPD_002")[group_id])

            repeated_scope = json.loads(json.dumps(scoped))
            repeated_scope["iteration"] = 3
            repeated_scope["requests"][0]["request_id"] = "REQ-SCOPE-002"
            repeated_scope_path = temporary / "repeated-scope.json"
            repeated_scope_path.write_text(json.dumps(repeated_scope), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Repeated analysis signature"):
                STATE.cmd_register_exploration(SimpleNamespace(state=str(state_path), plan=str(repeated_scope_path)))

            empty_bounds = json.loads(json.dumps(plan))
            empty_bounds["iteration"] = 3
            empty_bounds["mode"] = "orchestrator-bounded"
            empty_bounds["bounds"] = {"notes": "No scientific boundary"}
            empty_bounds["requests"][0]["request_id"] = "REQ-BOUND-EMPTY"
            empty_bounds_path = temporary / "empty-bounds.json"
            empty_bounds_path.write_text(json.dumps(empty_bounds), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "requires at least one explicit scientific bound"):
                STATE.cmd_register_exploration(SimpleNamespace(state=str(state_path), plan=str(empty_bounds_path)))

            outside_bounds = json.loads(json.dumps(empty_bounds))
            outside_bounds["bounds"] = {"operator_ids": ["A006"]}
            outside_bounds["requests"][0]["request_id"] = "REQ-BOUND-OUTSIDE"
            outside_bounds_path = temporary / "outside-bounds.json"
            outside_bounds_path.write_text(json.dumps(outside_bounds), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "outside operator_ids"):
                STATE.cmd_register_exploration(SimpleNamespace(state=str(state_path), plan=str(outside_bounds_path)))


if __name__ == "__main__":
    unittest.main()
