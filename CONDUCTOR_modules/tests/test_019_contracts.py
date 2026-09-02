from __future__ import annotations

import json
import importlib.util
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / "CONDUCTOR_modules"
SKILLS = ROOT / ".claude" / "skills"


class Version019Contracts(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = json.loads((MODULES / "catalog" / "analysis_profile.json").read_text(encoding="utf-8"))
        self.selection = json.loads((MODULES / "catalog" / "included_skills.json").read_text(encoding="utf-8"))

    def load_batch_runner(self, module_name: str):
        common_path = MODULES / "tools" / "templates" / "batch_skill_common.py"
        common_spec = importlib.util.spec_from_file_location("batch_skill_common", common_path)
        common = importlib.util.module_from_spec(common_spec)
        assert common_spec.loader is not None
        common_spec.loader.exec_module(common)
        import sys
        previous = sys.modules.get("batch_skill_common")
        sys.modules["batch_skill_common"] = common
        try:
            runner_path = MODULES / "tools" / "templates" / "series_batch_runner.py"
            runner_spec = importlib.util.spec_from_file_location(module_name, runner_path)
            runner = importlib.util.module_from_spec(runner_spec)
            assert runner_spec.loader is not None
            runner_spec.loader.exec_module(runner)
        finally:
            if previous is None:
                sys.modules.pop("batch_skill_common", None)
            else:
                sys.modules["batch_skill_common"] = previous
        return runner

    def test_basic_compute_is_all_description_all_vector_clustering(self) -> None:
        basic = self.profile["basic_compute"]
        self.assertEqual(len(basic["description_capabilities"]), 18)
        self.assertEqual(basic["vector_clustering_representations"], basic["description_capabilities"])
        self.assertEqual(basic["vector_clustering_capabilities"], ["C005", "C006", "C007", "C008", "C009", "C010"])
        self.assertEqual(basic["survey_capabilities"], ["A001", "A002"])
        self.assertEqual(basic["series_clustering"], "C012")

    def test_standard_operator_ids_are_unique_and_batched(self) -> None:
        expected = ["A003", "A004", "A005", "A006", "A007", "A008", "A009"]
        self.assertEqual(self.profile["standard_analysis"]["capabilities"], expected)
        capabilities = []
        for name in self.selection["analysis_skills"]:
            capabilities.append(json.loads((SKILLS / name / "capability.json").read_text(encoding="utf-8")))
        self.assertEqual(sorted(item["capability_id"] for item in capabilities), ["A001", "A002", *expected])

    def test_on_demand_is_round_independent(self) -> None:
        capability = json.loads((SKILLS / "cs-conductor-on-demand-analysis" / "capability.json").read_text(encoding="utf-8"))
        self.assertEqual(capability["implementation"]["record_namespace"], "REQ")
        self.assertEqual(capability["implementation"]["round_participation"], "forbidden")
        self.assertEqual(capability["implementation"]["dag_registration"], "forbidden")

    def test_mmp_defaults_are_interpretable(self) -> None:
        capability = json.loads((SKILLS / "cs-analysis-matched-molecular-pairs" / "capability.json").read_text(encoding="utf-8"))
        self.assertEqual(capability["default_parameters"]["cuts"], 1)
        self.assertEqual((capability["default_parameters"]["radius_min"], capability["default_parameters"]["radius_max"]), (0, 2))

    def test_mmp_storage_and_effect_direction_are_role_specific(self) -> None:
        source = (SKILLS / "cs-analysis-matched-molecular-pairs" / "scripts" / "run.py").read_text(encoding="utf-8")
        self.assertIn('persist_database=role == "type-iii"', source)
        self.assertIn('"favorable_delta_toward_target" if role == "type-i" else "favorable_delta_from_target_to_neighbor"', source)
        self.assertIn('[endpoint, compound_id], ascending=[not higher_is_better, True]', source)
        self.assertIn("attachment_topology_signature(reference_mol)!=target_topology", source)
        self.assertNotIn('role="global-build"', source)
        self.assertIn("hashlib.sha256(target_id.encode('utf-8')).hexdigest()[:12]", source)

    def test_audit_directories_do_not_collide_within_one_second(self) -> None:
        controller_path = MODULES / "tools" / "runtime_controller.py"
        specification = importlib.util.spec_from_file_location("runtime_019_audit_path_test", controller_path)
        runtime = importlib.util.module_from_spec(specification)
        assert specification.loader is not None
        specification.loader.exec_module(runtime)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runtime").mkdir()
            (root / "state").mkdir()
            source = root / "input.csv"
            source.write_text("compound_id,SMILES,activity\nC1,CC,1.0\n", encoding="utf-8")
            control = {
                "schema_version": "1.0.0", "conductor_version": "0.1.9",
                "project": "test", "run_id": "RUN019", "input_path": str(source),
                "input_sha256": runtime.sha256(source),
                "columns": {"compound_id": "compound_id", "smiles": "SMILES", "endpoint": "activity"},
                "active_round_id": None, "round_status": "NONE", "revision": 0,
            }
            dag = {"schema_version": "1.0.0", "conductor_version": "0.1.9", "revision": 0, "nodes": []}
            runtime.atomic_json(runtime.control_path(root), control)
            runtime.atomic_json(runtime.dag_path(root), dag)
            with redirect_stdout(io.StringIO()):
                runtime.cmd_audit(SimpleNamespace(run_root=str(root), mode="quick", register=False, lease_token=None))
                runtime.cmd_audit(SimpleNamespace(run_root=str(root), mode="quick", register=False, lease_token=None))
            audit_directories = [path for path in (root / "state").iterdir() if path.is_dir()]
        self.assertEqual(len(audit_directories), 2)

    def test_long_analysis_unit_membership_is_grouped_by_analysis_unit_id(self) -> None:
        common_path = MODULES / "tools" / "templates" / "batch_skill_common.py"
        specification = importlib.util.spec_from_file_location("batch_common_019_test", common_path)
        module = importlib.util.module_from_spec(specification)
        assert specification.loader is not None
        specification.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            membership = Path(temporary) / "analysis_unit_membership.csv"
            membership.write_text(
                "compound_id,analysis_unit_id,membership_value\n"
                "C1,GLOBAL,True\nC2,GLOBAL,True\nC3,GLOBAL,True\n"
                "C1,S000001,True\nC2,S000001,True\nC3,S000002,True\n",
                encoding="utf-8",
            )
            request = {"inputs": [{"role": "analysis_unit_membership", "path": str(membership)}]}
            units = module.analysis_units(request)
        self.assertEqual(units["GLOBAL"], {"C1", "C2", "C3"})
        self.assertEqual(units["S000001"], {"C1", "C2"})
        self.assertEqual(units["S000002"], {"C3"})
        self.assertNotIn("analysis_unit_id", units)

    def test_runtime_plans_exact_basic_contract(self) -> None:
        controller_path = MODULES / "tools" / "runtime_controller.py"
        specification = importlib.util.spec_from_file_location("runtime_019_test", controller_path)
        runtime = importlib.util.module_from_spec(specification)
        assert specification.loader is not None
        specification.loader.exec_module(runtime)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "input.csv"
            source.write_text("compound_id,SMILES,activity\nC1,CC,1.0\nC2,CCC,2.0\n", encoding="utf-8")
            run_root = base / "run"
            with redirect_stdout(io.StringIO()):
                runtime.cmd_init(SimpleNamespace(input=str(source), id_column="compound_id", smiles_column="SMILES", endpoint="activity", higher_is_better=True, endpoint_unit=None, project="test", parallel_limit=2, available_cpu_cores=8, run_id="RUN019", output_dir=str(run_root)))
                runtime.cmd_prepare_round(SimpleNamespace(run_root=str(run_root), walltime_minutes=60, parallel_limit=None, available_cpu_cores=None, min_ff_evaluate=10, leiden_resolution=1.0, objective="contract test", approve_high_cost=True))
            control = runtime.read_json(runtime.control_path(run_root))
            request = runtime.read_json(Path(control["pending_round_request"]))
            key = (run_root / "runtime" / "control_authority.key").read_text(encoding="utf-8").strip()
            with redirect_stdout(io.StringIO()):
                runtime.cmd_authorize_round(SimpleNamespace(run_root=str(run_root), control_key=key, authorization_token=request["authorization_token"]))
                runtime.cmd_resume_round(SimpleNamespace(run_root=str(run_root), control_key=key, owner_id="test", lease_minutes=60))
            control = runtime.read_json(runtime.control_path(run_root))
            with redirect_stdout(io.StringIO()):
                runtime.cmd_plan_basic(SimpleNamespace(run_root=str(run_root), lease_token=control["lease"]["token"]))
            _, dag = runtime.load_state(run_root)
        basic_nodes = [node for node in runtime.nodes(dag) if node["wave"] == "basic"]
        self.assertEqual(len(basic_nodes), 133)
        self.assertEqual(sum(node["capability_id"] in {"A001", "A002", "C012"} for node in basic_nodes), 3)

    def test_cluster_registry_accepts_blank_cluster_id_for_inactive_membership(self) -> None:
        controller_path = MODULES / "tools" / "runtime_controller.py"
        specification = importlib.util.spec_from_file_location("runtime_019_registry_test", controller_path)
        runtime = importlib.util.module_from_spec(specification)
        assert specification.loader is not None
        specification.loader.exec_module(runtime)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runtime").mkdir()
            source = root / "input.csv"
            source.write_text(
                "compound_id,SMILES,activity\n"
                "C1,CC,1\nC2,CCC,2\nC3,CCCC,3\nC4,CCO,4\nC5,CCN,5\nC6,CCF,6\n",
                encoding="utf-8",
            )
            result_dir = root / "source_node"
            result_dir.mkdir()
            membership = result_dir / "cluster_membership.csv"
            membership.write_text(
                "cluster_id,compound_id,membership_value,membership_reason\n"
                "LCL000001,C1,1.0,clustered\n"
                "LCL000001,C2,1.0,clustered\n"
                "LCL000001,C3,1.0,clustered\n"
                "LCL000001,C4,1.0,clustered\n"
                "LCL000001,C5,1.0,clustered\n"
                ",C6,0.0,below_min_cluster_size\n",
                encoding="utf-8",
            )
            dag = {"nodes": [{
                "node_id": "N000001", "capability_id": "C001", "stage": "clustering",
                "round_id": "RND0001", "status": "succeeded", "dependencies": [],
                "parameters": {"min_cluster_size": 5},
                "result": {"result_dir": str(result_dir), "primary_path": str(membership)},
            }]}
            control = {"input_path": str(source), "columns": {"compound_id": "compound_id"}}
            runtime.rebuild_cluster_registry(root, control, dag, "RND0001")
            registry = (root / "runtime" / "cluster_registry.csv").read_text(encoding="utf-8")
            long_membership = (root / "runtime" / "cluster_membership_long.csv").read_text(encoding="utf-8")
        self.assertIn("C1", long_membership)
        self.assertNotIn("C6", long_membership)
        self.assertIn("C000001", registry)

    def test_cluster_registry_rejects_silently_omitted_compounds(self) -> None:
        controller_path = MODULES / "tools" / "runtime_controller.py"
        specification = importlib.util.spec_from_file_location("runtime_019_registry_coverage_test", controller_path)
        runtime = importlib.util.module_from_spec(specification)
        assert specification.loader is not None
        specification.loader.exec_module(runtime)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runtime").mkdir()
            source = root / "input.csv"
            source.write_text(
                "compound_id,SMILES,activity\n"
                "C1,CC,1\nC2,CCC,2\nC3,CCCC,3\nC4,CCO,4\nC5,CCN,5\nC6,CCF,6\n",
                encoding="utf-8",
            )
            result_dir = root / "source_node"
            result_dir.mkdir()
            membership = result_dir / "cluster_membership.csv"
            membership.write_text(
                "cluster_id,compound_id,membership_value,membership_reason\n"
                "LCL000001,C1,1,clustered\nLCL000001,C2,1,clustered\n"
                "LCL000001,C3,1,clustered\nLCL000001,C4,1,clustered\n"
                "LCL000001,C5,1,clustered\n",
                encoding="utf-8",
            )
            dag = {"nodes": [{
                "node_id": "N000001", "capability_id": "C001", "stage": "clustering",
                "round_id": "RND0001", "status": "succeeded", "dependencies": [],
                "parameters": {"min_cluster_size": 5},
                "result": {"result_dir": str(result_dir), "primary_path": str(membership)},
            }]}
            control = {"input_path": str(source), "columns": {"compound_id": "compound_id"}}
            with self.assertRaisesRegex(ValueError, "omits input compound IDs"):
                runtime.rebuild_cluster_registry(root, control, dag, "RND0001")

    def test_add_node_persists_capability_defaults(self) -> None:
        controller_path = MODULES / "tools" / "runtime_controller.py"
        specification = importlib.util.spec_from_file_location("runtime_019_node_defaults_test", controller_path)
        runtime = importlib.util.module_from_spec(specification)
        assert specification.loader is not None
        specification.loader.exec_module(runtime)
        control = {"round_status": "ACTIVE", "active_round_id": "RND0001", "next_node_number": 1}
        dag = {"nodes": []}
        node, added = runtime.add_node(control, dag, "C005", [], "basic", {"min_cluster_size": 7})
        defaults = runtime.capabilities()["C005"]["default_parameters"]
        self.assertTrue(added)
        self.assertEqual(node["parameters"]["min_cluster_size"], 7)
        for key, value in defaults.items():
            if key != "min_cluster_size":
                self.assertEqual(node["parameters"][key], value)

    def test_series_gate_counts_accepted_series_not_fallback_units(self) -> None:
        controller_path = MODULES / "tools" / "runtime_controller.py"
        specification = importlib.util.spec_from_file_location("runtime_019_series_gate_test", controller_path)
        runtime = importlib.util.module_from_spec(specification)
        assert specification.loader is not None
        specification.loader.exec_module(runtime)
        with tempfile.TemporaryDirectory() as temporary:
            result_dir = Path(temporary) / "c012"
            result_dir.mkdir()
            summary_path = result_dir / "series_summary.json"
            summary_path.write_text(json.dumps({
                "accepted_series_count": 2,
                "analysis_unit_count": 30,
            }), encoding="utf-8")
            control = {"active_round_id": "RND0001"}
            dag = {"nodes": [{
                "node_id": "N000001", "capability_id": "C012",
                "round_id": "RND0001", "status": "succeeded",
                "result": {"result_dir": str(result_dir)},
            }]}
            gate = runtime.series_gate(Path(temporary), control, dag)
            self.assertIsNone(gate)

            summary_path.write_text(json.dumps({
                "accepted_series_count": 25,
                "analysis_unit_count": 30,
            }), encoding="utf-8")
            gate = runtime.series_gate(Path(temporary), control, dag)
            self.assertIsNotNone(gate)
            self.assertEqual(gate["accepted_series_count"], 25)
            self.assertEqual(gate["analysis_unit_count"], 30)

    def test_execution_packet_is_bound_to_its_originating_lease(self) -> None:
        controller_path = MODULES / "tools" / "runtime_controller.py"
        specification = importlib.util.spec_from_file_location("runtime_019_packet_lease_test", controller_path)
        runtime = importlib.util.module_from_spec(specification)
        assert specification.loader is not None
        specification.loader.exec_module(runtime)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packets = root / "runtime" / "packets"
            packets.mkdir(parents=True)
            control = {
                "revision": 0, "conductor_version": "0.1.9", "run_id": "RUN019",
                "round_status": "ACTIVE", "active_round_id": "RND0001",
                "round_deadline": "2099-01-01T00:00:00+00:00",
                "lease": {"token": "current", "expires_at": "2099-01-01T00:00:00+00:00"},
            }
            dag = {"revision": 0, "nodes": []}
            runtime.atomic_json(runtime.control_path(root), control)
            runtime.atomic_json(runtime.dag_path(root), dag)
            packet = packets / "PKTSTALE.json"
            runtime.atomic_json(packet, {
                "schema_version": "1.0.0", "packet_id": "PKTSTALE",
                "run_root": str(root), "round_id": "RND0001",
                "lease_fingerprint": runtime.hashlib.sha256(b"old").hexdigest(),
                "node_ids": [], "parallel_limit": 1, "status": "prepared",
            })
            with self.assertRaisesRegex(RuntimeError, "originating Runtime lease"):
                runtime.cmd_execute_packet(SimpleNamespace(run_root=str(root), packet=str(packet)))

    def test_standard_report_waits_for_but_does_not_load_mmp_pairs(self) -> None:
        controller_path = MODULES / "tools" / "runtime_controller.py"
        specification = importlib.util.spec_from_file_location("runtime_019_report_inputs_test", controller_path)
        runtime = importlib.util.module_from_spec(specification)
        assert specification.loader is not None
        specification.loader.exec_module(runtime)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runtime").mkdir()
            dataset = root / "input.csv"
            dataset.write_text("compound_id,SMILES,activity\nC1,CC,1\n", encoding="utf-8")
            (root / "runtime" / "series_registry.csv").write_text(
                "series_id,accepted\n", encoding="utf-8"
            )
            dependency_specs = [
                ("N000001", "A001", "profile.csv"),
                ("N000002", "A002", "enrichment.csv"),
                ("N000003", "C012", "series.csv"),
                ("N000004", "A003", "contrast.csv"),
                ("N000005", "A008", "mmp_target_pairs.csv"),
            ]
            dependency_nodes = []
            for node_id, capability_id, name in dependency_specs:
                path = root / name
                path.write_text("value\n", encoding="utf-8")
                dependency_nodes.append({
                    "node_id": node_id, "capability_id": capability_id,
                    "stage": "analysis" if capability_id != "C012" else "clustering",
                    "round_id": "RND0001", "status": "succeeded",
                    "result": {"primary_path": str(path), "primary_sha256": runtime.sha256(path)},
                })
            report_node = {
                "node_id": "N000006", "capability_id": "A009",
                "skill_name": "cs-analysis-series-report", "round_id": "RND0001",
                "dependencies": [item["node_id"] for item in dependency_nodes],
                "parameters": {},
            }
            dag = {"nodes": [*dependency_nodes, report_node]}
            control = {
                "input_path": str(dataset), "input_sha256": runtime.sha256(dataset),
                "columns": {"compound_id": "compound_id", "smiles": "SMILES", "endpoint": "activity"},
                "higher_is_better": True, "available_cpu_cores": 8, "parallel_limit": 2,
                "project": "test", "run_id": "RUN019",
            }
            request = runtime.execution_request(root, control, dag, report_node, "ATT0001", root / "scratch")
        source_capabilities = {
            item.get("source_capability_id") for item in request["inputs"] if item.get("role") == "source"
        }
        self.assertIn("A003", source_capabilities)
        self.assertNotIn("A008", source_capabilities)

    def test_batch_capabilities_declare_the_dataset_their_code_reads(self) -> None:
        c012 = json.loads(
            (SKILLS / "cs-compute-clustering-meta-overlap" / "capability.json").read_text(encoding="utf-8")
        )
        a009 = json.loads(
            (SKILLS / "cs-analysis-series-report" / "capability.json").read_text(encoding="utf-8")
        )
        for capability in (c012, a009):
            self.assertIn("dataset", capability["input_contract"])
            self.assertIn("dataset", capability["conductor_request"]["required_input_roles"])

        # A009 can render an explicitly partial standard report after optional
        # A003-A007 failures are waived; their generic source role must not be
        # an unconditional Runtime contract.
        self.assertNotIn("source", a009["conductor_request"]["required_input_roles"])
        self.assertIn("optional_standard_operator_results", a009["input_contract"])

    def test_init_rejects_duplicate_compound_ids_before_planning(self) -> None:
        controller_path = MODULES / "tools" / "runtime_controller.py"
        specification = importlib.util.spec_from_file_location("runtime_019_input_test", controller_path)
        runtime = importlib.util.module_from_spec(specification)
        assert specification.loader is not None
        specification.loader.exec_module(runtime)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "input.csv"
            source.write_text(
                "compound_id,SMILES,activity\nC1,CC,1.0\nC1,CCC,2.0\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "Duplicate compound ID"):
                runtime.cmd_init(SimpleNamespace(
                    input=str(source), id_column="compound_id", smiles_column="SMILES",
                    endpoint="activity", higher_is_better=True, endpoint_unit=None,
                    project="test", parallel_limit=2, available_cpu_cores=8,
                    run_id="RUN019", output_dir=str(base / "run"),
                ))

    def test_empty_cluster_profile_keeps_header_only_negative_result(self) -> None:
        runner = self.load_batch_runner("series_runner_019_empty_test")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "input.csv"
            source.write_text("compound_id,SMILES,activity\nC1,CC,1.0\nC2,CCC,2.0\n", encoding="utf-8")
            membership = base / "membership.csv"
            membership.write_text("compound_id\nC1\nC2\n", encoding="utf-8")
            registry = base / "registry.csv"
            registry.write_text("cluster_id,source_node_id\n", encoding="utf-8")
            request = {
                "inputs": [
                    {"role": "dataset", "path": str(source)},
                    {"role": "clustering", "path": str(membership)},
                    {"role": "cluster_registry", "path": str(registry)},
                ],
                "columns": {"compound_id": "compound_id", "smiles": "SMILES", "endpoint": "activity"},
                "endpoint": {"higher_is_better": True},
                "parameters": {"min_ff_evaluate": 10, "favorable_fraction_threshold": 0.5},
            }
            result, summary = runner.cluster_statistics(request)
        self.assertEqual(len(result), 0)
        self.assertIn("cluster_id", result.columns)
        self.assertIn("selected_for_series", result.columns)
        self.assertEqual(summary["selected_cluster_count"], 0)

    def test_c012_rejects_inconsistent_a001_a002_cluster_selection(self) -> None:
        runner = self.load_batch_runner("series_runner_019_consistency_test")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            dataset = base / "input.csv"
            dataset.write_text(
                "compound_id,SMILES,activity\nC1,CC,1.0\nC2,CCC,2.0\n",
                encoding="utf-8",
            )
            membership = base / "membership.csv"
            membership.write_text("compound_id,C000001\nC1,True\nC2,True\n", encoding="utf-8")
            registry = base / "registry.csv"
            registry.write_text("cluster_id,sample_count\nC000001,2\n", encoding="utf-8")
            profile = base / "profile.csv"
            profile.write_text(
                "cluster_id,sample_count,favorable_fraction,selected_for_series\nC000001,2,0.5,False\n",
                encoding="utf-8",
            )
            enrichment = base / "enrichment.csv"
            enrichment.write_text(
                "cluster_id,sample_count,favorable_fraction,selected_for_series\nC000001,2,0.5,True\n",
                encoding="utf-8",
            )
            request = {
                "inputs": [
                    {"role": "dataset", "path": str(dataset)},
                    {"role": "cluster_membership_matrix", "path": str(membership)},
                    {"role": "cluster_registry", "path": str(registry)},
                    {"role": "cluster_profile", "path": str(profile)},
                    {"role": "cluster_enrichment", "path": str(enrichment)},
                ],
                "columns": {"compound_id": "compound_id", "smiles": "SMILES", "endpoint": "activity"},
                "endpoint": {"higher_is_better": True},
                "parameters": {"min_ff_evaluate": 5, "favorable_fraction_threshold": 0.5},
            }
            with self.assertRaisesRegex(ValueError, "A001 profile and A002 enrichment disagree"):
                runner.run_c012(request, base / "output", {"capability_id": "C012", "stage": "clustering"})

    def test_c012_global_compound_count_is_not_endpoint_valid_count(self) -> None:
        runner = self.load_batch_runner("series_runner_019_global_count_test")
        runner.finish = lambda *args, **kwargs: None
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            output = base / "output"
            output.mkdir()
            dataset = base / "input.csv"
            dataset.write_text(
                "compound_id,SMILES,activity\n"
                "C1,CC,1\nC2,CCC,2\nC3,CCCC,3\nC4,CCO,4\nC5,CCN,\n",
                encoding="utf-8",
            )
            membership = base / "membership.csv"
            membership.write_text(
                "compound_id,C000001\nC1,True\nC2,True\nC3,True\nC4,True\nC5,True\n",
                encoding="utf-8",
            )
            registry = base / "registry.csv"
            registry.write_text(
                "cluster_id,source_cluster_id,source_node_id,sample_count\n"
                "C000001,LCL000001,N000001,5\n",
                encoding="utf-8",
            )
            profile = base / "profile.csv"
            enrichment = base / "enrichment.csv"
            content = (
                "cluster_id,sample_count,favorable_fraction,selected_for_series\n"
                "C000001,4,0.75,True\n"
            )
            profile.write_text(content, encoding="utf-8")
            enrichment.write_text(content, encoding="utf-8")
            request = {
                "inputs": [
                    {"role": "dataset", "path": str(dataset)},
                    {"role": "cluster_membership_matrix", "path": str(membership)},
                    {"role": "cluster_registry", "path": str(registry)},
                    {"role": "cluster_profile", "path": str(profile)},
                    {"role": "cluster_enrichment", "path": str(enrichment)},
                ],
                "columns": {"compound_id": "compound_id", "smiles": "SMILES", "endpoint": "activity"},
                "endpoint": {"higher_is_better": True},
                "parameters": {"min_ff_evaluate": 4, "favorable_fraction_threshold": 0.5},
            }
            runner.run_c012(request, output, {"capability_id": "C012", "stage": "clustering"})
            units = runner.pd.read_csv(output / "analysis_unit_registry.csv").set_index("analysis_unit_id")
        self.assertEqual(int(units.loc["GLOBAL", "compound_count"]), 5)
        self.assertEqual(int(units.loc["GLOBAL", "endpoint_valid_count"]), 4)

    def test_runtime_creates_and_passes_canonical_description_result(self) -> None:
        controller_path = MODULES / "tools" / "runtime_controller.py"
        specification = importlib.util.spec_from_file_location("runtime_019_description_contract_test", controller_path)
        runtime = importlib.util.module_from_spec(specification)
        assert specification.loader is not None
        specification.loader.exec_module(runtime)
        with tempfile.TemporaryDirectory() as temporary:
            result_dir = Path(temporary)
            primary = result_dir / "D001_rdkit_2d.csv"
            primary.write_text("compound_id,desc_a\nC1,1.0\n", encoding="utf-8")
            (result_dir / "description_manifest.json").write_text(json.dumps({
                "schema_version": "2.0.0", "conductor_version": "0.1.9",
                "artifact_stage": "description", "capability_id": "D001",
                "node_id": "N000001", "attempt_id": "ATT0001",
                "skill_name": "cs-compute-description-rdkit-2d",
                "row_count": 1, "feature_count": 1, "feature_columns": ["desc_a"],
                "value_semantics": "dense_continuous", "natural_metric": "euclidean",
                "output": primary.name, "warnings": [], "errors": [],
                "created_at": "2026-01-01T00:00:00+00:00",
            }), encoding="utf-8")
            node = {
                "node_id": "N000001", "attempt_id": "ATT0001",
                "capability_id": "D001", "skill_name": "cs-compute-description-rdkit-2d",
                "attempts": [{"attempt_id": "ATT0001"}],
            }
            sidecar = runtime.create_description_result(result_dir, node, runtime.capabilities()["D001"], primary)
            node["result"] = {
                "description_result_path": str(sidecar),
                "description_result_sha256": runtime.sha256(sidecar),
            }
            bound = runtime.artifact("description", primary, node)
            contract = json.loads(sidecar.read_text(encoding="utf-8"))
            sidecar_hash = runtime.sha256(sidecar)
        self.assertEqual(contract["document_type"], "description_result")
        self.assertEqual(contract["payload"], primary.name)
        self.assertEqual(bound["result_path"], str(sidecar.resolve()))
        self.assertEqual(bound["result_sha256"], sidecar_hash)

    def test_vector_adapter_uses_normalized_description_compound_id(self) -> None:
        adapter_path = MODULES / "tools" / "templates" / "conductor_request_adapter.py"
        specification = importlib.util.spec_from_file_location("adapter_019_id_test", adapter_path)
        adapter = importlib.util.module_from_spec(specification)
        assert specification.loader is not None
        specification.loader.exec_module(adapter)
        capability = json.loads((SKILLS / "cs-compute-clustering-vector-butina" / "capability.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            payload = base / "description.csv"
            payload.write_text("compound_id,f1\n001,1\n", encoding="utf-8")
            result = base / "description_result.json"
            result.write_text("{}\n", encoding="utf-8")
            request_path = base / "request.json"
            request_path.write_text(json.dumps({
                "schema_version": "1.0.0",
                "identity": {
                    "project": "test", "run_id": "RUN019", "round_id": "RND0001",
                    "node_id": "N000002", "attempt_id": "ATT0001", "capability_id": "C005",
                    "skill_name": capability["skill_name"],
                },
                "inputs": [{
                    "role": "description", "path": str(payload), "sha256": adapter._sha256(payload),
                    "result_path": str(result), "result_sha256": adapter._sha256(result),
                    "source_capability_id": "D001",
                }],
                "columns": {"compound_id": "CHEMBL_ID", "smiles": "canonical_smiles", "endpoint": "IC50"},
                "endpoint": {"higher_is_better": False}, "subject": {}, "parameters": {}, "resources": {},
                "output": {"directory": str(base / "output")},
            }), encoding="utf-8")
            arguments = adapter.request_to_cli(request_path, capability)
        position = arguments.index("--id-column")
        self.assertEqual(arguments[position + 1], "compound_id")
        self.assertNotIn("CHEMBL_ID", arguments)

    def test_declining_high_cost_does_not_cancel_cluster_surveys(self) -> None:
        controller_path = MODULES / "tools" / "runtime_controller.py"
        specification = importlib.util.spec_from_file_location("runtime_019_high_cost_test", controller_path)
        runtime = importlib.util.module_from_spec(specification)
        assert specification.loader is not None
        specification.loader.exec_module(runtime)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "input.csv"
            source.write_text("compound_id,SMILES,activity\nC1,CC,1.0\nC2,CCC,2.0\n", encoding="utf-8")
            run_root = base / "run"
            with redirect_stdout(io.StringIO()):
                runtime.cmd_init(SimpleNamespace(input=str(source), id_column="compound_id", smiles_column="SMILES", endpoint="activity", higher_is_better=True, endpoint_unit=None, project="test", parallel_limit=2, available_cpu_cores=8, run_id="RUN019", output_dir=str(run_root)))
                runtime.cmd_prepare_round(SimpleNamespace(run_root=str(run_root), walltime_minutes=60, parallel_limit=None, available_cpu_cores=None, min_ff_evaluate=10, leiden_resolution=1.0, objective="contract test", approve_high_cost=False))
            control = runtime.read_json(runtime.control_path(run_root))
            request = runtime.read_json(Path(control["pending_round_request"]))
            key = (run_root / "runtime" / "control_authority.key").read_text(encoding="utf-8").strip()
            with redirect_stdout(io.StringIO()):
                runtime.cmd_authorize_round(SimpleNamespace(run_root=str(run_root), control_key=key, authorization_token=request["authorization_token"]))
                runtime.cmd_resume_round(SimpleNamespace(run_root=str(run_root), control_key=key, owner_id="test", lease_minutes=60))
            control = runtime.read_json(runtime.control_path(run_root))
            with redirect_stdout(io.StringIO()):
                runtime.cmd_plan_basic(SimpleNamespace(run_root=str(run_root), lease_token=control["lease"]["token"]))
                runtime.cmd_approve_high_cost(SimpleNamespace(run_root=str(run_root), control_key=key, approve=False, rationale="test decline"))
            _, dag = runtime.load_state(run_root)
        table = {node["capability_id"]: node for node in runtime.nodes(dag) if node["capability_id"] in {"A001", "A002", "C012"}}
        self.assertEqual({key: value["status"] for key, value in table.items()}, {"A001": "pending", "A002": "pending", "C012": "pending"})
        self.assertTrue(all(node["status"] == "cancelled" for node in runtime.nodes(dag) if node["capability_id"] in runtime.HIGH_COST))

    def test_preparation_failure_becomes_failed_node_with_diagnostic(self) -> None:
        controller_path = MODULES / "tools" / "runtime_controller.py"
        specification = importlib.util.spec_from_file_location("runtime_019_attempt_failure_test", controller_path)
        runtime = importlib.util.module_from_spec(specification)
        assert specification.loader is not None
        specification.loader.exec_module(runtime)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runtime").mkdir(parents=True)
            for stage in ("description", "clustering", "analysis", "interpretation"):
                (root / stage).mkdir()
            control = {
                "schema_version": "1.0.0", "run_id": "RUN019", "project": "test",
                "active_round_id": "RND0001", "round_status": "ACTIVE", "revision": 0,
                "available_cpu_cores": 8, "parallel_limit": 2,
            }
            dag = {"schema_version": "1.0.0", "revision": 0, "nodes": [{
                "node_id": "N000001", "capability_id": "D001", "skill_name": "cs-compute-description-rdkit-2d",
                "stage": "description", "wave": "basic", "round_id": "RND0001", "dependencies": [],
                "parameters": {}, "status": "pending", "attempts": [], "result": None, "error": None,
                "waived": False, "created_at": runtime.now(), "updated_at": runtime.now(),
            }]}
            runtime.atomic_json(runtime.control_path(root), control)
            runtime.atomic_json(runtime.dag_path(root), dag)
            with mock.patch.object(runtime, "execution_request", side_effect=ValueError("contract construction failed")):
                result = runtime.run_node(root, "N000001")
            _, updated = runtime.load_state(root)
        node = updated["nodes"][0]
        self.assertEqual(result["status"], "failed")
        self.assertEqual(node["status"], "failed")
        self.assertIn("contract construction failed", node["error"]["message"])
        self.assertEqual(node["attempts"][0]["status"], "failed")

    def test_init_rejects_compound_id_whitespace_and_path_traversal(self) -> None:
        controller_path = MODULES / "tools" / "runtime_controller.py"
        specification = importlib.util.spec_from_file_location("runtime_019_safe_input_test", controller_path)
        runtime = importlib.util.module_from_spec(specification)
        assert specification.loader is not None
        specification.loader.exec_module(runtime)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "input.csv"
            source.write_text("compound_id,SMILES,activity\n C1,CC,1.0\n", encoding="utf-8")
            arguments = dict(input=str(source), id_column="compound_id", smiles_column="SMILES", endpoint="activity", higher_is_better=True, endpoint_unit=None, project="test", parallel_limit=1, available_cpu_cores=1, run_id="RUN019", output_dir=str(base / "run"))
            with self.assertRaisesRegex(ValueError, "leading or trailing whitespace"):
                runtime.cmd_init(SimpleNamespace(**arguments))
            source.write_text("compound_id,SMILES,activity\nC1,CC,1.0\n", encoding="utf-8")
            arguments.update(project="../escape")
            with self.assertRaisesRegex(ValueError, "one path component"):
                runtime.cmd_init(SimpleNamespace(**arguments))

    def test_init_rejects_parallel_limit_above_cpu_budget(self) -> None:
        controller_path = MODULES / "tools" / "runtime_controller.py"
        specification = importlib.util.spec_from_file_location("runtime_019_cpu_limit_test", controller_path)
        runtime = importlib.util.module_from_spec(specification)
        assert specification.loader is not None
        specification.loader.exec_module(runtime)
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "input.csv"
            source.write_text("compound_id,SMILES,activity\nC1,CC,1.0\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must not exceed"):
                runtime.cmd_init(SimpleNamespace(
                    input=str(source), id_column="compound_id", smiles_column="SMILES",
                    endpoint="activity", higher_is_better=True, endpoint_unit=None,
                    project="test", parallel_limit=9, available_cpu_cores=8,
                    run_id="RUN019", output_dir=str(Path(temporary) / "run"),
                ))

    def test_resume_does_not_reclassify_a_live_local_runtime(self) -> None:
        controller_path = MODULES / "tools" / "runtime_controller.py"
        specification = importlib.util.spec_from_file_location("runtime_019_live_process_test", controller_path)
        runtime = importlib.util.module_from_spec(specification)
        assert specification.loader is not None
        specification.loader.exec_module(runtime)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runtime").mkdir()
            key = "control-key"
            (root / "runtime" / "control_authority.key").write_text(key + "\n", encoding="utf-8")
            control = {
                "schema_version": "1.0.0", "conductor_version": "0.1.9", "run_id": "RUN019",
                "active_round_id": "RND0001", "round_status": "ACTIVE", "revision": 0,
                "lease": {"token": "expired", "expires_at": "2000-01-01T00:00:00+00:00"},
            }
            dag = {"schema_version": "1.0.0", "conductor_version": "0.1.9", "revision": 0, "nodes": [{
                "node_id": "N000001", "round_id": "RND0001", "status": "running",
                "attempts": [{"attempt_id": "ATT0001", "status": "running", "runtime_pid": 12345, "runtime_host": runtime.socket.gethostname()}],
            }]}
            runtime.atomic_json(runtime.control_path(root), control)
            runtime.atomic_json(runtime.dag_path(root), dag)
            with mock.patch.object(runtime, "process_alive", return_value=True):
                with self.assertRaisesRegex(RuntimeError, "still executing"):
                    runtime.cmd_resume_round(SimpleNamespace(
                        run_root=str(root), control_key=key, owner_id="replacement",
                        lease_minutes=360, confirm_interrupted_running=False,
                    ))
            _, unchanged = runtime.load_state(root)
        self.assertEqual(unchanged["nodes"][0]["status"], "running")

    def test_load_state_uses_complete_pending_transaction_pair(self) -> None:
        controller_path = MODULES / "tools" / "runtime_controller.py"
        specification = importlib.util.spec_from_file_location("runtime_019_transaction_test", controller_path)
        runtime = importlib.util.module_from_spec(specification)
        assert specification.loader is not None
        specification.loader.exec_module(runtime)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runtime").mkdir()
            runtime.atomic_json(runtime.control_path(root), {"revision": 1, "marker": "old-control"})
            runtime.atomic_json(runtime.dag_path(root), {"revision": 1, "marker": "old-dag"})
            runtime.atomic_json(runtime.state_transaction_path(root), {
                "schema_version": "1.0.0",
                "control": {"revision": 2, "marker": "new-control"},
                "dag": {"revision": 2, "marker": "new-dag"},
            })
            control, dag = runtime.load_state(root)
        self.assertEqual((control["revision"], dag["revision"]), (2, 2))
        self.assertEqual((control["marker"], dag["marker"]), ("new-control", "new-dag"))

    def test_batch_tables_preserve_leading_zero_compound_ids(self) -> None:
        common_path = MODULES / "tools" / "templates" / "batch_skill_common.py"
        specification = importlib.util.spec_from_file_location("batch_common_019_string_id_test", common_path)
        common = importlib.util.module_from_spec(specification)
        assert specification.loader is not None
        specification.loader.exec_module(common)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "input.csv"
            source.write_text("compound_id,SMILES,activity\n001,CC,1.0\n002,CCC,2.0\n", encoding="utf-8")
            membership = base / "membership.csv"
            membership.write_text("compound_id,C000001\n001,True\n002,False\n", encoding="utf-8")
            request = {
                "inputs": [{"role": "dataset", "path": str(source)}],
                "columns": {"compound_id": "compound_id", "smiles": "SMILES", "endpoint": "activity"},
            }
            frame, cid, _, _ = common.dataset(request)
            all_ids, groups = common.membership_sets(membership)
        self.assertEqual(frame[cid].tolist(), ["001", "002"])
        self.assertEqual(all_ids, ["001", "002"])
        self.assertEqual(groups["C000001"], {"001"})


if __name__ == "__main__":
    unittest.main()
