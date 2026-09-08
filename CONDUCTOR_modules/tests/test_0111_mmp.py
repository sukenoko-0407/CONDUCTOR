from __future__ import annotations

import importlib
import importlib.util
import json
import re
import sqlite3
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import closing
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / "CONDUCTOR_modules"
SCRIPTS = ROOT / ".claude" / "skills" / "cs-analysis-matched-molecular-pairs" / "scripts"
TEMPLATES = ROOT / ".claude" / "skills" / "cs-analysis-matched-molecular-pairs" / "templates"


class Version0111MMP(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        sys.path.insert(0, str(SCRIPTS))
        cls.model = importlib.import_module("mmp_0111_model")
        cls.evidence = importlib.import_module("mmp_0111_evidence")
        cls.runner = importlib.import_module("mmp_0111_runner")
        cls.engine = importlib.import_module("mmp_engine")

    @classmethod
    def tearDownClass(cls) -> None:
        sys.path.remove(str(SCRIPTS))

    def _row(self, **updates):
        row = {
            "mmp_id": "MMP-1",
            "compound_id_from": "C1",
            "compound_id_to": "C2",
            "smiles_from": "CCc1ccccc1",
            "smiles_to": "Clc1ccccc1",
            "endpoint_from": 5.0,
            "endpoint_to": 6.0,
            "endpoint_delta": 1.0,
            "favorable_delta": 1.0,
            "variable_from": "C[*:1]",
            "variable_to": "Cl[*:1]",
            "transform_id": "legacy",
            "transform_smirks": "C[*:1]>>Cl[*:1]",
            "exact_core_smiles": "c1ccc([*:1])cc1",
            "core_id": "legacy-core",
            "core_heavy_atoms": 6,
            "core_fraction_from": 0.75,
            "core_fraction_to": 0.85,
            "core_molecular_weight": 77.0,
            "cut_count": 1,
            "attachment_mapping": "[1]",
            "native_rule_id": 1,
            "endpoint_missing": False,
            "quality_flags": "",
        }
        row.update(updates)
        return row

    def test_canonical_direction_is_invariant_to_native_row_direction(self) -> None:
        forward = self.model.canonicalize_pair_transformations(
            pd.DataFrame([self._row()]), higher_is_better=True
        ).iloc[0]
        reverse = self.model.canonicalize_pair_transformations(pd.DataFrame([
            self._row(
                compound_id_from="C2", compound_id_to="C1",
                smiles_from="Clc1ccccc1", smiles_to="CCc1ccccc1",
                endpoint_from=6.0, endpoint_to=5.0, endpoint_delta=-1.0,
                variable_from="Cl[*:1]", variable_to="C[*:1]",
            )
        ]), higher_is_better=True).iloc[0]
        self.assertEqual(forward["transformation_id"], reverse["transformation_id"])
        self.assertEqual(forward["pair_id"], reverse["pair_id"])
        self.assertEqual(forward["normalized_signed_delta"], reverse["normalized_signed_delta"])
        self.assertEqual(forward["fixed_direction_effect"], reverse["fixed_direction_effect"])

    def test_compound_pair_cut_pair_and_pair_transformation_ids_are_separate(self) -> None:
        rows = pd.DataFrame([
            self._row(mmp_id="M1"),
            self._row(
                mmp_id="M2", cut_count=2,
                variable_from="[*:1]CO[*:2]", variable_to="[*:1]N[*:2]",
                exact_core_smiles="CC[*:1].CCC[*:2]",
            ),
            self._row(
                mmp_id="M3", exact_core_smiles="c1cc([*:1])ncc1",
            ),
        ])
        result = self.model.canonicalize_pair_transformations(rows, higher_is_better=True)
        self.assertEqual(result["compound_pair_id"].nunique(), 1)
        self.assertEqual(result["pair_id"].nunique(), 2)
        self.assertEqual(result["pair_transformation_id"].nunique(), 3)

    def test_neutral_boundary_is_strictly_less_than_point_one(self) -> None:
        rows = pd.DataFrame([
            self._row(mmp_id="M1", compound_id_to="C2", endpoint_delta=0.099),
            self._row(mmp_id="M2", compound_id_to="C3", endpoint_delta=0.100),
        ])
        result = self.model.canonicalize_pair_transformations(rows, higher_is_better=True)
        statuses = dict(zip(result["compound_id_to"], result["effect_status"]))
        self.assertEqual(statuses["C2"], "neutral")
        self.assertEqual(statuses["C3"], "supports_fixed_direction")

    def test_lower_is_better_normalized_signed_delta_uses_run_direction(self) -> None:
        result = self.model.canonicalize_pair_transformations(
            pd.DataFrame([self._row(endpoint_from=6.0, endpoint_to=5.0, endpoint_delta=-1.0)]),
            higher_is_better=False,
        ).iloc[0]
        self.assertEqual(result["endpoint_delta"], -1.0)
        self.assertEqual(result["normalized_signed_delta"], 1.0)
        self.assertEqual(result["effect_status"], "supports_fixed_direction")

    def test_two_cut_attachment_order_is_not_erased(self) -> None:
        variable_01, constant_01 = self.model.ordered_fragmentation_structures(
            "*CO*", "*N.*O", "01"
        )
        variable_10, constant_10 = self.model.ordered_fragmentation_structures(
            "*CO*", "*N.*O", "10"
        )
        self.assertNotEqual(variable_01, variable_10)
        self.assertEqual(constant_01, constant_10)
        self.assertIn("[*:1]", variable_01)
        self.assertIn("[*:2]", variable_01)

    def test_graph_welder_handles_branched_two_cut_fragment(self) -> None:
        constant = "N#C[*:1].NC(=O)c1cn([*:2])nc1Nc1ccccc1"
        variable = "O=C(NCC(F)(F)F)[C@H]1CC[C@@](C[*:1])([*:2])CC1"
        expected = "N#CC[C@]1(n2cc(C(N)=O)c(Nc3ccccc3)n2)CC[C@H](C(=O)NCC(F)(F)F)CC1"
        self.assertTrue(self.model._reconstructs_compound(constant, variable, expected))

    def test_direction_consistency_counts_unique_pairs_without_positive_reorientation(self) -> None:
        frame = pd.DataFrame([
            {"target_compound_id": "T", "transformation_family_id": "F", "environment_group_id": "E", "pair_id": "P1", "fixed_direction_effect": 1.0, "compound_id_from": "A", "compound_id_to": "B", "core_id": "K1"},
            {"target_compound_id": "T", "transformation_family_id": "F", "environment_group_id": "E", "pair_id": "P2", "fixed_direction_effect": .8, "compound_id_from": "C", "compound_id_to": "D", "core_id": "K2"},
            {"target_compound_id": "T", "transformation_family_id": "F", "environment_group_id": "E", "pair_id": "P3", "fixed_direction_effect": -.6, "compound_id_from": "E", "compound_id_to": "F", "core_id": "K3"},
        ])
        result = self.evidence._add_group_metrics(frame, .1).iloc[0]
        self.assertEqual(result["supporting_pair_count"], 2)
        self.assertEqual(result["conflicting_pair_count"], 1)
        self.assertAlmostEqual(result["direction_consistency"], 2 / 3)

    def test_disjoint_pair_count_is_exact_not_a_greedy_lower_bound(self) -> None:
        # Sorted greedy matching selects A-B only; the maximum is A-C + B-D.
        self.assertEqual(
            self.model.maximum_disjoint_pair_count([
                ("A", "B"), ("A", "C"), ("B", "D"),
            ]),
            2,
        )

    def test_exact_target_pair_anchors_transferred_direction(self) -> None:
        transferred = pd.DataFrame([
            {"target_compound_id": "T", "transformation_family_id": "F", "environment_group_id": "R2", "pair_id": "P1", "fixed_direction_effect": -.8, "compound_id_from": "A", "compound_id_to": "B", "core_id": "K1"},
            {"target_compound_id": "T", "transformation_family_id": "F", "environment_group_id": "R2", "pair_id": "P2", "fixed_direction_effect": -.7, "compound_id_from": "C", "compound_id_to": "D", "core_id": "K2"},
        ])
        anchor = pd.DataFrame([
            {"pair_id": "DIRECT", "fixed_direction_effect": .5}
        ])
        result = self.evidence._add_group_metrics(
            transferred, .1, {("T", "F"): anchor}
        ).iloc[0]
        self.assertEqual(result["consensus_direction"], "fixed")
        self.assertEqual(result["supporting_pair_count"], 0)
        self.assertEqual(result["conflicting_pair_count"], 2)

    def test_consensus_direction_is_not_shared_between_transformation_families(self) -> None:
        frame = pd.DataFrame([
            {"target_compound_id": "T", "transformation_family_id": "F1", "environment_group_id": "E", "pair_id": "P1", "fixed_direction_effect": .8, "compound_id_from": "A", "compound_id_to": "B", "core_id": "K1"},
            {"target_compound_id": "T", "transformation_family_id": "F2", "environment_group_id": "E", "pair_id": "P2", "fixed_direction_effect": -.7, "compound_id_from": "C", "compound_id_to": "D", "core_id": "K2"},
        ])
        result = self.evidence._add_group_metrics(frame, .1)
        directions = dict(zip(result["transformation_family_id"], result["consensus_direction"]))
        self.assertEqual(directions, {"F1": "fixed", "F2": "reverse"})

    def test_target_registry_deduplicates_target_and_preserves_sources(self) -> None:
        data = pd.DataFrame({"ID": ["T", "X"]})
        parameters = {"targets": [
            {"compound_id": "T", "selection_sources": [
                {"source_type": "analysis_unit_top1", "source_id": "S1"},
                {"source_type": "global_top1", "source_id": "GLOBAL"},
            ]},
            {"compound_id": "T", "selection_sources": [
                {"source_type": "analysis_unit_top1", "source_id": "S1"}
            ]},
        ]}
        registry, sources = self.evidence.normalize_target_registry(parameters, data, "ID")
        self.assertEqual(len(registry), 1)
        self.assertEqual(len(sources), 2)

    def test_direct_target_is_routed_by_signed_target_delta(self) -> None:
        details = self.model.canonicalize_pair_transformations(
            pd.DataFrame([self._row()]), higher_is_better=True
        )
        lookup = pd.DataFrame({
            "compound_id": ["C1", "C2"],
            "smiles": ["CCc1ccccc1", "Clc1ccccc1"],
            "endpoint": [5.0, 6.0],
        }).set_index("compound_id")
        from_side = self.evidence._direct_evidence("C1", details, lookup, .1)[0]
        to_side = self.evidence._direct_evidence("C2", details, lookup, .1)[0]
        self.assertEqual(from_side["target_variable_side_favorable"], "A")
        self.assertEqual(from_side["interpretation_role"], "observed_improvement")
        self.assertEqual(to_side["target_variable_side_favorable"], "B")
        self.assertEqual(to_side["interpretation_role"], "target_explanation")
        self.assertEqual(from_side["target_oriented_delta"], -1.0)
        self.assertEqual(to_side["target_oriented_delta"], 1.0)
        self.assertEqual(from_side["smiles_from"], "CCc1ccccc1")
        self.assertEqual(from_side["smiles_to"], "Clc1ccccc1")
        self.assertEqual(from_side["endpoint_from"], 5.0)
        self.assertEqual(from_side["endpoint_to"], 6.0)

    def test_target_report_direction_is_target_fixed_not_positive_reoriented(self) -> None:
        details = self.model.canonicalize_pair_transformations(
            pd.DataFrame([self._row()]), higher_is_better=True
        )
        lookup = pd.DataFrame({
            "compound_id": ["C1", "C2"],
            "smiles": ["CCc1ccccc1", "Clc1ccccc1"],
            "endpoint": [5.0, 6.0],
        }).set_index("compound_id")
        low_target = self.evidence._direct_evidence("C1", details, lookup, .1)[0]
        high_target = self.evidence._direct_evidence("C2", details, lookup, .1)[0]
        self.assertLess(low_target["target_oriented_delta"], 0)
        self.assertGreater(high_target["target_oriented_delta"], 0)
        self.assertEqual(low_target["pair_favorable_gain"], high_target["pair_favorable_gain"])

    def test_report_only_core_reduction_keeps_maximal_and_incomparable_cores(self) -> None:
        rows = pd.DataFrame([
            {"target_compound_id": "T", "neighbor_compound_id": "N", "cut_count": 1,
             "evidence_id": "small", "exact_core_smiles": "C[*:1]", "pair_favorable_gain": .5},
            {"target_compound_id": "T", "neighbor_compound_id": "N", "cut_count": 1,
             "evidence_id": "large", "exact_core_smiles": "CC[*:1]", "pair_favorable_gain": .5},
            {"target_compound_id": "T", "neighbor_compound_id": "N", "cut_count": 1,
             "evidence_id": "other", "exact_core_smiles": "N[*:1]", "pair_favorable_gain": .5},
        ])
        reduced = self.runner._minimal_direct_rows(rows)
        self.assertEqual(set(reduced["evidence_id"]), {"large", "other"})

    def test_report_core_reduction_ignores_moved_attachment_dummy(self) -> None:
        rows = pd.DataFrame([
            {"target_compound_id": "T", "neighbor_compound_id": "N", "cut_count": 1,
             "evidence_id": "small", "pair_favorable_gain": .5,
             "exact_core_smiles": "N#C[C@H]1CCCC[C@@H]1n1cc(C(N)=O)c([*:1])n1"},
            {"target_compound_id": "T", "neighbor_compound_id": "N", "cut_count": 1,
             "evidence_id": "medium", "pair_favorable_gain": .5,
             "exact_core_smiles": "N#C[C@H]1CCCC[C@@H]1n1cc(C(N)=O)c(N[*:1])n1"},
            {"target_compound_id": "T", "neighbor_compound_id": "N", "cut_count": 1,
             "evidence_id": "large", "pair_favorable_gain": .5,
             "exact_core_smiles": "N#C[C@H]1CCCC[C@@H]1n1cc(C(N)=O)c(Nc2ccc([*:1])cc2)n1"},
        ])
        reduced = self.runner._minimal_direct_rows(rows)
        self.assertEqual(reduced["evidence_id"].tolist(), ["large"])

    def test_two_cut_core_reduction_matches_two_distinct_anchor_components(self) -> None:
        rows = pd.DataFrame([
            {"target_compound_id": "T", "neighbor_compound_id": "N", "cut_count": 2,
             "evidence_id": "small", "pair_favorable_gain": .5,
             "exact_core_smiles": "C[*:1].N[*:2]"},
            {"target_compound_id": "T", "neighbor_compound_id": "N", "cut_count": 2,
             "evidence_id": "large", "pair_favorable_gain": .5,
             "exact_core_smiles": "CC[*:1].CN[*:2]"},
            {"target_compound_id": "T", "neighbor_compound_id": "N", "cut_count": 2,
             "evidence_id": "incomparable", "pair_favorable_gain": .5,
             "exact_core_smiles": "O[*:1].S[*:2]"},
        ])
        reduced = self.runner._minimal_direct_rows(rows)
        self.assertEqual(set(reduced["evidence_id"]), {"large", "incomparable"})

    def test_report_core_reduction_collapses_identical_core_rows_deterministically(self) -> None:
        common = {
            "target_compound_id": "T", "neighbor_compound_id": "N", "cut_count": 1,
            "pair_favorable_gain": .5, "exact_core_smiles": "CC[*:1]",
        }
        rows = pd.DataFrame([
            {**common, "evidence_id": "second"},
            {**common, "evidence_id": "first"},
        ])
        reduced = self.runner._minimal_direct_rows(rows)
        self.assertEqual(reduced["evidence_id"].tolist(), ["first"])

    def test_failed_alignment_still_returns_both_whole_compound_images(self) -> None:
        left, right, status = self.runner._aligned_pair_svg_data(
            "CCO", "c1ccccc1", "N#[*:1]", 180, 120
        )
        self.assertNotEqual(status, "core_aligned")
        self.assertTrue(left.startswith("data:image/svg+xml;base64,"))
        self.assertTrue(right.startswith("data:image/svg+xml;base64,"))

    def test_external_svg_writer_decodes_data_uri_to_xml(self) -> None:
        data_uri = self.runner._molecule_svg_data("CCO", 180, 120)
        svg = self.runner._svg_data_to_text(data_uri)
        self.assertFalse(svg.startswith("data:"))
        self.assertTrue(ET.fromstring(svg).tag.endswith("svg"))

    def test_two_cut_duplicate_of_one_cut_is_excluded_structurally(self) -> None:
        one = self._row()
        two = self._row(
            mmp_id="MMP-2", cut_count=2,
            variable_from="[*:1]C[*:2]", variable_to="[*:1]N[*:2]",
            exact_core_smiles="C[*:1].C[*:2]",
        )
        result = self.model.canonicalize_pair_transformations(
            pd.DataFrame([one, two]), higher_is_better=True
        )
        two_result = result.loc[result["cut_count"].eq(2)].iloc[0]
        self.assertEqual(two_result["two_cut_quality_class"], "2C-X")
        self.assertIn("reducible_to_1cut", two_result["two_cut_quality_reasons"])

    def test_two_cut_requires_four_heavy_atoms_in_each_retained_anchor(self) -> None:
        row = self._row(
            mmp_id="MMP-anchor-floor", compound_id_from="A", compound_id_to="B",
            smiles_from="COCCCC", smiles_to="CNCCCC",
            variable_from="[*:1]O[*:2]", variable_to="[*:1]N[*:2]",
            exact_core_smiles="C[*:1].CCCC[*:2]", cut_count=2,
            core_fraction_from=.8, core_fraction_to=.8,
        )
        result = self.model.canonicalize_pair_transformations(
            pd.DataFrame([row]), higher_is_better=True
        ).iloc[0]
        self.assertEqual(self.model.DEFAULT_TWO_CUT_THRESHOLDS["min_anchor_heavy_atoms"], 4)
        self.assertEqual(result["two_cut_quality_class"], "2C-X")
        self.assertIn(
            "anchor_below_minimum_heavy_atoms", result["two_cut_quality_reasons"]
        )

    def test_parameter_contract_rejects_unknown_and_target_state_in_database_mode(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown"):
            self.runner.validate_parameters({"mode": "target", "surprise": 1})
        with self.assertRaisesRegex(ValueError, "Target-independent"):
            self.runner.validate_parameters({"mode": "database", "targets": [{"compound_id": "X"}]})

    def test_database_separates_one_and_two_cut_and_has_no_target_table(self) -> None:
        one = self.model.canonicalize_pair_transformations(
            pd.DataFrame([self._row()]), higher_is_better=True
        )
        two_source = self._row(
            mmp_id="MMP-2", compound_id_from="C3", compound_id_to="C4",
            smiles_from="CCCOCC", smiles_to="CCCNC",
            variable_from="[*:1]CO[*:2]", variable_to="[*:1]N[*:2]",
            exact_core_smiles="C[*:1].C[*:2]", cut_count=2,
            endpoint_delta=.5, core_fraction_from=.7, core_fraction_to=.7,
        )
        two = self.model.canonicalize_pair_transformations(
            pd.DataFrame([two_source]), higher_is_better=True
        )
        details = pd.concat([one, two], ignore_index=True, sort=False)
        fragments = pd.DataFrame({"fragmentation_id": ["FR1"], "compound_id": ["C1"]})
        compounds = pd.DataFrame({
            "compound_id": ["C1", "C2", "C3", "C4"],
            "smiles": ["CCc1ccccc1", "Clc1ccccc1", "CCCOCC", "CCCNC"],
            "endpoint": [5., 6., 4., 4.5],
        })
        contexts = pd.DataFrame({"mmp_id": ["MMP-1"]})
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "mmp.sqlite"
            self.model.write_canonical_database(
                path, details=details, fragmentations=fragments,
                compounds=compounds, contexts=contexts,
                metadata={"schema_version": "2.0.0", "calculation_version": "0.1.11"},
            )
            with closing(sqlite3.connect(path)) as connection:
                tables = {row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
                )}
                one_count = connection.execute("SELECT count(*) FROM pair_transformations_1cut").fetchone()[0]
                two_count = connection.execute("SELECT count(*) FROM pair_transformations_2cut").fetchone()[0]
                pair_columns = {row[1] for row in connection.execute("PRAGMA table_info(pairs)")}
                transformation_columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(pair_transformations)")
                }
        self.assertNotIn("targets", tables)
        self.assertEqual((one_count, two_count), (1, 1))
        self.assertIn("cut_count", pair_columns)
        self.assertIn("pair_transformation_id", transformation_columns)

    def test_runtime_standard_target_selection_includes_global_and_unit_top1(self) -> None:
        path = MODULES / "tools" / "runtime_controller.py"
        spec = importlib.util.spec_from_file_location("runtime_0111_mmp_test", path)
        runtime = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(runtime)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runtime").mkdir()
            dataset = root / "input.csv"
            dataset.write_text(
                "ID,SMILES,EP\nA,CC,5\nB,CCC,9\nC,CCCC,7\n", encoding="utf-8"
            )
            (root / "runtime" / "analysis_unit_membership.csv").write_text(
                "compound_id,analysis_unit_id,membership_value\nA,S1,True\nC,S1,True\nA,S2,True\nB,S2,True\n",
                encoding="utf-8",
            )
            targets = runtime.standard_mmp_targets(root, {
                "input_path": str(dataset),
                "columns": {"compound_id": "ID", "endpoint": "EP"},
                "higher_is_better": True,
            })
        by_id = {row["compound_id"]: row["selection_sources"] for row in targets}
        self.assertIn("B", by_id)
        self.assertIn({"source_type": "global_top1", "source_id": "GLOBAL"}, by_id["B"])
        self.assertIn({"source_type": "analysis_unit_top1", "source_id": "S1"}, by_id["C"])

    def test_interactive_template_has_fixed_workspace_contract(self) -> None:
        template = (TEMPLATES / "mmp_target_workspace_template.html").read_text(encoding="utf-8")
        self.assertIn('data-template-id="A008-target-workspace"', template)
        self.assertIn('data-template-version="0.1.11"', template)
        for view in ("map", "transformation", "direction", "core", "cuts", "data", "guide"):
            self.assertIn(f'data-view="{view}"', template)
        for scope in ("all", "direct", "transferred"):
            self.assertIn(f'data-transformation-scope="{scope}"', template)
        for direction in ("positive", "negative"):
            self.assertIn(f'data-direction="{direction}"', template)
        for core_type in ("direct", "transferred"):
            self.assertIn(f'data-core-type="{core_type}"', template)
        for cut_count in ("1", "2"):
            self.assertIn(f'data-cut-view="{cut_count}"', template)
        for quality_class in ("2C-A", "2C-B", "2C-X"):
            self.assertIn(quality_class, template)
        self.assertIn("ΔN2T", template)
        self.assertIn("Align ×", template)
        self.assertIn("heavy atom 4", template)
        self.assertNotIn("Targetを常に生成物側に表示", template)
        self.assertNotIn("Target基準Δ", template)
        self.assertNotIn("この読み方", template)
        self.assertIn("Direct MMPあり", template)
        self.assertIn("Transferredのみ", template)
        self.assertNotIn('data-core-type="exact"', template)
        self.assertIn('const key=`${r.transformation_family_id}|${r.cut_count}`', template)
        self.assertIn("Core横断の観測", template)
        self.assertIn("global cut/quality filters across data views", (SCRIPTS / "mmp_0111_browser_audit.py").read_text(encoding="utf-8"))
        self.assertIn("hasNumber", template)
        self.assertIn("clamp(650px,58vw,920px)", template)
        self.assertNotIn("Favorable Δ", template)
        self.assertIn('data-kind="neighbor"', (SCRIPTS / "mmp_0111_runner.py").read_text(encoding="utf-8"))
        self.assertNotIn("screenshot", (SCRIPTS / "mmp_0111_browser_audit.py").read_text(encoding="utf-8").lower())

    def test_six_neighbors_are_accounted_by_one_map_portal(self) -> None:
        rows = []
        for index in range(6):
            rows.append({
                "connection_scope": "direct", "cut_count": 1,
                "two_cut_quality_class": "not_applicable",
                "target_compound_id": "T", "neighbor_compound_id": f"N{index}",
                "evidence_id": f"E{index}", "exact_core_smiles": "c1ccc([*:1])cc1",
                "core_id": "K", "target_oriented_delta": index - 2.5,
                "pair_favorable_gain": abs(index - 2.5), "pair_id": f"P{index}",
                "interpretation_role": "target_explanation",
            })
        interactive, static, _ = self.runner._relationship_map(
            "T", "Cc1ccccc1", 8.0, pd.DataFrame(rows), cut_count=1
        )
        self.assertEqual(interactive.count('data-kind="neighbor-group"'), 1)
        self.assertEqual(interactive.count('data-kind="neighbor"'), 0)
        self.assertIn('data-neighbor-count="6"', static)
        self.assertIn("6 Neighbor", static)
        self.assertIn('width="140" height="62"', static)

    def test_mixed_sign_insights_use_a_representative_with_the_same_sign(self) -> None:
        common = {
            "portal_core_id": "PC1", "transformation_family_id": "TF1",
            "cut_count": 1, "connection_scope": "direct",
            "neighbor_compound_id": "N", "core_image": "core.svg",
            "variable_from": "C[*:1]", "variable_to": "Cl[*:1]",
            "target_variable_side_fixed": "B", "target_current_variable": "Cl[*:1]",
            "counterpart_fragment_image": "before.svg",
            "target_fragment_image": "after.svg",
        }
        records = [
            {**common, "evidence_id": "positive", "target_oriented_delta": 0.8},
            {**common, "evidence_id": "negative", "target_oriented_delta": -0.6},
        ]
        _, insights = self.runner._report_indexes(records)
        by_reading = {row["reading"]: row for row in insights}
        self.assertEqual(by_reading["support"]["representative_evidence_id"], "positive")
        self.assertGreater(by_reading["support"]["median_target_delta"], 0)
        self.assertEqual(by_reading["improvement"]["representative_evidence_id"], "negative")
        self.assertLess(by_reading["improvement"]["median_target_delta"], 0)

    def test_a009_places_mmp_after_primary_analysis_sections(self) -> None:
        detail = (ROOT / ".claude" / "skills" / "cs-analysis-series-report" / "templates" / "series_detail_template.html").read_text(encoding="utf-8")
        summary = (ROOT / ".claude" / "skills" / "cs-analysis-series-report" / "templates" / "standard_summary_template.html").read_text(encoding="utf-8")
        self.assertGreater(detail.index("$mmp_navigation"), detail.index('data-report-section="a007"'))
        self.assertGreater(summary.index("$mmp_global_map"), summary.index('data-report-section="detail-reports"'))

    def test_relationship_map_is_self_contained_and_cards_do_not_overlap(self) -> None:
        rows = []
        core_smiles = [
            "c1ccc([*:1])cc1", "c1ccncc1[*:1]", "C1CCCCC1[*:1]",
            "c1ncccc1[*:1]", "c1ccc2ccccc2c1[*:1]",
        ]
        for core_index, core in enumerate(core_smiles):
            for neighbor_index in range(3):
                rows.append({
                    "connection_scope": "direct", "cut_count": 1,
                    "two_cut_quality_class": "not_applicable",
                    "target_compound_id": "T",
                    "neighbor_compound_id": f"N{core_index}{neighbor_index}",
                    "evidence_id": f"E{core_index}{neighbor_index}",
                    "exact_core_smiles": core, "core_id": f"K{core_index}",
                    "pair_favorable_gain": float(3 - neighbor_index),
                    "pair_id": f"P{core_index}{neighbor_index}",
                    "compound_pair_id": f"CP{core_index}{neighbor_index}",
                    "interpretation_role": "target_explanation",
                    "consensus_direction": "fixed",
                    "variable_from": "C[*:1]", "variable_to": "Cl[*:1]",
                    "target_variable_side_favorable": "B",
                    "neighbor_endpoint": 7.0 + neighbor_index,
                })
        _, static, _ = self.runner._relationship_map(
            "T", "Cc1ccccc1", 8.0, pd.DataFrame(rows), cut_count=1
        )
        self.assertIn('xmlns="http://www.w3.org/2000/svg"', static)
        self.assertIn(".neighbor-box{stroke:#e07a24}", static)
        self.assertIn("stroke-dasharray:5 4", static)
        rectangles = [tuple(map(float, match)) for match in re.findall(
            r'<rect class="node-box [^"]+" x="([0-9.]+)" y="([0-9.]+)"[^>]*width="([0-9.]+)" height="([0-9.]+)"',
            static,
        )]
        self.assertEqual(len(rectangles), 21)  # Target + 5 Core + 15 Neighbor
        for index, (ax, ay, aw, ah) in enumerate(rectangles):
            for bx, by, bw, bh in rectangles[index + 1:]:
                overlap_width = min(ax + aw, bx + bw) - max(ax, bx)
                overlap_height = min(ay + ah, by + bh) - max(ay, by)
                self.assertFalse(
                    overlap_width > .5 and overlap_height > .5,
                    f"Map cards overlap: {(ax, ay, aw, ah)} vs {(bx, by, bw, bh)}",
                )

    def test_formal_5000_compound_input_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "input.csv"
            pd.DataFrame({
                "ID": [f"C{index:05d}" for index in range(5000)],
                "SMILES": ["CC"] * 5000,
                "EP": [1.0] * 5000,
            }).to_csv(path, index=False)
            valid, coverage, _ = self.engine.load_input(path, "ID", "SMILES", "EP", 5000)
            self.assertEqual((len(valid), len(coverage)), (5000, 5000))
            overflow = Path(temporary) / "overflow.csv"
            pd.DataFrame({
                "ID": [f"C{index:05d}" for index in range(5001)],
                "SMILES": ["CC"] * 5001,
                "EP": [1.0] * 5001,
            }).to_csv(overflow, index=False)
            with self.assertRaisesRegex(ValueError, "maximum is 5000"):
                self.engine.load_input(overflow, "ID", "SMILES", "EP", 5000)


if __name__ == "__main__":
    unittest.main()
