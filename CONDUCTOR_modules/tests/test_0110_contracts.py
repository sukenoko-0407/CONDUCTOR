from __future__ import annotations

import json
import importlib.util
import io
import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / "CONDUCTOR_modules"
SKILLS = ROOT / ".claude" / "skills"


class Version0110Contracts(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = json.loads((MODULES / "catalog" / "analysis_profile.json").read_text(encoding="utf-8"))
        self.selection = json.loads((MODULES / "catalog" / "included_skills.json").read_text(encoding="utf-8"))

    def test_report_and_runtime_pixi_manifests_declare_import_dependencies(self) -> None:
        requirements = {
            "cs-analysis-series-descriptor-contrast": {"matplotlib"},
            "cs-analysis-multidescription-feature-model": {"matplotlib"},
            "cs-analysis-series-landscape": {"matplotlib"},
            "cs-analysis-series-structural-signature": {"matplotlib", "rdkit"},
            "cs-analysis-series-report": {"matplotlib", "rdkit"},
            "cs-conductor-runtime": {"rdkit"},
        }
        for skill_name, expected in requirements.items():
            manifest = tomllib.loads(
                (SKILLS / skill_name / "env" / "pixi.toml").read_text(
                    encoding="utf-8"
                )
            )
            with self.subTest(skill=skill_name):
                self.assertTrue(expected.issubset(manifest["dependencies"]))
        runtime_smoke = tomllib.loads(
            (SKILLS / "cs-conductor-runtime" / "env" / "pixi.toml").read_text(
                encoding="utf-8"
            )
        )["tasks"]["smoke"]
        self.assertIn("rdkit", runtime_smoke)

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

    def make_many_cluster_c012_fixture(self, root: Path) -> dict:
        """Build 25 valid Clusters whose default Leiden result has 25 units."""
        dataset = root / "input.csv"
        dataset.write_text(
            "compound_id,SMILES,activity\n" + "".join(
                f"C{index},CC,{index}\n" for index in range(1, 51)
            ),
            encoding="utf-8",
        )
        cluster_ids = [f"C{index:06d}" for index in range(1, 26)]
        membership = root / "membership.csv"
        membership.write_text(
            "compound_id," + ",".join(cluster_ids) + "\n" + "".join(
                f"C{compound}," + ",".join(
                    "True" if compound >= 41 else "False"
                    for _ in cluster_ids
                ) + "\n"
                for compound in range(1, 51)
            ),
            encoding="utf-8",
        )
        registry = root / "registry.csv"
        registry.write_text(
            "cluster_id,source_cluster_id,source_node_id,sample_count\n"
            + "".join(
                f"{cluster_id},L{position:06d},N000001,10\n"
                for position, cluster_id in enumerate(cluster_ids, 1)
            ),
            encoding="utf-8",
        )
        statistics = root / "statistics.csv"
        statistics.write_text(
            "cluster_id,sample_count,favorable_fraction,selected_for_series\n"
            + "".join(
                f"{cluster_id},10,1.0,True\n" for cluster_id in cluster_ids
            ),
            encoding="utf-8",
        )
        return {
            "inputs": [
                {"role": "dataset", "path": str(dataset)},
                {
                    "role": "cluster_membership_matrix",
                    "path": str(membership),
                },
                {"role": "cluster_registry", "path": str(registry)},
                {"role": "cluster_profile", "path": str(statistics)},
                {"role": "cluster_enrichment", "path": str(statistics)},
            ],
            "columns": {
                "compound_id": "compound_id", "smiles": "SMILES",
                "endpoint": "activity",
            },
            "endpoint": {"higher_is_better": True},
            "parameters": {
                "parameter_search_enabled": True,
                "resolution_grid": [1.0, 1.25, 1.5, 2.0, 2.5, 3.0],
                "min_ff_evaluate_grid": [10, 15, 20, 25, 30],
                "favorable_fraction_threshold": 0.5,
                "multi_cluster_favorable_fraction_threshold": 0.4,
                "max_units_for_auto_standard": 24,
                "absolute_max_analysis_units": 100,
            },
        }

    def test_basic_compute_is_all_description_all_vector_clustering(self) -> None:
        basic = self.profile["basic_compute"]
        self.assertEqual(len(basic["description_capabilities"]), 18)
        self.assertEqual(basic["vector_clustering_representations"], basic["description_capabilities"])
        self.assertEqual(basic["vector_clustering_capabilities"], ["C005", "C006", "C007", "C008", "C009", "C010"])
        self.assertEqual(basic["survey_capabilities"], ["A001", "A002"])
        self.assertEqual(basic["series_clustering"], "C012")

    def test_every_description_declares_0110_and_calculation_version(self) -> None:
        for skill_name in self.selection["description_skills"]:
            capability = json.loads(
                (SKILLS / skill_name / "capability.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(capability["version"], "0.1.10", skill_name)
            self.assertTrue(str(capability.get("calculation_version", "")), skill_name)

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
        self.assertIn("<details class='report-table'>", basic)
        self.assertIn("sortable", basic)
        self.assertIn("列の説明", basic)
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
        self.assertIn("$target_structure_image", template)
        self.assertIn("$neighbor_structure_gallery", template)
        self.assertLess(
            template.index("$basic_information_table"),
            template.index("2D構造図に示したTargetとNeighbor"),
        )
        self.assertLess(
            template.index("$mmp_detail_table"),
            template.index("Targetは表示上常にTo"),
        )
        self.assertLess(
            template.index("$transformation_gallery"),
            template.index("Attachment pointを含む同一Core"),
        )
        self.assertIn('<details class="section-explanation">', template)
        self.assertIn("詳細CSVリンク", template)
        overview_template = (
            SKILLS / "cs-analysis-matched-molecular-pairs" / "templates"
            / "mmp_overview_report_template.html"
        ).read_text(encoding="utf-8")
        self.assertIn("$target_gallery", overview_template)

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

        neighbor = runner.depiction_molecule("c1ccccc1Cl")
        target = runner.depiction_molecule("c1ccccc1N")
        self.assertTrue(
            runner.align_target_depiction_to_neighbor(
                neighbor, target, "c1ccccc1[*:1]"
            )
        )
        self.assertEqual(neighbor.GetNumConformers(), 1)
        self.assertEqual(target.GetNumConformers(), 1)
        second_neighbor = runner.depiction_molecule("c1ccccc1F")
        self.assertTrue(
            runner.align_neighbor_depiction_to_target(
                target, second_neighbor, "c1ccccc1[*:1]"
            )
        )
        self.assertEqual(second_neighbor.GetNumConformers(), 1)

        with tempfile.TemporaryDirectory() as temporary:
            target_html, neighbor_html, structure_artifacts = (
                runner.render_target_neighbor_structures(
                    "T1", "c1ccccc1N", oriented,
                    Path(temporary), "target",
                )
            )
            self.assertEqual(len(structure_artifacts), 2)
            self.assertTrue(all(path.is_file() for path in structure_artifacts))
        self.assertIn("single-target-structure", target_html)
        self.assertIn("<details class='neighbor-structure-gallery'>", neighbor_html)
        self.assertIn("共通する構造を基準に向きを揃え", neighbor_html)

        with tempfile.TemporaryDirectory() as temporary:
            overview_html, overview_artifacts = runner.render_target_overview_gallery(
                runner.pd.DataFrame([
                    {"analysis_unit_id": "C000001", "target_compound_id": "T1"},
                    {"analysis_unit_id": "S000001", "target_compound_id": "T1"},
                ]),
                runner.pd.DataFrame([{
                    "compound_id": "T1", "SMILES": "c1ccccc1N", "activity": 8.0,
                }]),
                "compound_id", "SMILES", "activity", Path(temporary),
            )
            overview_svg = overview_artifacts[0].read_text(encoding="utf-8")
        self.assertIn("各analysis unitのTargetを4列", overview_html)
        self.assertIn("width='1080px'", overview_svg)
        self.assertIn("height='230px'", overview_svg)

    def test_mmp_report_keeps_incomparable_maximal_cores(self) -> None:
        runner = self.load_mmp_runner("mmp_runner_0110_incomparable_core_test")
        common = {
            "target_compound_id": "T1", "neighbor_compound_id": "N1",
            "target_endpoint": 8.0, "neighbor_endpoint": 3.0,
            "target_smiles": "CCCCN", "neighbor_smiles": "CCCCCl",
            "variable_neighbor": "[*:1]Cl", "variable_target": "[*:1]N",
            "favorable_delta_toward_target": 5.0,
        }
        frame = runner.pd.DataFrame([
            {
                **common, "mmp_id": "MMP_AROMATIC",
                "exact_core_smiles": "c1ccccc1[*:1]",
            },
            {
                **common, "mmp_id": "MMP_ALIPHATIC",
                "exact_core_smiles": "C1CCCCC1[*:1]",
            },
        ])
        selected = runner.select_minimal_transform_rows(frame)
        self.assertEqual(
            set(selected["mmp_id"]), {"MMP_AROMATIC", "MMP_ALIPHATIC"}
        )

    def test_mmp_core_group_expands_top_five_and_folds_remaining_rows(self) -> None:
        runner = self.load_mmp_runner("mmp_runner_0110_core_group_test")
        frame = runner.pd.DataFrame([
            {
                "mmp_id": f"MMP{index:06d}",
                "target_compound_id": "T1",
                "neighbor_compound_id": f"N{index}",
                "target_endpoint": 10.0,
                "neighbor_endpoint": float(index),
                "target_smiles": "CCCCN",
                "neighbor_smiles": "CCCCCl",
                "exact_core_smiles": "CCCC[*:1]",
                "variable_neighbor": "[*:1]Cl",
                "variable_target": "[*:1]N",
                "favorable_delta_report": float(10 - index),
            }
            for index in range(1, 7)
        ])
        with tempfile.TemporaryDirectory() as temporary:
            gallery, artifacts = runner.render_core_group_gallery(
                frame, Path(temporary), "target"
            )
            self.assertEqual(len(artifacts), 7)  # one core + six transformations
            self.assertTrue(all(path.is_file() for path in artifacts))
            transformation_svg = "\n".join(
                path.read_text(encoding="utf-8")
                for path in artifacts if "mmp_transform_" in path.name
            )
        self.assertEqual(gallery.count("Core group 1"), 1)
        self.assertNotIn("Core group 2", gallery)
        self.assertIn("残り1件を表示", gallery)
        self.assertIn("Neighbor N1", gallery)
        self.assertIn("core-summary-layout", gallery)
        self.assertIn("metric-stack", gallery)
        self.assertIn("width='1080px'", transformation_svg)
        source = (
            SKILLS / "cs-analysis-matched-molecular-pairs" / "scripts" / "run.py"
        ).read_text(encoding="utf-8")
        source = source[
            source.index("def render_transformation_gallery"):
            source.index("def render_core_group_gallery")
        ]
        labels = [
            "f\"Neighbor {neighbor_id}\"",
            "f\"Target {getattr(record, 'target_compound_id', '—')}\"",
            '"Before fragment (Neighbor)"',
            '"After fragment (Target)"',
        ]
        positions = [source.index(label) for label in labels]
        self.assertEqual(positions, sorted(positions))

        scope = runner.mmp_report_scope_note(frame, frame)
        self.assertIn("一意MMP 6件をすべて", scope)
        self.assertIn("上位5件を初期表示", scope)
        self.assertIn("残り1件", scope)
        empty_scope = runner.mmp_report_scope_note(frame.iloc[0:0], frame.iloc[0:0])
        self.assertEqual(
            empty_scope, "このTargetに接続するMMPは検出されませんでした。"
        )

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
            self.assertIn("一意MMPを2件検出", target_html)
            self.assertIn("最小変換へ整理した1件", target_html)
            self.assertIn("詳細CSVリンク", target_html)
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
                "schema_version": "1.0.0", "conductor_version": "0.1.10",
                "project": "test", "run_id": "RUN019", "input_path": str(source),
                "input_sha256": runtime.sha256(source),
                "columns": {"compound_id": "compound_id", "smiles": "SMILES", "endpoint": "activity"},
                "active_round_id": None, "round_status": "NONE", "revision": 0,
            }
            dag = {"schema_version": "1.0.0", "conductor_version": "0.1.10", "revision": 0, "nodes": []}
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
            "summary", "endpoint-distribution", "selected-clusters",
            "series-formation", "operator-results", "projections",
            "detail-reports",
        }
        for section in required_standard_sections:
            self.assertIn(f'data-report-section="{section}"', standard)
        self.assertLess(
            standard.index('data-report-section="summary"'),
            standard.index('data-report-section="endpoint-distribution"'),
        )
        self.assertNotIn('data-report-section="report-scope"', standard)
        self.assertNotIn('data-report-section="execution-status"', standard)
        self.assertNotIn('data-report-section="full-tables-and-limitations"', standard)
        self.assertIn("$summary_metrics", standard)
        self.assertNotIn("$at_a_glance_table", standard)
        self.assertIn('class="summary-distribution-figure"', standard)
        for section in {
            "unit-definition", "projection", "a003", "a005", "a006", "a007",
        }:
            self.assertIn(f'data-report-section="{section}"', detail)
        self.assertNotIn('data-report-section="full-tables-and-limitations"', detail)
        self.assertLess(
            detail.index("$a006_table"), detail.index("$a006_explanation")
        )
        self.assertLess(
            detail.index("$a007_gallery"), detail.index("$a007_explanation")
        )
        self.assertIn('<details class="section-explanation">', detail)
        self.assertIn("$a005_prediction_plot", detail)

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
        self.assertIn("<details class='report-table'>", rendered)
        self.assertIn("sortable", rendered)
        self.assertIn("列の説明", rendered)
        self.assertIn("Cluster ID", rendered)
        self.assertNotIn("parameters_json", rendered)
        self.assertNotIn("intentionally hidden", rendered)

        unit_info = runner.pd.DataFrame([{
            "analysis_unit_id": "C000001", "scope_kind": "cluster",
        }])
        source_info = runner.source_clusters_for_analysis_unit(
            "C000001",
            unit_info,
            runner.pd.DataFrame([{
                "series_id": "S000999", "cluster_id": "C000001",
            }]),
            runner.pd.DataFrame([{
                "cluster_id": "C000001", "description_id": "D001",
                "description_name": "RDKit 2D descriptors",
                "clustering_id": "C005", "clustering_name": "Vector Butina",
            }]),
        )
        self.assertEqual(source_info["cluster_id"].tolist(), ["C000001"])
        source_legend = runner.id_legend(source_info)
        self.assertIn("<summary>特徴量／クラスタリングの説明</summary>", source_legend)
        self.assertIn("D001", source_legend)
        self.assertIn("RDKit 2D", source_legend)
        self.assertIn("C005", source_legend)
        self.assertIn("Vector Butina", source_legend)

        structural_info = runner.report_cluster_provenance(
            runner.pd.DataFrame([{
                "cluster_id": "C000003", "description_id": "D001",
                "description_name": "RDKit 2D descriptors",
                "clustering_id": "C001", "clustering_name": "Murcko scaffold",
            }])
        )
        self.assertTrue(structural_info["description_id"].isna().all())
        structural_legend = runner.id_legend(structural_info)
        self.assertNotIn("D001", structural_legend)
        self.assertIn("C001", structural_legend)
        structural_explanation = runner.structural_signature_explanation(
            "C000003", unit_info, structural_info
        )
        self.assertIn("構造由来（C001：Murcko scaffold）", structural_explanation)
        self.assertIn("直接定義したKey構造を", structural_explanation)
        self.assertNotIn("Key構造だけ", structural_explanation)
        self.assertIn("boundary pair", runner.OPERATOR_EXPLANATIONS["A006"])
        self.assertIn("活性enrichmentの境界", runner.OPERATOR_EXPLANATIONS["A006"])
        self.assertIn("unit全体の優位を証明するものではなく", runner.OPERATOR_EXPLANATIONS["A006"])
        a006_rendered = runner.compact_table(runner.pd.DataFrame([{
            "analysis_unit_id": "S000001", "sample_count": 20,
            "status": "succeeded", "boundary_cliff_count": 4,
            "boundary_favorable_count": 3,
            "boundary_favorable_direction_fraction": .75,
        }]), "A006")
        self.assertIn("Boundary favorable direction", a006_rendered)
        self.assertIn("3 / 4", a006_rendered)
        self.assertEqual(
            runner.section_csv_link("tables/result.csv"),
            "<p class='muted'><a href='tables/result.csv'>詳細CSVリンク</a></p>",
        )

        a003_frame = runner.pd.DataFrame([{
            "feature": "MolWt", "description_id": "D001",
            "sample_count": 12, "pearson_r": .81,
            "spearman_r": .78, "max_abs_correlation": .81,
            "correlation_q_bh": .01, "strict_hit": True,
            "median_shift_global_iqr": 1.2, "shift_q_bh": .02,
            "global_pearson_r": .15,
        }])
        a003_rendered = runner.compact_table(a003_frame, "A003_detail")
        self.assertIn("Max |r|", a003_rendered)
        self.assertLess(a003_rendered.index("Description ID"), a003_rendered.index("N"))
        self.assertNotIn("Correlation BH q", a003_rendered)
        self.assertNotIn("Strict hit", a003_rendered)
        self.assertNotIn("median_shift_global_iqr", a003_rendered)
        self.assertNotIn("global_pearson_r", a003_rendered)

        fallback_row = runner.pd.Series({
            "cluster_id": runner.pd.NA,
            "clustering_id": "C001",
            "method": "fallback_murcko",
        })
        self.assertEqual(
            runner.key_structure_legend(fallback_row, "C000003"),
            "C000003 (Murcko)",
        )
        a007_rendered = runner.compact_table(
            runner.pd.DataFrame([{
                "analysis_unit_id": "C000003", "method": "fallback_murcko",
                "clustering_id": "C001", "cluster_id": runner.pd.NA,
                "structure": "c1ccccc1", "support_count": 10,
                "source_member_count": 20, "mcs_canceled": False,
                "status": "succeeded", "reason": "",
            }]),
            "A007",
        )
        self.assertIn("Murcko scaffold", a007_rendered)
        self.assertNotIn("fallback_murcko", a007_rendered)

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
                "analysis_unit_id,feature,description_id,sample_count,pearson_r,"
                "spearman_r,correlation_gain,correlation_q_bh,"
                "median_shift_global_iqr,shift_q_bh,correlation_hit,strict_hit,"
                "near_miss_score\n"
                "S000001,MolWt,D001,6,0.3,0.35,0.1,0.08,0.5,0.07,False,"
                "False,0.9\n",
            )
            a005 = write(
                "a005.csv",
                "analysis_unit_id,member_count,model_count,status,oof_r2,"
                "global_oof_on_same_series_r2,local_minus_global_r2,oof_mae,"
                "global_minus_local_mae,strict_improvement,near_miss_score,reason\n"
                "S000001,6,6,succeeded,0.1,0.15,-0.05,1.1,-0.2,False,0.75,"
                "best available model\n",
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
            a005_plot = root / "A005_oof_comparison_S000001.png"
            a005_plot.write_bytes(b"test-png")
            write(
                "A005_oof_comparison_plots.json",
                json.dumps({
                    "schema_version": "1.0.0",
                    "plots": [{
                        "analysis_unit_id": "S000001",
                        "path": a005_plot.name,
                        "sample_count": 6,
                    }],
                }),
            )
            mmp_dir = root / "mmp"
            mmp_dir.mkdir()
            mmp_report = mmp_dir / "mmp_target_C6.html"
            mmp_report.write_text(
                "<html><body><header><h1>MMP C6</h1></header></body></html>",
                encoding="utf-8",
            )
            mmp_index = mmp_dir / "mmp_report_index.json"
            mmp_index.write_text(json.dumps({
                "schema_version": "1.0.0",
                "unit_reports": [{
                    "analysis_unit_id": "S000001",
                    "target_compound_id": "C6",
                    "target_rank": 1,
                    "target_endpoint": 6.0,
                    "pair_count": 1,
                    "report_path": mmp_report.name,
                }],
            }), encoding="utf-8")
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
                    {
                        "role": "source", "path": str(a005),
                        "source_capability_id": "A005",
                    },
                    {"role": "mmp_report_index", "path": str(mmp_index)},
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
            self.assertIn('data-report-section="endpoint-distribution"', summary_html)
            self.assertIn('data-report-section="summary"', summary_html)
            self.assertLess(
                summary_html.index('data-report-section="summary"'),
                summary_html.index('data-report-section="endpoint-distribution"'),
            )
            self.assertIn("Standard-criterion Series", summary_html)
            self.assertIn("All Clusters", summary_html)
            self.assertNotIn("参考・基準未達: MolWt", summary_html)
            self.assertIn("各analysis unitの最良結果を1件ずつ", summary_html)
            self.assertIn("best available model", summary_html)
            self.assertIn("tables/A003_full.csv", summary_html)
            self.assertIn("tables/A005_full.csv", summary_html)
            self.assertNotIn("parameters_json", summary_html)
            self.assertIn("table.sortable", summary_html)
            self.assertIn("クリックして並べ替え", summary_html)
            report_source = (
                MODULES / "tools" / "templates" / "series_batch_runner.py"
            ).read_text(encoding="utf-8")
            self.assertIn('label=f"{label}: {report_value(value)}"', report_source)
            self.assertIn('label=f"Favorable cutoff:', report_source)
            self.assertIn('label=f"Unfavorable cutoff:', report_source)
            self.assertIn("endpoint_boxplot_width = 1080", report_source)
            self.assertIn('data-report-section="a005"', detail_html)
            self.assertIn("OOF予測値と実測値", detail_html)
            self.assertIn("上位3 feature–Endpoint散布図", detail_html)
            self.assertIn("data:image/png;base64", detail_html)
            self.assertNotIn("相関係数順に上位1件", detail_html)
            self.assertIn("該当結果なし", detail_html)
            self.assertIn("Type-I MMP Top 1", detail_html)
            self.assertIn("mmp_reports/mmp_target_C6.html", detail_html)
            copied_mmp = (
                output / "mmp_reports" / "mmp_target_C6.html"
            ).read_text(encoding="utf-8")
            self.assertIn("../series_S000001.html", copied_mmp)
            self.assertIn("A009 S000001", copied_mmp)
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
            self.assertTrue((output / "endpoint_analysis_unit_boxplot.png").is_file())

    def test_a003_generates_top_three_feature_endpoint_scatter_plots(self) -> None:
        runner = self.load_batch_runner("batch_runner_019_a003_scatter_test")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "output"
            output.mkdir()
            dataset = root / "dataset.csv"
            membership = root / "membership.csv"
            dataset.write_text(
                "compound_id,SMILES,activity\n" + "".join(
                    f"C{index},CC,{index}\n" for index in range(1, 9)
                ),
                encoding="utf-8",
            )
            description_specs = {
                "D001": ("feature_a,feature_b", lambda index: f"{index},{9-index}"),
                "D012": ("rdkit3d__PBF,rdkit3d__NPR1", lambda index: f"{index * index},{index / 10}"),
                "D015": ("mordred__nAcid,mordred__nRing,mordred__ABC", lambda index: f"{index % 2},{index % 4},{index * 9}"),
                "D016": ("mordred__GeomDiameter,mordred__PNSA1,mordred__Mor01", lambda index: f"{index * 1.5},{index * 2},{index * 11}"),
                "D019": ("xtb__dipole,xtb__homo", lambda index: f"{index / 3},{-index}"),
            }
            description_paths = {}
            for description_id, (header, values) in description_specs.items():
                description_path = root / f"{description_id}.csv"
                description_path.write_text(
                    f"compound_id,{header}\n" + "".join(
                        f"C{index},{values(index)}\n" for index in range(1, 9)
                    ),
                    encoding="utf-8",
                )
                description_paths[description_id] = description_path
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
                    *[
                        {
                            "role": "description", "path": str(path),
                            "source_capability_id": description_id,
                        }
                        for description_id, path in description_paths.items()
                    ],
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
            self.assertTrue(all(
                record.get("description_id") in runner.A003_DESCRIPTION_PANEL
                for record in plot_index["plots"][0]["features"]
            ))
            self.assertEqual(
                len(plot_index["plots"][0]["features"]), 3
            )
            self.assertTrue(
                (output / plot_index["plots"][0]["path"]).is_file()
            )
            result = runner.pd.read_csv(output / "A003_series_descriptor_contrast.csv")
            self.assertEqual(
                set(result["description_id"]), set(runner.A003_DESCRIPTION_PANEL)
            )
            self.assertNotIn("mordred__ABC", set(result["feature"]))
            self.assertNotIn("mordred__Mor01", set(result["feature"]))

    def test_a005_generates_local_and_global_oof_comparison_plot(self) -> None:
        runner = self.load_batch_runner("batch_runner_0110_a005_plot_test")
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            predictions = runner.pd.DataFrame([
                *[
                    {
                        "analysis_unit_id": "GLOBAL", "compound_id": f"C{i}",
                        "observed": float(i), "oof_prediction": float(i) + .2,
                    }
                    for i in range(1, 7)
                ],
                *[
                    {
                        "analysis_unit_id": "S000001", "compound_id": f"C{i}",
                        "observed": float(i), "oof_prediction": float(i) + .1,
                    }
                    for i in range(1, 7)
                ],
            ])
            metrics = runner.pd.DataFrame([{
                "analysis_unit_id": "S000001", "oof_r2": .8,
                "global_oof_on_same_series_r2": .6,
            }])
            index_path, plots = runner.render_a005_oof_comparison_plots(
                predictions, metrics, output
            )
            self.assertEqual(len(plots), 1)
            self.assertTrue(plots[0].is_file())
            index = json.loads(index_path.read_text(encoding="utf-8"))
            self.assertEqual(index["plots"][0]["analysis_unit_id"], "S000001")
            self.assertEqual(index["plots"][0]["sample_count"], 6)

    def test_a007_emits_support_ranked_structure_image_index(self) -> None:
        runner = self.load_batch_runner("batch_runner_0110_a007_images_test")
        runner.finish = lambda *args, **kwargs: None
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "output"
            output.mkdir()
            dataset = root / "dataset.csv"
            dataset.write_text(
                "compound_id,SMILES,activity\n"
                "C1,c1ccccc1C,1\nC2,c1ccccc1N,2\n",
                encoding="utf-8",
            )
            membership = root / "membership.csv"
            membership.write_text(
                "compound_id,analysis_unit_id,membership_value\n"
                "C1,S000001,True\nC2,S000001,True\n",
                encoding="utf-8",
            )
            request = {
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
                "parameters": {"mcs_timeout_seconds": 5},
            }
            runner.run_a007(
                request, output,
                {"capability_id": "A007", "stage": "analysis"},
            )
            index = json.loads(
                (output / "A007_structure_images.json").read_text(
                    encoding="utf-8"
                )
            )
            image_exists = (
                output / str(index["images"][0]["path"])
            ).is_file()
        self.assertEqual(index["selection"], "support_descending")
        self.assertEqual(index["top_n"], 5)
        self.assertEqual(index["images"][0]["analysis_unit_id"], "S000001")
        self.assertTrue(image_exists)

    def test_a007_uses_direct_keys_only_for_structural_clusters(self) -> None:
        runner = self.load_batch_runner("batch_runner_0110_a007_origin_test")
        runner.finish = lambda *args, **kwargs: None
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "output"
            output.mkdir()
            dataset = root / "dataset.csv"
            dataset.write_text(
                "compound_id,SMILES,activity\n"
                "C1,c1ccccc1C,1\nC2,c1ccccc1N,2\n"
                "C3,c1ccccc1O,3\nC4,c1ccccc1F,4\n",
                encoding="utf-8",
            )
            unit_membership = root / "unit_membership.csv"
            unit_membership.write_text(
                "compound_id,analysis_unit_id,membership_value\n"
                + "".join(
                    f"{compound},CSTR,True\n{compound},CVEC,True\n"
                    for compound in ("C1", "C2", "C3", "C4")
                ),
                encoding="utf-8",
            )
            registry = root / "registry.csv"
            registry.write_text(
                "cluster_id,source_cluster_id,source_node_id,clustering_id,"
                "input_kind,sample_count,structure_definition\n"
                "CSTR,L1,N1,C001,structure,4,c1ccccc1\n"
                "CVEC,L2,N2,C005,description_vector,4,\n",
                encoding="utf-8",
            )
            cluster_membership = root / "cluster_membership.csv"
            cluster_membership.write_text(
                "compound_id,cluster_id,membership_value\n"
                + "".join(
                    f"{compound},CVEC,True\n"
                    for compound in ("C1", "C2", "C3", "C4")
                ),
                encoding="utf-8",
            )
            request = {
                "inputs": [
                    {"role": "dataset", "path": str(dataset)},
                    {"role": "analysis_unit_membership", "path": str(unit_membership)},
                    {"role": "cluster_registry", "path": str(registry)},
                    {"role": "cluster_membership_long", "path": str(cluster_membership)},
                ],
                "columns": {
                    "compound_id": "compound_id", "smiles": "SMILES",
                    "endpoint": "activity",
                },
                "parameters": {"mcs_timeout_seconds": 5},
            }
            runner.run_a007(
                request, output,
                {"capability_id": "A007", "stage": "analysis"},
            )
            result = runner.pd.read_csv(
                output / "A007_series_structural_signature.csv"
            )
        structural = result.loc[result["analysis_unit_id"].eq("CSTR")]
        vector = result.loc[result["analysis_unit_id"].eq("CVEC")]
        self.assertEqual(
            structural["method"].tolist(), ["source_structural_cluster"]
        )
        self.assertEqual(structural["structure"].tolist(), ["c1ccccc1"])
        self.assertEqual(
            set(vector["method"]), {"fallback_murcko", "fallback_mcs"}
        )
        self.assertEqual(set(vector["cluster_id"]), {"CVEC"})

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
                "revision": 0, "conductor_version": "0.1.10", "run_id": "RUN019",
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
            mmp_index = root / "mmp_report_index.json"
            mmp_index.write_text(
                json.dumps({"schema_version": "1.0.0", "unit_reports": []}),
                encoding="utf-8",
            )
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
        mmp_inputs = [
            item for item in request["inputs"]
            if item.get("role") == "mmp_report_index"
        ]
        self.assertEqual(len(mmp_inputs), 1)
        self.assertEqual(Path(mmp_inputs[0]["path"]).name, "mmp_report_index.json")

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

    def test_c012_recomputes_selection_instead_of_using_stale_flags(self) -> None:
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
                "parameters": {"min_ff_evaluate": 2, "favorable_fraction_threshold": 0.5},
            }
            runner.finish = lambda *args, **kwargs: None
            runner.run_c012(
                request, base / "output",
                {"capability_id": "C012", "stage": "clustering"},
            )
            selected = runner.pd.read_csv(
                base / "output" / "selected_clusters_effective.csv"
            )
            self.assertEqual(selected["cluster_id"].tolist(), ["C000001"])

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

    def test_c012_accepts_multi_cluster_series_at_relaxed_ff_040(self) -> None:
        runner = self.load_batch_runner("series_runner_0110_relaxed_ff_test")
        frame = runner.pd.DataFrame({
            "compound_id": [f"C{index}" for index in range(1, 11)],
            "activity": list(range(1, 11)),
        })
        enrichment = runner.pd.DataFrame([
            {
                "cluster_id": "C000001", "sample_count": 4,
                "favorable_fraction": 0.5,
            },
            {
                "cluster_id": "C000002", "sample_count": 4,
                "favorable_fraction": 0.5,
            },
        ])
        with mock.patch.object(
            runner, "leiden_membership", return_value=[0, 0]
        ):
            result = runner.evaluate_series_configuration(
                cluster_sets={
                    "C000001": {"C1", "C2", "C9", "C10"},
                    "C000002": {"C1", "C3", "C9", "C10"},
                },
                enrichment=enrichment,
                frame=frame,
                compound_id_column="compound_id",
                endpoint_column="activity",
                higher_is_better=True,
                min_ff_evaluate=4,
                resolution=1.0,
                random_seed=61453,
                cluster_ff_threshold=0.5,
                multi_cluster_ff_threshold=0.4,
            )
        row = result["series_rows"][0]
        self.assertTrue(row["accepted"])
        self.assertAlmostEqual(row["favorable_fraction"], 0.4)
        self.assertEqual(row["applied_ff_threshold"], 0.4)
        self.assertEqual(row["acceptance_basis"], "multi_cluster_relaxed_0.40")
        self.assertAlmostEqual(row["global_favorable_fraction"], 0.2)
        self.assertAlmostEqual(row["ff_delta_from_global"], 0.2)
        self.assertAlmostEqual(row["ff_enrichment_ratio"], 2.0)
        self.assertEqual(result["summary"]["relaxed_series_count"], 1)

    def test_c012_resolution_search_auto_selects_first_condition_at_24_or_less(self) -> None:
        runner = self.load_batch_runner("series_runner_0110_auto_search_test")
        runner.finish = lambda *args, **kwargs: None
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "output"
            output.mkdir()
            request = self.make_many_cluster_c012_fixture(root)

            def membership(vertex_count, edges, weights, resolution, seed):
                return (
                    list(range(vertex_count)) if resolution < 1.25
                    else [0] * vertex_count
                )

            with mock.patch.object(
                runner, "leiden_membership", side_effect=membership
            ):
                runner.run_c012(
                    request, output,
                    {"capability_id": "C012", "stage": "clustering"},
                )
            search = json.loads(
                (output / "series_parameter_search.json").read_text(
                    encoding="utf-8"
                )
            )
            summary = json.loads(
                (output / "series_summary.json").read_text(encoding="utf-8")
            )
            canonical_series_exists = (output / "series_registry.csv").is_file()
        self.assertEqual(
            search["chosen_condition"],
            {"min_ff_evaluate": 10, "leiden_resolution": 1.25},
        )
        self.assertTrue(search["automatic_selection"])
        self.assertFalse(search["selection_required"])
        self.assertEqual(summary["analysis_unit_count"], 1)
        self.assertTrue(canonical_series_exists)

    def test_c012_emits_30_condition_session_matrix_without_canonical_preview(self) -> None:
        runner = self.load_batch_runner("series_runner_0110_human_matrix_test")
        runner.finish = lambda *args, **kwargs: None
        runner.leiden_membership = (
            lambda vertex_count, edges, weights, resolution, seed:
            list(range(vertex_count))
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "output"
            output.mkdir()
            request = self.make_many_cluster_c012_fixture(root)
            runner.run_c012(
                request, output,
                {"capability_id": "C012", "stage": "clustering"},
            )
            search = json.loads(
                (output / "series_parameter_search.json").read_text(
                    encoding="utf-8"
                )
            )
            summary = json.loads(
                (output / "series_summary.json").read_text(encoding="utf-8")
            )
            files = {path.name for path in output.iterdir()}
        self.assertTrue(search["selection_required"])
        self.assertEqual(search["status"], "awaiting_human_selection")
        self.assertEqual(len(search["evaluations"]), 30)
        default = next(
            row for row in search["evaluations"]
            if row["min_ff_evaluate"] == 10
            and row["leiden_resolution"] == 1.0
        )
        filtered = next(
            row for row in search["evaluations"]
            if row["min_ff_evaluate"] == 15
            and row["leiden_resolution"] == 1.0
        )
        self.assertEqual(default["analysis_unit_count"], 25)
        self.assertEqual(default["cluster_coverage"], 1.0)
        self.assertEqual(default["compound_coverage"], 1.0)
        self.assertEqual(filtered["analysis_unit_count"], 0)
        self.assertEqual(filtered["cluster_coverage"], 0.0)
        self.assertEqual(filtered["compound_coverage"], 0.0)
        self.assertTrue(summary["selection_required"])
        self.assertNotIn("series_registry.csv", files)
        self.assertNotIn("analysis_unit_registry.csv", files)
        self.assertNotIn("clustering_report.html", files)

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
                "schema_version": "2.0.0", "conductor_version": "0.1.10",
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

    def test_round1_has_no_description_high_cost_approval_branch(self) -> None:
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
            _, dag = runtime.load_state(run_root)
        table = {
            node["capability_id"]: node for node in runtime.nodes(dag)
            if node["capability_id"] in {"D016", "D019", "D020"}
        }
        self.assertEqual(
            {item: table[item]["status"] for item in table},
            {"D016": "pending", "D019": "pending", "D020": "pending"},
        )
        self.assertFalse(hasattr(runtime, "cmd_approve_high_cost"))
        self.assertNotIn(
            "approve-high-cost", controller_path.read_text(encoding="utf-8")
        )

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
                "schema_version": "1.0.0", "conductor_version": "0.1.10", "run_id": "RUN019",
                "active_round_id": "RND0001", "round_status": "ACTIVE", "revision": 0,
                "lease": {"token": "expired", "expires_at": "2000-01-01T00:00:00+00:00"},
            }
            dag = {"schema_version": "1.0.0", "conductor_version": "0.1.10", "revision": 0, "nodes": [{
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
