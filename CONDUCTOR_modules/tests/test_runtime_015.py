from __future__ import annotations

import contextlib
import importlib.util
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
ADAPTER_PATH = ROOT / "CONDUCTOR_modules" / "tools" / "templates" / "conductor_request_adapter.py"
SPEC = importlib.util.spec_from_file_location("request_adapter_015", ADAPTER_PATH)
assert SPEC and SPEC.loader
ADAPTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADAPTER)
RUNTIME_SPEC = importlib.util.spec_from_file_location(
    "runtime_controller_015",
    ROOT / "CONDUCTOR_modules" / "tools" / "runtime_controller.py",
)
assert RUNTIME_SPEC and RUNTIME_SPEC.loader
RUNTIME = importlib.util.module_from_spec(RUNTIME_SPEC)
RUNTIME_SPEC.loader.exec_module(RUNTIME)
HAS_JSONSCHEMA = importlib.util.find_spec("jsonschema") is not None


class ExecutionRequest015(unittest.TestCase):
    def request(self, root: Path, capability: dict, inputs: list[dict], parameters: dict | None = None) -> Path:
        value = {
            "schema_version": "1.0.0",
            "identity": {"project": "p", "run_id": "r", "round_id": "RND0001", "node_id": "N000001", "attempt_id": "ATT0001", "capability_id": capability["capability_id"], "skill_name": capability["skill_name"]},
            "inputs": inputs,
            "columns": {"compound_id": "compound_id", "smiles": "smiles", "endpoint": "pIC50"},
            "endpoint": {"higher_is_better": True},
            "subject": {"mode": "global"},
            "parameters": parameters or {},
            "resources": {"available_cpu_cores": 8, "node_cpu_cores": 1, "native_thread_limit": 1, "skill_options": {}},
            "output": {"directory": str(root / "output"), "overwrite": False},
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        path = root / "execution_request.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def capability(self, skill: str) -> dict:
        return json.loads((ROOT / ".claude" / "skills" / skill / "capability.json").read_text(encoding="utf-8"))

    @staticmethod
    def artifact(path: Path, role: str, *, capability: str | None = None, node: str | None = None, result: Path | None = None) -> dict:
        path.write_text("compound_id,smiles,pIC50\nC1,CCO,5\n", encoding="utf-8")
        item = {"role": role, "artifact_type": role, "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        if capability:
            item["source_capability_id"] = capability
        if node:
            item["source_node_id"] = node
        if result:
            result.write_text("{}", encoding="utf-8")
            item.update({"result_path": str(result), "result_sha256": hashlib.sha256(result.read_bytes()).hexdigest()})
        return item

    def test_description_request_maps_to_existing_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capability = self.capability("cs-compute-description-rdkit-2d")
            request = self.request(root, capability, [self.artifact(root / "input.csv", "dataset")])
            argv = ADAPTER.request_to_cli(request, capability)
            self.assertIn("--conductor", argv)
            self.assertEqual("smiles", argv[argv.index("--smiles-column") + 1])
            self.assertEqual(str((root / "input.csv").resolve()), argv[argv.index("--input") + 1])

    def test_vector_clustering_uses_description_role_and_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capability = self.capability("cs-compute-clustering-vector-butina")
            source = self.artifact(root / "description.csv", "description", capability="D002", node="N000002", result=root / "result.json")
            request = self.request(root, capability, [source], {"min_cluster_size": 5, "metric": "auto"})
            argv = ADAPTER.request_to_cli(request, capability)
            self.assertEqual("D002", argv[argv.index("--input-representation") + 1])
            self.assertIn("--description-result", argv)

    def test_categorical_clustering_uses_dataset_without_structure_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capability = self.capability("cs-compute-clustering-categorical")
            request = self.request(
                root,
                capability,
                [self.artifact(root / "input.csv", "dataset")],
                {"columns": "series", "min_cluster_size": 5},
            )
            argv = ADAPTER.request_to_cli(request, capability)
            self.assertEqual(str((root / "input.csv").resolve()), argv[argv.index("--input") + 1])
            self.assertEqual("series", argv[argv.index("--columns") + 1])
            self.assertNotIn("--smiles-column", argv)

    def test_false_store_true_parameter_is_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capability = self.capability("cs-compute-description-morgan")
            request = self.request(root, capability, [self.artifact(root / "input.csv", "dataset")], {"use_features": False, "include_chirality": False})
            argv = ADAPTER.request_to_cli(request, capability)
            self.assertNotIn("--no-use-features", argv)
            self.assertNotIn("--no-include-chirality", argv)

    def test_mmp_global_request_uses_new_standard_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capability = self.capability("cs-analysis-matched-molecular-pairs")
            request = self.request(root, capability, [self.artifact(root / "input.csv", "dataset")], capability["default_parameters"] | {"role": "global-build"})
            value = json.loads(request.read_text(encoding="utf-8"))
            value["resources"]["node_cpu_cores"] = 8
            request.write_text(json.dumps(value), encoding="utf-8")
            argv = ADAPTER.request_to_cli(request, capability)
            self.assertEqual("global-build", argv[0])
            self.assertEqual("2", argv[argv.index("--num-cuts") + 1])
            self.assertEqual("2", argv[argv.index("--max-radius") + 1])
            self.assertEqual("10", argv[argv.index("--max-variable-heavy-atoms") + 1])
            self.assertNotIn("--no-extended-search", argv)

    def test_request_identity_must_match_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capability = self.capability("cs-compute-description-rdkit-2d")
            request = self.request(root, capability, [self.artifact(root / "input.csv", "dataset")])
            value = json.loads(request.read_text(encoding="utf-8"))
            value["identity"]["capability_id"] = "D002"
            request.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "capability_id"):
                ADAPTER.request_to_cli(request, capability)


class RuntimeControl015(unittest.TestCase):
    def command(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "CONDUCTOR_modules" / "tools" / "runtime_controller.py"), *arguments],
            cwd=ROOT,
            text=True,
            capture_output=True,
            env=os.environ.copy(),
        )
        self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
        return completed

    def test_parser_exposes_one_exploration_action_without_legacy_tokens(self) -> None:
        parser = RUNTIME.build_parser()
        subparsers = next(
            action for action in parser._actions
            if action.__class__.__name__ == "_SubParsersAction"
        )
        commands = subparsers.choices
        self.assertIn("plan-exploration", commands)
        self.assertNotIn("plan-initial-global", commands)
        self.assertNotIn("plan-initial-local", commands)
        self.assertNotIn("execute-batch", commands)
        for command in ("plan-basic", "plan-exploration", "prepare-execution-packet"):
            destinations = {action.dest for action in commands[command]._actions}
            self.assertIn("lease_token", destinations)
            self.assertNotIn("action_token", destinations)
            self.assertNotIn("executor_token", destinations)
        executor_destinations = {action.dest for action in commands["execute-packet"]._actions}
        self.assertEqual({"help", "run_root", "packet"}, executor_destinations)

    def test_round_analysis_limit_is_one_unbatched_set_of_one_hundred(self) -> None:
        self.assertEqual((100, 100), RUNTIME._analysis_planning_limits())

    def test_global_only_operator_is_rejected_for_local_scope(self) -> None:
        capabilities = RUNTIME.catalog()
        self.assertFalse(RUNTIME._supports_standard_local_scope(capabilities["A012"]))
        self.assertTrue(RUNTIME._supports_standard_local_scope(capabilities["A002"]))
        self.assertTrue(RUNTIME._analysis_scope_supported(capabilities["A003"], {"mode": "global"}, {}))
        self.assertTrue(RUNTIME._analysis_scope_supported(capabilities["A003"], {"mode": "projection"}, {"role": "cluster-overlay"}))
        self.assertTrue(RUNTIME._analysis_scope_supported(capabilities["A005"], {"mode": "multi_scope"}, {"role": "cluster-survey"}))
        self.assertTrue(RUNTIME._analysis_scope_supported(capabilities["A014"], {"mode": "multi_scope"}, {"role": "local-screen"}))
        control = {"active_round_id": "RND0001"}
        snapshot = {"nodes": [], "counters": {"node": 0}, "rounds": {"RND0001": {"reused_node_ids": []}}}
        with self.assertRaisesRegex(ValueError, "A012 does not support Runtime scope=single_cluster"):
            RUNTIME._add_node(
                snapshot, control, "A012", ["N000001"], "exploration",
                {"mode": "single_cluster", "cluster_ids": ["C000001"]},
                {"target_cluster": "C000001"},
            )

    @unittest.skipUnless(HAS_JSONSCHEMA, "jsonschema is installed by the Runtime Pixi environment")
    def test_projection_overlay_canonical_subject_preserves_global_population(self) -> None:
        description = {"node_id": "N000001", "kind": "description", "capability_id": "D001", "input_nodes": []}
        clustering = {"node_id": "N000002", "kind": "clustering", "capability_id": "C005", "input_nodes": ["N000001"]}
        projection = {"node_id": "N000003", "kind": "analysis", "capability_id": "A003", "input_nodes": ["N000001"], "parameters": {"role": "projection-fit"}, "scope": {"mode": "global"}}
        overlay = {"node_id": "N000004", "kind": "analysis", "capability_id": "A003", "input_nodes": ["N000003", "N000002"], "parameters": {"role": "cluster-overlay", "target_cluster": "C000001"}, "scope": {"mode": "single_cluster", "cluster_ids": ["C000001"]}}
        snapshot = {"nodes": [description, clustering, projection, overlay]}
        control = {"run": {"input": "unused.csv", "endpoint": "pIC50"}}
        all_ids = [f"CPD{i:03d}" for i in range(5)]
        with mock.patch.object(RUNTIME, "_read_input_ids", return_value=(all_ids, set(all_ids))), mock.patch.object(
            RUNTIME, "_membership_ids", return_value=set(all_ids[:2])
        ), mock.patch.object(RUNTIME, "_description_valid_ids", return_value=set(all_ids)), mock.patch.object(
            RUNTIME, "_primary_payload", return_value=Path("membership.csv")
        ):
            subject = RUNTIME._analysis_subject(Path("."), control, snapshot, overlay, sample_count=5)
        self.assertEqual("projection", subject["scope_mode"])
        self.assertEqual(5, subject["population_count"])
        self.assertEqual(5, subject["analyzed_count"])
        self.assertEqual(["C000001"], subject["cluster_ids"])

    def test_canonical_description_eligibility_uses_declared_features_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / "features.csv").write_text(
                "compound_id,f1,numeric_metadata,mol_parse_ok\nC001,1,0,true\nC002,,1,true\nC003,3,0,false\n",
                encoding="utf-8",
            )
            RUNTIME.write_json(output / "result.json", {
                "document_type": "description_result", "schema_version": "1.0.0",
                "node_id": "N000001", "capability_id": "D001", "payload": "features.csv",
                "row_count": 3, "feature_count": 1, "value_semantics": "dense_continuous",
                "natural_metric": "euclidean", "feature_columns": ["f1"], "quality_flags": [],
                "created_at": RUNTIME.utc_now(),
            })
            node = {"node_id": "N000001", "kind": "description", "capability_id": "D001", "output_ref": str(output)}
            self.assertEqual({"C001"}, RUNTIME._description_valid_ids(node))

    def test_exploration_materializes_one_global_first_set_capped_at_one_hundred(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            control = {
                "active_round_id": "RND0001",
                "run": {"run_root": str(root)},
            }
            snapshot = {
                "nodes": [],
                "counters": {"node": 0},
                "rounds": {"RND0001": {"reused_node_ids": []}},
                "plans": {"RND0001": {}},
            }
            global_specs = [
                {"capability_id": "A001", "input_nodes": [], "scope": {"mode": "global"}, "parameters": {"sample": index}}
                for index in range(120)
            ]
            local_specs = [
                {"capability_id": "A001", "input_nodes": [], "scope": {"mode": "single_cluster", "cluster_ids": [f"C{index:06d}"]}, "parameters": {"sample": index}}
                for index in range(120)
            ]
            with mock.patch.object(RUNTIME, "_exploration_global_specs", return_value=global_specs), mock.patch.object(
                RUNTIME, "_exploration_local_specs", return_value=local_specs
            ):
                planned = RUNTIME._plan_exploration(root, control, snapshot)
            self.assertEqual(100, len(planned))
            self.assertEqual(100, len(snapshot["nodes"]))
            scope_counts = {
                mode: sum(node["scope"]["mode"] == mode for node in snapshot["nodes"])
                for mode in ("global", "single_cluster")
            }
            self.assertEqual({"global": 67, "single_cluster": 33}, scope_counts)
            self.assertEqual(100, snapshot["plans"]["RND0001"]["exploration_nodes_planned"])

    def test_default_lease_execution_timeout_and_cpu_budget(self) -> None:
        parser = RUNTIME.build_parser()
        resumed = parser.parse_args([
            "resume-round", "--run-root", "run", "--control-key", "key", "--owner-id", "owner",
        ])
        packet = parser.parse_args([
            "prepare-execution-packet", "--run-root", "run", "--lease-token", "lease",
        ])
        initialized = parser.parse_args([
            "init", "--input", "input.csv", "--endpoint", "pIC50", "--higher-is-better",
            "--project", "test", "--parallel-limit", "3",
        ])
        self.assertEqual(360, RUNTIME.DEFAULT_LEASE_MINUTES)
        self.assertEqual(360, RUNTIME.DEFAULT_EXECUTION_TIMEOUT_MINUTES)
        self.assertEqual(360, resumed.lease_minutes)
        self.assertEqual(360, packet.timeout_minutes)
        self.assertEqual(8, initialized.available_cpu_cores)

    @unittest.skipUnless(HAS_JSONSCHEMA, "jsonschema is installed by the Runtime Pixi environment")
    def test_compact_response_has_no_rotating_action_token(self) -> None:
        control = {
            "run": {"run_id": "RUN0001"},
            "active_round_id": "RND0001",
            "round_state": "ACTIVE",
            "required_action": {"code": "PLAN_EXPLORATION", "reason": "test"},
            "revision": 7,
            "lease": {"expires_at": "2026-01-01T00:00:00+00:00"},
        }
        response = RUNTIME._compact_response(control)
        self.assertEqual("0.1.6", response["protocol_version"])
        self.assertNotIn("action_token", response)
        self.assertNotIn("executor_token", response)

    def test_attempt_scratch_accepts_only_the_prepared_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scratch = Path(temporary)
            (scratch / "execution_request.json").write_text("{}", encoding="utf-8")
            RUNTIME._validate_attempt_scratch(scratch)
            (scratch / "ad_hoc.py").write_text("pass", encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "Unexpected pre-existing"):
                RUNTIME._validate_attempt_scratch(scratch)

    def test_execution_request_rejects_changed_input_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset = root / "input.csv"
            dataset.write_text("compound_id,smiles,pIC50\nC1,CCO,5\n", encoding="utf-8")
            control = {"run": {"input": str(dataset)}}
            request = {"inputs": [{
                "role": "dataset", "artifact_type": "endpoint_csv", "path": str(dataset),
                "sha256": RUNTIME.file_hash(dataset),
            }]}
            RUNTIME._validate_execution_request_artifacts(root, control, request)
            dataset.write_text("compound_id,smiles,pIC50\nC1,CCN,6\n", encoding="utf-8")
            with self.assertRaisesRegex(PermissionError, "hash mismatch"):
                RUNTIME._validate_execution_request_artifacts(root, control, request)

    def test_result_card_links_are_canonical_run_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = root / "analysis" / "N000001" / "report.html"
            report.parent.mkdir(parents=True)
            report.write_text("ok", encoding="utf-8")
            card = {"artifact_links": {"report": "analysis/N000001/report.html", "detail": None}}
            RUNTIME._validate_result_card_links(root, card)
            card["artifact_links"]["report"] = "analysis/N000001/analysis/N000001/report.html"
            with self.assertRaises(FileNotFoundError):
                RUNTIME._validate_result_card_links(root, card)

    def test_failed_analysis_signature_remains_eligible_without_counting_as_history(self) -> None:
        spec = {"capability_id": "A001", "input_nodes": [], "scope": {"mode": "global"}, "parameters": {}}
        signature = RUNTIME._signature(spec["capability_id"], spec["input_nodes"], spec["scope"], spec["parameters"])
        failed = {
            "node_id": "N000001", "kind": "analysis", "capability_id": "A001", "input_nodes": [],
            "scope": {"mode": "global"}, "parameters": {}, "signature": signature, "status": "failed",
            "result_quality": {"eligible_for_downstream": False},
        }
        candidates = RUNTIME._history_balanced_specs({"nodes": [failed]}, [spec], 17)
        self.assertEqual(1, len(candidates))

    def test_deterministic_contract_failures_are_not_auto_recoverable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / "attempt.log"
            log.write_text("error: unrecognized arguments: --wrong\n", encoding="utf-8")
            classification, recoverable = RUNTIME._classify_execution_failure(log, {"returncode": 2}, RuntimeError("failed"))
            self.assertEqual("argument_contract_mismatch", classification)
            self.assertFalse(recoverable)

    def test_process_output_is_streamed_to_attempt_log(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log = root / "attempt.log"
            process_record = root / "process.json"
            outcome = RUNTIME._run_one(
                [sys.executable, "-c", "print('x' * 200000)"],
                log, process_record, 30, "0" * 64,
            )
            self.assertEqual(0, outcome["returncode"])
            self.assertGreater(log.stat().st_size, 200000)
            process = json.loads(process_record.read_text(encoding="utf-8"))
            self.assertEqual(process["pid"], process["process_group_id"])

    def test_global_deliverable_cannot_be_satisfied_by_local_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            round_dir = root / "rounds" / "RND0001"
            round_dir.mkdir(parents=True)
            contract = {"required_deliverables": [{
                "deliverable_id": "DELIV_GLOBAL", "type": "capability_coverage", "description": "global",
                "parameters": {"capability_ids": ["A001"], "scope_modes": ["global"]},
                "human_acceptance_required": False,
            }]}
            (round_dir / "round_contract.json").write_text(json.dumps(contract), encoding="utf-8")
            control = {"active_round_id": "RND0001"}
            node = {
                "node_id": "N000001", "capability_id": "A001", "status": "succeeded",
                "scope": {"mode": "single_cluster"}, "assigned_round": "RND0001",
                "created_in_round": "RND0001", "result_quality": {"eligible_for_downstream": True},
            }
            status = RUNTIME._deliverable_status(root, control, {"nodes": [node], "rounds": {"RND0001": {}}, "plans": {}})
            self.assertFalse(status[0]["satisfied"])
            node["scope"] = {"mode": "global"}
            status = RUNTIME._deliverable_status(root, control, {"nodes": [node], "rounds": {"RND0001": {}}, "plans": {}})
            self.assertTrue(status[0]["satisfied"])

    def test_basic_deliverable_requires_every_planned_signature_node(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            round_dir = root / "rounds" / "RND0001"
            round_dir.mkdir(parents=True)
            contract = {"required_deliverables": [{
                "deliverable_id": "DELIV_BASIC", "type": "planned_node_coverage", "description": "basic",
                "parameters": {"plan_key": "basic_compute"}, "human_acceptance_required": False,
            }]}
            (round_dir / "round_contract.json").write_text(json.dumps(contract), encoding="utf-8")
            control = {"active_round_id": "RND0001"}
            nodes = [
                {"node_id": "N000001", "status": "succeeded", "assigned_round": "RND0001", "created_in_round": "RND0001", "result_quality": {"eligible_for_downstream": True}},
                {"node_id": "N000002", "status": "failed", "assigned_round": "RND0001", "created_in_round": "RND0001", "result_quality": {"eligible_for_downstream": False}},
            ]
            snapshot = {"nodes": nodes, "rounds": {"RND0001": {}}, "plans": {"RND0001": {"basic_compute_node_ids": ["N000001", "N000002"]}}}
            status = RUNTIME._deliverable_status(root, control, snapshot)
            self.assertFalse(status[0]["satisfied"])
            nodes[1].update({"status": "succeeded", "result_quality": {"eligible_for_downstream": True}})
            status = RUNTIME._deliverable_status(root, control, snapshot)
            self.assertTrue(status[0]["satisfied"])

    @unittest.skipUnless(HAS_JSONSCHEMA, "jsonschema is installed by the Runtime Pixi environment")
    def test_skill_command_is_fixed_and_python_path_independent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset = root / "input.csv"
            dataset.write_text("compound_id,smiles,pIC50\nC1,CCO,5.0\n", encoding="utf-8")
            capability = RUNTIME.catalog()["D001"]
            control = {"run": {
                "project": "test", "run_id": "run-015", "run_root": str(root),
                "input": str(dataset), "id_column": "compound_id", "smiles_column": "smiles",
                "endpoint": "pIC50", "higher_is_better": True,
                "available_cpu_cores": 8, "parallel_limit": 2,
            }}
            node = {
                "node_id": "N000001", "capability_id": "D001", "skill_name": capability["skill_name"],
                "assigned_round": "RND0001", "kind": "description", "input_nodes": [],
                "parameters": {}, "scope": {"mode": "not_applicable"},
            }
            scratch = root / "runtime" / "scratch" / "RND0001" / "N000001" / "ATT0001"
            with mock.patch.object(RUNTIME.sys, "executable", "/orchestrator/python"):
                prepared = RUNTIME._skill_command(root, control, {"nodes": [node]}, node, "ATT0001", scratch)
                prepared_resolved = RUNTIME._resolve_skill_command(prepared)
            with mock.patch.object(RUNTIME.sys, "executable", "/runtime/python"):
                executed = RUNTIME._skill_command(root, control, {"nodes": [node]}, node, "ATT0001", scratch)
                executed_resolved = RUNTIME._resolve_skill_command(executed)
            self.assertEqual(prepared, executed)
            self.assertEqual(4, len(prepared))
            self.assertEqual(RUNTIME.RUNTIME_PYTHON_TOKEN, prepared[0])
            self.assertEqual("--conductor-request", prepared[2])
            self.assertEqual(prepared_resolved[1:], executed_resolved[1:])
            self.assertNotEqual(prepared_resolved[0], executed_resolved[0])

    @unittest.skipUnless(HAS_JSONSCHEMA, "jsonschema is installed by the Runtime Pixi environment")
    def test_signed_packet_becomes_stale_after_revision_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            dataset = base / "input.csv"
            dataset.write_text("compound_id,smiles,pIC50\nC1,CCO,5.0\nC2,CCN,5.2\n", encoding="utf-8")
            run_root = base / "run"
            self.command(
                "init", "--input", str(dataset), "--endpoint", "pIC50", "--higher-is-better",
                "--project", "test", "--parallel-limit", "2", "--run-id", "run-015",
                "--output-dir", str(run_root),
            )
            prepared = json.loads(self.command(
                "prepare-round", "--run-root", str(run_root), "--objective", "packet test",
                "--walltime-minutes", "60", "--parallel-limit", "2", "--approve-high-cost",
            ).stdout)
            key = (run_root / "runtime" / "control_authority.key").read_text(encoding="utf-8").strip()
            self.command(
                "authorize-round", "--run-root", str(run_root), "--control-key", key,
                "--request-file", prepared["request_file"], "--authorization-token", prepared["authorization_token"],
            )
            resumed = json.loads(self.command(
                "resume-round", "--run-root", str(run_root), "--control-key", key,
                "--owner-id", "test-main", "--process-id", str(os.getpid()),
            ).stdout)
            lease = resumed["lease_token"]
            self.command("plan-basic", "--run-root", str(run_root), "--lease-token", lease)
            packet_response = json.loads(self.command(
                "prepare-execution-packet", "--run-root", str(run_root), "--lease-token", lease,
                "--timeout-minutes", "5",
            ).stdout)
            packet_path = Path(packet_response["packet_path"])
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
            self.assertNotIn("executor_token", packet)
            self.assertNotIn("action_token", packet)
            self.assertTrue(all(contract["command_argv"][2] == "--conductor-request" for contract in packet["execution_contracts"]))
            current_control = json.loads((run_root / "conductor_control.json").read_text(encoding="utf-8"))
            RUNTIME._validate_execution_packet(run_root, current_control, packet_path)
            self.command("heartbeat", "--run-root", str(run_root), "--lease-token", lease)
            changed_control = json.loads((run_root / "conductor_control.json").read_text(encoding="utf-8"))
            with self.assertRaisesRegex(PermissionError, "stale"):
                RUNTIME._validate_execution_packet(run_root, changed_control, packet_path)

    def test_common_launcher_installs_then_runs_locked_environment(self) -> None:
        launcher = (ROOT / "CONDUCTOR_modules" / "tools" / "templates" / "launch.py").read_text(encoding="utf-8")
        self.assertIn("--conductor-request", launcher)
        self.assertIn('install.append("--locked")', launcher)
        self.assertIn('"run", "--manifest-path", str(manifest)', launcher)
        self.assertIn('.bootstrap.lock', launcher)
        self.assertIn('.environment-ready', launcher)
        self.assertIn('owner.json', launcher)
        self.assertIn('environment_fingerprint', launcher)
        self.assertIn('manifest.read_bytes()', launcher)


class RuntimeWorkerOwnership015(unittest.TestCase):
    def test_atomic_replace_retries_a_transient_windows_scanner_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "worker_status.json"
            target.write_text("old", encoding="utf-8")
            real_replace = os.replace
            calls = 0

            def transient_replace(source: Path, destination: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise PermissionError(13, "transient scanner lock", str(destination))
                real_replace(source, destination)

            with mock.patch.object(RUNTIME.os, "replace", side_effect=transient_replace), mock.patch.object(RUNTIME.time, "sleep"):
                RUNTIME.atomic_bytes(target, b"new")

            self.assertEqual("new", target.read_text(encoding="utf-8"))
            self.assertEqual(2, calls)
            self.assertEqual([], list(root.glob(".worker_status.json.*.tmp")))

    def test_successful_retry_replaces_failed_attempt_quality(self) -> None:
        node = {
            "kind": "description",
            "result_quality": {
                "validation_passed": False,
                "eligible_for_downstream": False,
                "quality_flags": ["technical_failure"],
            },
        }
        quality = RUNTIME._successful_node_quality(node)
        self.assertTrue(quality["validation_passed"])
        self.assertTrue(quality["eligible_for_downstream"])
        self.assertNotIn("technical_failure", quality["quality_flags"])

    def test_human_authority_can_retry_failed_node_before_other_runnable_work(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runtime").mkdir()
            (root / "conductor_control.json").write_text("{}", encoding="utf-8")
            (root / "runtime" / "authority.json").write_text(
                json.dumps({"control_authority_key_hash": RUNTIME.value_hash("human-key")}),
                encoding="utf-8",
            )
            control = {
                "round_state": "ACTIVE", "active_round_id": "RND0001",
                "required_action": {"code": "EXECUTE_RUNNABLE_BATCH", "node_ids": ["N000002"]},
                "lease": {"owner_id": "main", "token_hash": RUNTIME.value_hash("lease"), "expires_at": "2999-01-01T00:00:00+00:00"},
            }
            failed = {
                "node_id": "N000001", "status": "failed", "finished_at": "earlier",
                "assigned_round": "RND0001", "attempts": [{"attempt_id": "ATT0001"}],
            }
            snapshot = {"nodes": [failed, {"node_id": "N000002", "status": "pending"}]}
            args = RUNTIME.argparse.Namespace(
                run_root=str(root), lease_token="lease", control_key="human-key",
                node_id="N000001", reason="human-approved technical repair",
            )
            with mock.patch.object(RUNTIME, "writer_lock", return_value=contextlib.nullcontext()), mock.patch.object(
                RUNTIME, "_recover_transaction"
            ), mock.patch.object(RUNTIME, "_read_state", return_value=(control, snapshot)), mock.patch.object(
                RUNTIME, "_commit"
            ) as commit, mock.patch.object(RUNTIME, "_print_compact"):
                returned = RUNTIME.cmd_retry_node(args)
            self.assertEqual(0, returned)
            self.assertEqual("pending", failed["status"])
            self.assertIsNone(failed["finished_at"])
            self.assertTrue(commit.call_args.args[4]["human_override"])

    def test_wait_reconstructs_terminal_status_after_commit_status_race(self) -> None:
        packet = {
            "packet_id": "PKT20260822T000000000000Z_1234abcd",
            "run_id": "run", "round_id": "RND0001", "node_ids": ["N000001"],
            "execution_contracts": [{"node_id": "N000001", "attempt_id": "ATT0001"}],
        }
        status = {
            "status": "running", "worker_pid": 987654321, "launcher_pid": None,
            "packet_id": packet["packet_id"], "run_id": "run", "round_id": "RND0001", "node_ids": ["N000001"],
        }
        control = {"revision": 4}
        snapshot = {"nodes": [{
            "node_id": "N000001", "status": "succeeded", "current_attempt_id": None,
            "attempts": [{"attempt_id": "ATT0001", "packet_id": packet["packet_id"], "status": "succeeded"}],
        }]}
        with mock.patch.object(RUNTIME, "_read_packet_status", return_value=dict(status)), mock.patch.object(
            RUNTIME, "_read_state", return_value=(control, snapshot)
        ), mock.patch.object(RUNTIME, "_validate_execution_packet_authentic", return_value=packet), mock.patch.object(
            RUNTIME, "pid_alive", return_value=False
        ), mock.patch.object(RUNTIME, "_write_packet_status") as write_status:
            returned_control, terminal = RUNTIME._wait_for_packet(Path("run"), Path("packet.json"), poll_seconds=0.01)
        self.assertIs(returned_control, control)
        self.assertEqual("terminal", terminal["status"])
        self.assertEqual(1, terminal["succeeded_count"])
        self.assertEqual(0, terminal["failed_count"])
        write_status.assert_called_once()

    def test_live_worker_packet_is_not_spawned_twice(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runtime").mkdir()
            packet_path = root / "runtime" / "scratch" / "packets" / "PKT" / "execution_packet.json"
            packet_path.parent.mkdir(parents=True)
            packet = {"packet_id": "PKT1", "run_id": "run", "round_id": "RND0001", "node_ids": ["N000001"]}
            status = {**packet, "status": "running", "worker_pid": os.getpid(), "launcher_pid": None}
            with mock.patch.object(RUNTIME, "_read_packet_status", return_value=status), mock.patch.object(
                RUNTIME, "_validate_execution_packet_authentic", return_value=packet
            ), mock.patch.object(RUNTIME.subprocess, "Popen"
            ) as popen:
                returned = RUNTIME._spawn_runtime_worker(root, packet_path)
            self.assertIs(returned, status)
            popen.assert_not_called()

    def test_running_action_separates_wait_from_reconcile(self) -> None:
        running = [{
            "node_id": "N000001", "status": "running", "current_attempt_id": "ATT0001",
            "attempts": [{"attempt_id": "ATT0001", "packet_id": "PKT1", "scratch": "missing"}],
        }]
        live_status = {"status": "running", "worker_pid": os.getpid(), "launcher_pid": None}
        with mock.patch.object(RUNTIME, "_read_packet_status", return_value=live_status):
            self.assertEqual("WAIT_RUNNING", RUNTIME._running_action(Path("run"), {"nodes": running}, running)["code"])
        with mock.patch.object(RUNTIME, "_read_packet_status", return_value={"status": "running", "worker_pid": 987654321, "launcher_pid": None}), mock.patch.object(
            RUNTIME, "pid_alive", return_value=False
        ):
            self.assertEqual("RECONCILE_RUNNING", RUNTIME._running_action(Path("run"), {"nodes": running}, running)["code"])


if __name__ == "__main__":
    unittest.main()
