from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / ".claude" / "skills" / "cs-analysis-interpret-mmp" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
SPEC = importlib.util.spec_from_file_location("mmp_interpretation_run", SCRIPT_DIR / "run.py")
assert SPEC and SPEC.loader
MMP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MMP)


class ReadOnlyMmpInterpretation(unittest.TestCase):
    def build_run(self, root: Path) -> None:
        (root / "runtime").mkdir(parents=True)
        (root / "analysis" / "N000001").mkdir(parents=True)
        control = {
            "conductor_version": "0.1.6",
            "round_state": "AWAITING_HUMAN_REVIEW",
            "active_round_id": "RND0001",
            "lease": {"owner_id": None, "expires_at": None},
            "run": {"run_id": "RUN-MMP-TEST", "endpoint": "pIC50", "higher_is_better": True},
        }
        nodes = [
            {
                "node_id": "N000001", "kind": "analysis", "capability_id": "A014", "status": "succeeded",
                "parameters": {"role": "global-build"}, "output_ref": str(root / "analysis" / "N000001"),
                "created_in_round": "RND0001", "assigned_round": "RND0001",
            },
            {
                "node_id": "N000002", "kind": "clustering", "capability_id": "C005", "status": "succeeded",
                "parameters": {}, "output_ref": str(root / "clustering" / "N000002"),
                "created_in_round": "RND0001", "assigned_round": "RND0001",
            },
        ]
        snapshot = {"nodes": nodes, "rounds": {"RND0001": {"state": "AWAITING_HUMAN_REVIEW"}}}
        (root / "conductor_control.json").write_text(json.dumps(control), encoding="utf-8")
        (root / "runtime" / "dag_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
        compounds = [f"CPD{i:03d}" for i in range(1, 13)]
        membership = pd.DataFrame({
            "compound_id": compounds,
            "C000001": [i < 6 for i in range(12)],
            "C000002": [i >= 6 for i in range(12)],
        })
        membership.to_csv(root / "runtime" / "cluster_membership.csv", index=False)
        registry = [
            {"cluster_id": "C000001", "source_node_id": "N000002", "clustering_capability_id": "C005", "source_description_capability_ids": ["D001"], "compound_count": 6, "status": "active"},
            {"cluster_id": "C000002", "source_node_id": "N000002", "clustering_capability_id": "C005", "source_description_capability_ids": ["D001"], "compound_count": 6, "status": "active"},
        ]
        (root / "runtime" / "cluster_registry.jsonl").write_text("".join(json.dumps(row) + "\n" for row in registry), encoding="utf-8")
        self.build_database(root / "analysis" / "N000001" / "mmp_database.sqlite", compounds)

    def build_database(self, path: Path, compounds: list[str]) -> None:
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value_json TEXT NOT NULL)")
            connection.executemany("INSERT INTO metadata VALUES (?, ?)", [("endpoint_column", '"pIC50"'), ("higher_is_better", "true")])
            connection.execute("CREATE TABLE compounds (compound_key INTEGER, compound_id TEXT, smiles TEXT, endpoint REAL, valid_smiles INTEGER, heavy_atoms INTEGER, endpoint_available INTEGER, exclusion_reason TEXT)")
            connection.executemany("INSERT INTO compounds VALUES (?, ?, ?, ?, 1, 3, 1, '')", [(i + 1, compound, "CCO", float(i)) for i, compound in enumerate(compounds)])
            connection.execute("CREATE TABLE transforms (transform_key INTEGER, transform_id TEXT, variable_from TEXT, variable_to TEXT, transform_smirks TEXT, cut_count INTEGER)")
            connection.execute("INSERT INTO transforms VALUES (1, 'TRF-TEST', '[*:1]C', '[*:1]N', '[*:1]C>>[*:1]N', 1)")
            connection.execute("CREATE TABLE cores (core_key INTEGER, core_id TEXT, exact_core_smiles TEXT, core_heavy_atoms INTEGER, core_molecular_weight REAL)")
            connection.executemany("INSERT INTO cores VALUES (?, ?, 'c1ccccc1', 6, 78.0)", [(1, "CORE-A"), (2, "CORE-B")])
            connection.execute("CREATE TABLE mmp_pairs (pair_key INTEGER, mmp_id TEXT, endpoint_delta REAL, favorable_delta REAL, core_fraction_from REAL, core_fraction_to REAL, native_rule_id INTEGER, endpoint_missing INTEGER, quality_flags TEXT, compound_from_key INTEGER, compound_to_key INTEGER, transform_key INTEGER, core_key INTEGER)")
            effects = [1.0, 1.1, .9, -1.0, -1.1, -.9]
            pairs = [(1, 2), (3, 4), (5, 6), (7, 8), (9, 10), (11, 12)]
            connection.executemany(
                "INSERT INTO mmp_pairs VALUES (?, ?, ?, ?, .7, .7, ?, 0, '', ?, ?, 1, ?)",
                [(i + 1, f"MMP-{i + 1}", effect, effect, i + 1, pair[0], pair[1], 1 if i < 3 else 2) for i, (effect, pair) in enumerate(zip(effects, pairs))],
            )
            connection.commit()

    def test_prepare_finalize_and_verify_preserve_canonical_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "run"
            self.build_run(root)
            before = MMP.run_inventory(root)
            args = argparse.Namespace(
                run_root=str(root), round_id="RND0001", mmp_node_id=None,
                clustering_node_id=[], cluster_id=[], transform_id=[],
                min_local_pairs=2, min_outside_pairs=2, explicit_request=True,
            )
            self.assertEqual(0, MMP.prepare(args))
            request_dir = next((root / "mmp_interpretation").iterdir())
            variance = pd.read_csv(request_dir / "candidate_variance_collapse.csv")
            self.assertEqual(1, len(variance))
            self.assertGreater(float(variance.iloc[0]["dispersion_reduction"]), 0)
            self.assertEqual(before, MMP.run_inventory(root))
            self.assertEqual(0, MMP.finalize(argparse.Namespace(request_dir=str(request_dir), overwrite=False)))
            self.assertEqual(0, MMP.verify(argparse.Namespace(request_dir=str(request_dir))))
            self.assertTrue((request_dir / "mmp_interpretation.html").is_file())
            self.assertEqual(before, MMP.run_inventory(root))

    def test_negative_result_tables_keep_stable_csv_headers(self) -> None:
        details = pd.DataFrame(columns=[
            "mmp_id", "compound_id_from", "compound_id_to", "favorable_delta",
            "transform_id", "transform_smirks", "core_id",
        ])
        matrix = pd.DataFrame({"compound_id": [f"CPD{i:03d}" for i in range(5)], "C000001": [True] * 5})
        registry = [{
            "cluster_id": "C000001", "source_node_id": "N000002",
            "clustering_capability_id": "C005", "source_description_capability_ids": ["D001"],
        }]
        tables = MMP.derive_tables(details, matrix, "compound_id", registry, 5, 5)
        for key in ("cluster_transform_summary", "clustering_transform_summary", "variance_collapse", "cluster_specific", "direction_reversal"):
            self.assertGreater(len(tables[key].columns), 0, key)

    def test_low_support_cluster_keeps_screening_without_outside_detail(self) -> None:
        details = pd.DataFrame([
            {"mmp_id": "M1", "compound_id_from": "CPD001", "compound_id_to": "CPD002", "favorable_delta": 1.0, "transform_id": "T1", "transform_smirks": "A>>B", "core_id": "K1"},
            {"mmp_id": "M2", "compound_id_from": "CPD006", "compound_id_to": "CPD007", "favorable_delta": -1.0, "transform_id": "T1", "transform_smirks": "A>>B", "core_id": "K2"},
        ])
        matrix = pd.DataFrame({
            "compound_id": [f"CPD{i:03d}" for i in range(1, 11)],
            "C000001": [i <= 5 for i in range(1, 11)],
            "C000002": [i > 5 for i in range(1, 11)],
            "C000003": [False] * 10,
        })
        registry = [
            {"cluster_id": cluster_id, "source_node_id": "N000002", "clustering_capability_id": "C005", "source_description_capability_ids": ["D001"]}
            for cluster_id in ("C000001", "C000002", "C000003")
        ]
        tables = MMP.derive_tables(details, matrix, "compound_id", registry, 2, 2)
        screening = tables["cluster_screening"].set_index("cluster_id")
        self.assertEqual(0, int(screening.loc["C000003", "within_pair_count"]))
        self.assertEqual(0, int(screening.loc["C000001", "eligible_transform_count"]))
        comparison = tables["cluster_transform_summary"]
        self.assertFalse(bool(comparison["eligible_local"].any()))
        self.assertTrue(comparison["outside_endpoint_pair_count"].isna().all())
        self.assertEqual({"not_evaluated_low_support"}, set(comparison["core_context_flag"]))

    def test_overlapping_clusters_assign_pair_to_membership_intersection(self) -> None:
        details = pd.DataFrame([
            {"mmp_id": "M1", "compound_id_from": "CPD001", "compound_id_to": "CPD002", "favorable_delta": 1.0, "transform_id": "T1", "transform_smirks": "A>>B", "core_id": "K1"},
            {"mmp_id": "M2", "compound_id_from": "CPD003", "compound_id_to": "CPD004", "favorable_delta": 2.0, "transform_id": "T1", "transform_smirks": "A>>B", "core_id": "K1"},
        ])
        matrix = pd.DataFrame({
            "compound_id": [f"CPD{i:03d}" for i in range(1, 7)],
            "C000001": [True, True, True, True, False, False],
            "C000002": [True, True, False, False, True, True],
        })
        registry = [
            {"cluster_id": cluster_id, "source_node_id": "N000002", "clustering_capability_id": "C002", "source_description_capability_ids": []}
            for cluster_id in ("C000001", "C000002")
        ]
        tables = MMP.derive_tables(details, matrix, "compound_id", registry, 1, 1)
        screening = tables["cluster_screening"].set_index("cluster_id")
        self.assertTrue(bool(screening["overlap_detected"].all()))
        self.assertEqual(2, int(screening.loc["C000001", "within_pair_count"]))
        self.assertEqual(1, int(screening.loc["C000002", "within_pair_count"]))
        method = tables["clustering_transform_summary"]
        self.assertFalse(bool(method["variance_comparison_eligible"].any()))

    def test_older_mmp_database_requires_explicit_node_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "run"
            self.build_run(root)
            snapshot = MMP.load_json(root / "runtime" / "dag_snapshot.json")
            node = snapshot["nodes"][0]
            node["assigned_round"] = "RND0000"
            node["created_in_round"] = "RND0000"
            with self.assertRaisesRegex(RuntimeError, "No successful Global A014 Node was produced"):
                MMP.select_global_mmp(root, snapshot, "RND0001", None)
            selected, database = MMP.select_global_mmp(root, snapshot, "RND0001", "N000001")
            self.assertEqual("N000001", selected["node_id"])
            self.assertTrue(database.is_file())


if __name__ == "__main__":
    unittest.main()
