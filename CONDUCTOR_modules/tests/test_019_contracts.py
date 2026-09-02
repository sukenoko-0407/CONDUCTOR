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

    def load_mmp_runner(self, module_name: str):
        import sys

        common_path = MODULES / "tools" / "templates" / "batch_skill_common.py"
        common_spec = importlib.util.spec_from_file_location(
            "batch_skill_common", common_path
        )
        common = importlib.util.module_from_spec(common_spec)
        assert common_spec.loader is not None
        common_spec.loader.exec_module(common)
        scripts = (
            SKILLS / "cs-analysis-matched-molecular-pairs" / "scripts"
        )
        previous = sys.modules.get("batch_skill_common")
        sys.modules["batch_skill_common"] = common
        sys.path.insert(0, str(scripts))
        try:
            runner_path = scripts / "run.py"
            runner_spec = importlib.util.spec_from_file_location(
                module_name, runner_path
            )
            runner = importlib.util.module_from_spec(runner_spec)
            assert runner_spec.loader is not None
            runner_spec.loader.exec_module(runner)
        finally:
            sys.path.remove(str(scripts))
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
        self.assertEqual(capability["default_parameters"]["top_k"], 1)
        self.assertEqual(
            self.profile["standard_analysis"]["mmp_type_i_top_k"], 1
        )
        self.assertEqual((capability["default_parameters"]["radius_min"], capability["default_parameters"]["radius_max"]), (0, 2))

    def test_mmp_type_i_targets_and_report_tables_follow_compact_contract(self) -> None:
        runner = self.load_mmp_runner("mmp_runner_019_compact_report_test")
        data = runner.pd.DataFrame({
            "compound_id": ["C1", "C2", "C3", "C4"],
            "activity": [1.0, 4.0, 2.0, 3.0],
        })
        targets = runner.select_type_i_targets(
            data, "compound_id", "activity", True,
            {
                "GLOBAL": {"C1", "C2", "C3", "C4"},
                "S000001": {"C1", "C2"},
                "CLU_C000001": {"C3", "C4"},
            },
        )
        self.assertEqual(
            {(row["analysis_unit_id"], row["target_compound_id"])
             for row in targets},
            {("S000001", "C2"), ("CLU_C000001", "C4")},
        )
        self.assertTrue(all(row["target_rank"] == "1" for row in targets))
        self.assertNotIn(
            "GLOBAL", {row["analysis_unit_id"] for row in targets}
        )

        pair = runner.pd.DataFrame([{
            "mmp_id": "MMP000001",
            "target_compound_id": "C2",
            "target_endpoint": 4.0,
            "neighbor_compound_id": "C1",
            "neighbor_endpoint": 1.0,
            "exact_core_smiles": "c1ccccc1[*:1]",
            "variable_neighbor": "[*:1]Cl",
            "variable_target": "[*:1]N",
            "favorable_delta_report": 3.0,
            "transform_pair_support": 99,
        }])
        basic = runner.compact_mmp_table(pair, "basic")
        detail = runner.compact_mmp_table(pair, "detail")
        self.assertIn("Target compound ID", basic)
        self.assertIn("Neighbor Endpoint", basic)
        self.assertIn("Favorable Δ (Neighbor → Target)", basic)
        self.assertIn("Core SMILES", detail)
        self.assertIn("Before fragment (Neighbor)", detail)
        self.assertNotIn("transform_pair_support", basic + detail)

        template = (
            SKILLS / "cs-analysis-matched-molecular-pairs" / "templates"
            / "mmp_target_report_template.html"
        ).read_text(encoding="utf-8")
        section_positions = [
            template.index(f'data-report-section="{section}"')
            for section in (
                "structures", "basic-information", "mmp-details",
                "visual-transformations", "full-data",
            )
        ]
        self.assertEqual(section_positions, sorted(section_positions))
        self.assertIn("Target full SMILES", template)

    def test_mmp_report_keeps_largest_core_and_orients_target_as_to(self) -> None:
        runner = self.load_mmp_runner("mmp_runner_019_minimal_transform_test")
        frame = runner.pd.DataFrame([
            {
                "mmp_id": "MMP_SMALL", "target_compound_id": "T1",
                "neighbor_compound_id": "N1", "target_endpoint": 8.0,
                "neighbor_endpoint": 3.0, "target_smiles": "CCCCN",
                "neighbor_smiles": "CCCCCl",
                "compound_id_from": "T1", "compound_id_to": "N1",
                "favorable_delta": -5.0,
                "exact_core_smiles": "[*:1]CC",
                "variable_neighbor": "[*:1]Cl",
                "variable_target": "[*:1]N",
                "favorable_delta_toward_target": 5.0,
            },
            {
                "mmp_id": "MMP_LARGE", "target_compound_id": "T1",
                "neighbor_compound_id": "N1", "target_endpoint": 8.0,
                "neighbor_endpoint": 3.0, "target_smiles": "CCCCN",
                "neighbor_smiles": "CCCCCl",
                "compound_id_from": "T1", "compound_id_to": "N1",
                "favorable_delta": -5.0,
                "exact_core_smiles": "[*:1]CCCC",
                "variable_neighbor": "[*:1]Cl",
                "variable_target": "[*:1]N",
                "favorable_delta_toward_target": 5.0,
            },
        ])
        selected = runner.select_minimal_transform_rows(frame)
        self.assertEqual(selected["mmp_id"].tolist(), ["MMP_LARGE"])

        oriented = runner.orient_report_rows_target_to(selected)
        row = oriented.iloc[0]
        self.assertEqual(row["compound_id_from"], "N1")
        self.assertEqual(row["compound_id_to"], "T1")
        self.assertEqual(row["endpoint_from"], 3.0)
        self.assertEqual(row["endpoint_to"], 8.0)
        self.assertEqual(row["variable_from"], "[*:1]Cl")
        self.assertEqual(row["variable_to"], "[*:1]N")
        self.assertEqual(row["favorable_delta"], 5.0)
        self.assertEqual(row["effect_direction"], "neighbor_to_target")
        with tempfile.TemporaryDirectory() as temporary:
            gallery, artifacts = runner.render_transformation_gallery(
                oriented, Path(temporary), "target"
            )
            self.assertEqual(len(artifacts), 1)
            self.assertTrue(artifacts[0].is_file())
            self.assertIn("Neighbor → Target", gallery)
            self.assertIn("MMP_LARGE", gallery)

    def test_mmp_storage_and_effect_direction_are_role_specific(self) -> None:
        source = (SKILLS / "cs-analysis-matched-molecular-pairs" / "scripts" / "run.py").read_text(encoding="utf-8")
        self.assertIn('persist_database=role == "type-iii"', source)
        self.assertIn('"favorable_delta_toward_target" if role == "type-i" else "favorable_delta_from_target_to_neighbor"', source)
        self.assertIn("select_type_i_targets(", source)
        self.assertIn("attachment_topology_signature(reference_mol)!=target_topology", source)
        self.assertNotIn('role="global-build"', source)
        self.assertIn("hashlib.sha256(target_id.encode('utf-8')).hexdigest()[:12]", source)
        self.assertNotIn("frame_html(part,1000)", source)
        self.assertIn('"basic_information_table": compact_mmp_table(', source)
        self.assertIn('"mmp_detail_table": compact_mmp_table(', source)

    def test_mmp_type_i_html_uses_collapsed_oriented_rows_only(self) -> None:
        runner = self.load_mmp_runner("mmp_runner_019_html_smoke_test")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "output"
            output.mkdir()
            dataset = root / "dataset.csv"
            dataset.write_text(
                "compound_id,SMILES,activity\n"
                "N1,CCCCCl,3\nT1,CCCCN,8\n",
                encoding="utf-8",
            )
            membership = root / "membership.csv"
            membership.write_text(
                "compound_id,analysis_unit_id,membership_value\n"
                "N1,S000001,True\nT1,S000001,True\n",
                encoding="utf-8",
            )
            details = runner.pd.DataFrame([
                {
                    "mmp_id": mmp_id,
                    "compound_id_from": "T1", "compound_id_to": "N1",
                    "smiles_from": "CCCCN", "smiles_to": "CCCCCl",
                    "endpoint_from": 8.0, "endpoint_to": 3.0,
                    "favorable_delta": -5.0,
                    "variable_from": "[*:1]N", "variable_to": "[*:1]Cl",
                    "transform_id": f"TRF_{mmp_id}",
                    "transform_smirks": "[*:1]N>>[*:1]Cl",
                    "core_id": f"CORE_{mmp_id}",
                    "exact_core_smiles": core,
                }
                for mmp_id, core in (
                    ("MMP_SMALL", "[*:1]CC"),
                    ("MMP_LARGE", "[*:1]CCCC"),
                )
            ])
            request = {
                "identity": {"node_id": "N000001"},
                "inputs": [
                    {"role": "dataset", "path": str(dataset)},
                    {
                        "role": "analysis_unit_membership",
                        "path": str(membership),
                    },
                ],
                "columns": {
                    "compound_id": "compound_id", "smiles": "SMILES",
                    "endpoint": "activity",
                },
                "endpoint": {"higher_is_better": True},
                "parameters": {"role": "type-i", "top_k": 1},
                "resources": {"node_cpu_cores": 1},
            }
            with (
                mock.patch.object(
                    runner, "parse_request",
                    return_value=(request, output, runner.CAPABILITY),
                ),
                mock.patch.object(
                    runner, "global_build",
                    return_value={"details": details, "warnings": []},
                ),
                mock.patch.object(runner, "finish_request"),
            ):
                self.assertEqual(runner.run_execution_request(), 0)

            raw = runner.pd.read_csv(output / "mmp_target_pairs.csv")
            target_report = next(output.glob("mmp_target_*.html"))
            target_html = target_report.read_text(encoding="utf-8")
            self.assertEqual(len(raw), 2)
            self.assertIn("MMP_LARGE", target_html)
            self.assertNotIn("MMP_SMALL", target_html)
            self.assertIn("Target full SMILES", target_html)
            self.assertIn("CCCCN", target_html)
            self.assertNotIn(">CCCCCl<", target_html)
            self.assertIn("Neighbor → Target", target_html)
            self.assertIn('data-report-section="visual-transformations"', target_html)
            self.assertEqual(
                len(list(output.glob("mmp_transform_*.svg"))), 1
            )

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

    def test_numeric_features_excludes_boolean_quality_columns(self) -> None:
        common_path = MODULES / "tools" / "templates" / "batch_skill_common.py"
        specification = importlib.util.spec_from_file_location("batch_common_019_bool_test", common_path)
        module = importlib.util.module_from_spec(specification)
        assert specification.loader is not None
        specification.loader.exec_module(module)
        frame = module.pd.DataFrame({
            "compound_id": ["C1", "C2", "C3", "C4"],
            "mol_parse_ok": module.pd.Series([True, True, False, True], dtype="bool"),
            "nullable_flag": module.pd.Series([True, False, module.pd.NA, True], dtype="boolean"),
            "descriptor": [1.0, 2.0, module.np.inf, 4.0],
            "numeric_text": ["1", "2", "invalid", "4"],
        })

        features, columns = module.numeric_features(frame, ["compound_id"])

        self.assertEqual(columns, ["descriptor", "numeric_text"])
        self.assertNotIn("mol_parse_ok", features)
        self.assertNotIn("nullable_flag", features)
        self.assertTrue(module.np.isnan(features.loc[2, "descriptor"]))
        self.assertTrue(module.np.isnan(features.loc[2, "numeric_text"]))
        self.assertTrue(all(module.pd.api.types.is_float_dtype(dtype) for dtype in features.dtypes))

    def test_a009_fixed_templates_and_compact_tables_are_enforced(self) -> None:
        runner = self.load_batch_runner("batch_runner_019_report_template_test")
        template_dir = MODULES / "tools" / "templates"
        standard = (template_dir / "standard_summary_template.html").read_text(
            encoding="utf-8"
        )
        detail = (template_dir / "series_detail_template.html").read_text(
            encoding="utf-8"
        )
        required_standard_sections = {
            "at-a-glance", "report-scope", "endpoint-overview", "selected-clusters",
            "series-formation", "operator-results", "execution-metadata",
            "projections", "detail-reports", "full-tables-and-limitations",
        }
        for section in required_standard_sections:
            self.assertIn(f'data-report-section="{section}"', standard)
        self.assertLess(
            standard.index('data-report-section="at-a-glance"'),
            standard.index('data-report-section="endpoint-overview"'),
        )
        for section in {
            "unit-definition", "projection", "a003", "a005", "a006", "a007",
            "full-tables-and-limitations",
        }:
            self.assertIn(f'data-report-section="{section}"', detail)

        frame = runner.pd.DataFrame([{
            "cluster_id": "C000001",
            "description_id": "D001",
            "clustering_id": "C005",
            "sample_count": 12,
            "favorable_count": 8,
            "favorable_fraction": 2 / 3,
            "odds_ratio": 4.5,
            "fisher_pvalue": .001,
            "q_value_bh": .01,
            "series_id": "S000001",
            "parameters_json": '{"very": "wide and intentionally hidden"}',
        }])
        rendered = runner.compact_table(frame, "selected_clusters")
        self.assertIn("table-wrap", rendered)
        self.assertIn("Cluster ID", rendered)
        self.assertNotIn("parameters_json", rendered)
        self.assertNotIn("intentionally hidden", rendered)

        a003_frame = runner.pd.DataFrame([{
            "feature": "MolWt", "sample_count": 12, "pearson_r": .81,
            "spearman_r": .78, "max_abs_correlation": .81,
            "correlation_q_bh": .01, "strict_hit": True,
            "median_shift_global_iqr": 1.2, "shift_q_bh": .02,
            "global_pearson_r": .15,
        }])
        a003_rendered = runner.compact_table(a003_frame, "A003_detail")
        self.assertIn("Max |r|", a003_rendered)
        self.assertIn("Correlation BH q", a003_rendered)
        self.assertNotIn("median_shift_global_iqr", a003_rendered)
        self.assertNotIn("global_pearson_r", a003_rendered)

        ranked = runner.rank_a003_correlations(runner.pd.DataFrame([
            {"feature": "B", "pearson_r": -.7, "spearman_r": -.6},
            {"feature": "A", "pearson_r": .8, "spearman_r": .75},
            {"feature": "C", "pearson_r": .2, "spearman_r": .9},
        ]), 2)
        self.assertEqual(ranked["feature"].tolist(), ["C", "A"])

        higher = runner.endpoint_distribution_statistics(
            runner.pd.Series([1, 2, 3, 4, 5]), True
        )
        lower = runner.endpoint_distribution_statistics(
            runner.pd.Series([1, 2, 3, 4, 5]), False
        )
        self.assertEqual(higher["favorable_top20_cutoff"], higher["q80"])
        self.assertEqual(higher["unfavorable_bottom20_cutoff"], higher["q20"])
        self.assertEqual(lower["favorable_top20_cutoff"], lower["q20"])
        self.assertEqual(lower["unfavorable_bottom20_cutoff"], lower["q80"])

    def test_a009_renders_required_sections_near_miss_and_full_csv_links(self) -> None:
        runner = self.load_batch_runner("batch_runner_019_report_smoke_test")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "output"
            output.mkdir()

            def write(name: str, content: str) -> Path:
                path = root / name
                path.write_text(content, encoding="utf-8")
                return path

            dataset = write(
                "dataset.csv",
                "compound_id,SMILES,activity\n"
                "C1,CC,1\nC2,CCC,2\nC3,CCCC,3\n"
                "C4,CCO,4\nC5,CCN,5\nC6,CCCl,6\n",
            )
            profile = write(
                "profile.csv",
                "cluster_id,sample_count,favorable_count,favorable_fraction,"
                "selected_for_series\nC000001,6,4,0.6667,True\n",
            )
            enrichment = write(
                "enrichment.csv",
                "cluster_id,description_id,description_name,clustering_id,"
                "clustering_name,sample_count,favorable_count,"
                "favorable_fraction,odds_ratio,fisher_pvalue,q_value_bh,"
                "selected_for_series,parameters_json\n"
                "C000001,D001,RDKit,C005,DBSCAN,6,4,0.6667,4.5,"
                "0.001,0.01,True,\"{\"\"wide\"\":true}\"\n",
            )
            series = write(
                "series.csv",
                "series_id,source_cluster_count,compound_count,"
                "endpoint_valid_count,favorable_count,favorable_fraction,"
                "source_cluster_mean_ff,union_ff_delta_from_source_mean,"
                "accepted,fallback_reason\n"
                "S000001,1,6,6,4,0.6667,0.6667,0,True,\n",
            )
            series_summary = write(
                "series_summary.json",
                json.dumps({
                    "min_ff_evaluate": 10,
                    "favorable_fraction_threshold": .5,
                    "series_with_ff_decrease_count": 0,
                    "median_union_ff_delta_from_source_mean": 0,
                }),
            )
            unit_membership = write(
                "unit_membership.csv",
                "compound_id,analysis_unit_id,membership_value\n"
                + "".join(
                    f"{compound},GLOBAL,True\n{compound},S000001,True\n"
                    for compound in ("C1", "C2", "C3", "C4", "C5", "C6")
                ),
            )
            unit_registry = write(
                "unit_registry.csv",
                "analysis_unit_id,scope_kind,compound_count,"
                "endpoint_valid_count,favorable_fraction,source_cluster_count,"
                "fallback_reason\n"
                "GLOBAL,global,6,6,0.3333,0,\n"
                "S000001,series,6,6,0.6667,1,\n",
            )
            series_clusters = write(
                "series_clusters.csv",
                "series_id,candidate_series_id,cluster_id\n"
                "S000001,S000001,C000001\n",
            )
            support = write(
                "support.csv",
                "series_id,compound_id,support_count,support_fraction\n"
                + "".join(
                    f"S000001,{compound},1,1\n"
                    for compound in ("C1", "C2", "C3", "C4", "C5", "C6")
                ),
            )
            a003 = write(
                "a003.csv",
                "analysis_unit_id,feature,sample_count,pearson_r,"
                "spearman_r,correlation_gain,correlation_q_bh,"
                "median_shift_global_iqr,shift_q_bh,strict_hit,"
                "near_miss_score\n"
                "S000001,MolWt,6,0.3,0.35,0.1,0.08,0.5,0.07,"
                "False,0.9\n",
            )
            a003_plot = root / "A003_top_correlations_S000001.png"
            a003_plot.write_bytes(b"test-png")
            write(
                "A003_top_correlation_plots.json",
                json.dumps({
                    "schema_version": "1.0.0", "top_n": 3,
                    "plots": [{
                        "analysis_unit_id": "S000001",
                        "path": a003_plot.name,
                        "features": [{"rank": 1, "feature": "MolWt"}],
                    }],
                }),
            )
            request = {
                "inputs": [
                    {"role": "dataset", "path": str(dataset)},
                    {"role": "cluster_profile", "path": str(profile)},
                    {"role": "cluster_enrichment", "path": str(enrichment)},
                    {"role": "series_registry", "path": str(series)},
                    {"role": "series_summary", "path": str(series_summary)},
                    {
                        "role": "analysis_unit_membership",
                        "path": str(unit_membership),
                    },
                    {
                        "role": "analysis_unit_registry",
                        "path": str(unit_registry),
                    },
                    {
                        "role": "series_cluster_membership",
                        "path": str(series_clusters),
                    },
                    {"role": "compound_series_support", "path": str(support)},
                    {
                        "role": "source", "path": str(a003),
                        "source_capability_id": "A003",
                    },
                ],
                "columns": {
                    "compound_id": "compound_id",
                    "smiles": "SMILES",
                    "endpoint": "activity",
                },
                "endpoint": {"higher_is_better": True},
                "subject": {"mode": "batch"},
                "parameters": {},
            }
            with mock.patch.object(runner, "finish"):
                runner.run_a009(request, output, {})

            summary_html = (output / "standard_summary.html").read_text(
                encoding="utf-8"
            )
            detail_html = (output / "series_S000001.html").read_text(
                encoding="utf-8"
            )
            index = json.loads(
                (output / "standard_report_index.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertIn('data-report-section="endpoint-overview"', summary_html)
            self.assertIn('data-report-section="at-a-glance"', summary_html)
            self.assertLess(
                summary_html.index('data-report-section="at-a-glance"'),
                summary_html.index('data-report-section="endpoint-overview"'),
            )
            self.assertIn("Criterion-accepted Series", summary_html)
            self.assertIn("All Clusters", summary_html)
            self.assertIn("near-miss: MolWt", summary_html)
            self.assertIn("tables/A003_full.csv", summary_html)
            self.assertNotIn("parameters_json", summary_html)
            self.assertIn('data-report-section="a005"', detail_html)
            self.assertIn("Top feature–Endpoint scatter plots", detail_html)
            self.assertIn("data:image/png;base64", detail_html)
            self.assertIn("相関係数順に上位1件", detail_html)
            self.assertIn("成果物なし", detail_html)
            self.assertEqual(
                index["report_template"], "standard_summary_template.html"
            )
            self.assertAlmostEqual(index["endpoint_overview"]["mean"], 3.5)
            self.assertAlmostEqual(index["endpoint_overview"]["median"], 3.5)
            self.assertAlmostEqual(
                index["endpoint_overview"]["favorable_top20_cutoff"], 5.0
            )
            self.assertAlmostEqual(
                index["endpoint_overview"]["unfavorable_bottom20_cutoff"], 2.0
            )
            self.assertTrue((output / "tables" / "A003_full.csv").is_file())

    def test_a003_generates_top_three_feature_endpoint_scatter_plots(self) -> None:
        runner = self.load_batch_runner("batch_runner_019_a003_scatter_test")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "output"
            output.mkdir()
            dataset = root / "dataset.csv"
            description = root / "D001.csv"
            membership = root / "membership.csv"
            dataset.write_text(
                "compound_id,SMILES,activity\n" + "".join(
                    f"C{index},CC,{index}\n" for index in range(1, 9)
                ),
                encoding="utf-8",
            )
            description.write_text(
                "compound_id,feature_a,feature_b,feature_c,feature_d\n"
                + "".join(
                    f"C{index},{index},{9-index},{index * index},{index % 3}\n"
                    for index in range(1, 9)
                ),
                encoding="utf-8",
            )
            membership.write_text(
                "compound_id,analysis_unit_id,membership_value\n"
                + "".join(
                    f"C{index},S000001,True\n" for index in range(1, 7)
                ),
                encoding="utf-8",
            )
            request = {
                "inputs": [
                    {"role": "dataset", "path": str(dataset)},
                    {
                        "role": "description", "path": str(description),
                        "source_capability_id": "D001",
                    },
                    {
                        "role": "analysis_unit_membership",
                        "path": str(membership),
                    },
                ],
                "columns": {
                    "compound_id": "compound_id", "smiles": "SMILES",
                    "endpoint": "activity",
                },
                "endpoint": {"higher_is_better": True},
                "parameters": {},
            }
            with mock.patch.object(runner, "finish"):
                runner.run_a003(request, output, {})

            plot_index = json.loads(
                (output / "A003_top_correlation_plots.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(plot_index["top_n"], 3)
            self.assertEqual(len(plot_index["plots"]), 1)
            self.assertEqual(
                len(plot_index["plots"][0]["features"]), 3
            )
            self.assertTrue(
                (output / plot_index["plots"][0]["path"]).is_file()
            )

    def test_dbscan_auto_eps_is_positive_for_duplicate_d006_vectors(self) -> None:
        runner_path = SKILLS / "cs-compute-clustering-vector-dbscan" / "scripts" / "run.py"
        specification = importlib.util.spec_from_file_location("dbscan_019_zero_eps_test", runner_path)
        runner = importlib.util.module_from_spec(specification)
        assert specification.loader is not None
        specification.loader.exec_module(runner)
        distance = runner.np.zeros((6, 6), dtype=float)
        args = SimpleNamespace(parameter_mode="auto", min_samples=5, min_cluster_size=5)

        labels, selection = runner.vector_partition(distance, args, "dbscan", "cosine", {})

        eps_values = [candidate["parameters"]["eps"] for candidate in selection["candidates"]]
        self.assertTrue(eps_values)
        self.assertTrue(all(eps > 0 for eps in eps_values))
        self.assertEqual(labels.tolist(), [0, 0, 0, 0, 0, 0])

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

    def test_series_gate_counts_actual_analysis_units_including_fallbacks(self) -> None:
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
                "analysis_unit_count": 20,
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
                "accepted_series_count": 2,
                "analysis_unit_count": 30,
            }), encoding="utf-8")
            gate = runtime.series_gate(Path(temporary), control, dag)
            self.assertIsNotNone(gate)
            self.assertEqual(gate["accepted_series_count"], 2)
            self.assertEqual(gate["analysis_unit_count"], 30)
            self.assertEqual(gate["review_basis"], "analysis_unit_count")
            self.assertEqual(
                gate["current_parameters"],
                {"min_ff_evaluate": 10, "leiden_resolution": 1.0},
            )
            self.assertIn("approve-series", gate["human_actions"])

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

    def test_c012_records_union_ff_dilution_and_fallback_count(self) -> None:
        runner = self.load_batch_runner("series_runner_019_ff_dilution_test")
        runner.finish = lambda *args, **kwargs: None
        runner.leiden_membership = lambda *args, **kwargs: [0, 0]
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            output = base / "output"
            output.mkdir()
            dataset = base / "input.csv"
            dataset.write_text(
                "compound_id,SMILES,activity\n"
                + "".join(
                    f"C{index},CC,{index}\n" for index in range(1, 11)
                ),
                encoding="utf-8",
            )
            membership = base / "membership.csv"
            membership.write_text(
                "compound_id,C000001,C000002\n"
                + "".join(
                    f"C{index},"
                    f"{index in {1, 2, 9, 10}},"
                    f"{index in {3, 4, 9, 10}}\n"
                    for index in range(1, 11)
                ),
                encoding="utf-8",
            )
            registry = base / "registry.csv"
            registry.write_text(
                "cluster_id,source_cluster_id,source_node_id,sample_count\n"
                "C000001,L1,N000001,4\n"
                "C000002,L2,N000002,4\n",
                encoding="utf-8",
            )
            profile = base / "profile.csv"
            enrichment = base / "enrichment.csv"
            content = (
                "cluster_id,sample_count,favorable_fraction,"
                "selected_for_series\n"
                "C000001,4,0.5,True\n"
                "C000002,4,0.5,True\n"
            )
            profile.write_text(content, encoding="utf-8")
            enrichment.write_text(content, encoding="utf-8")
            request = {
                "inputs": [
                    {"role": "dataset", "path": str(dataset)},
                    {
                        "role": "cluster_membership_matrix",
                        "path": str(membership),
                    },
                    {"role": "cluster_registry", "path": str(registry)},
                    {"role": "cluster_profile", "path": str(profile)},
                    {"role": "cluster_enrichment", "path": str(enrichment)},
                ],
                "columns": {
                    "compound_id": "compound_id",
                    "smiles": "SMILES",
                    "endpoint": "activity",
                },
                "endpoint": {"higher_is_better": True},
                "parameters": {
                    "min_ff_evaluate": 4,
                    "favorable_fraction_threshold": .5,
                },
            }
            runner.run_c012(
                request, output,
                {"capability_id": "C012", "stage": "clustering"},
            )
            registry_frame = runner.pd.read_csv(
                output / "series_registry.csv"
            )
            summary = json.loads(
                (output / "series_summary.json").read_text(encoding="utf-8")
            )
        self.assertAlmostEqual(
            float(registry_frame.loc[0, "source_cluster_mean_ff"]), .5
        )
        self.assertAlmostEqual(
            float(
                registry_frame.loc[
                    0, "union_ff_delta_from_source_mean"
                ]
            ),
            -1 / 6,
        )
        self.assertEqual(summary["series_with_ff_decrease_count"], 1)
        self.assertEqual(summary["fallback_cluster_count"], 2)
        self.assertEqual(summary["analysis_unit_count"], 2)

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
