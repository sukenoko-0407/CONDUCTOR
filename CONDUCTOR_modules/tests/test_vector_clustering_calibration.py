from __future__ import annotations

import argparse
import json
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / ".claude" / "skills" / "cs-compute-clustering-vector-butina" / "scripts" / "run.py"
SPEC = importlib.util.spec_from_file_location("vector_clustering", RUNNER)
VECTOR = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(VECTOR)


def arguments(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "parameter_mode": "auto",
        "min_cluster_size": 5,
        "distance_cutoff": None,
        "similarity_threshold": None,
        "distance_threshold": None,
        "n_clusters": None,
        "eps": None,
        "min_samples": 5,
        "resolution": 1.0,
        "random_seed": 61453,
        "n_neighbors": None,
        "graph_mode": "mutual-knn",
    }
    values.update(overrides)
    return argparse.Namespace(**values)


@unittest.skipUnless(importlib.util.find_spec("rdkit") and importlib.util.find_spec("networkx"), "Run in the Skill Pixi environment with RDKit and NetworkX")
class VectorClusteringCalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        rng = np.random.default_rng(61453)
        vectors = np.vstack(
            [
                rng.normal(-3.0, 0.30, size=(12, 48)),
                rng.normal(0.0, 0.30, size=(12, 48)),
                rng.normal(3.0, 0.30, size=(12, 48)),
            ]
        )
        from sklearn.metrics import pairwise_distances

        cls.distance = pairwise_distances(vectors, metric="euclidean")
        cls.profile = VECTOR.distance_profile(
            cls.distance, "euclidean", 48, 48, {}, len(vectors), len(vectors), 0
        )

    def test_auto_methods_return_a_non_degenerate_partition(self) -> None:
        for method in ("butina", "hierarchical", "dbscan", "louvain", "leiden", "connected_components"):
            with self.subTest(method=method):
                if method == "leiden" and not (importlib.util.find_spec("igraph") and importlib.util.find_spec("leidenalg")):
                    self.skipTest("Leiden is verified in its Skill Pixi environment")
                labels, selection = VECTOR.vector_partition(
                    self.distance,
                    arguments(),
                    method,
                    "euclidean",
                    self.profile,
                )
                self.assertEqual("selected", selection["selection_status"])
                clusters, reasons = VECTOR.labeled_clusters_with_reasons(
                    [f"C{i:03d}" for i in range(len(labels))], labels, 5, selection["selection_status"]
                )
                self.assertGreaterEqual(len(clusters), 2)
                self.assertGreaterEqual(sum(len(members) for members in clusters.values()), 24)
                self.assertTrue(set(reasons.values()).issubset({"singleton_cluster", "filtered_small_cluster"}))

    def test_fixed_butina_uses_native_distance(self) -> None:
        labels, selection = VECTOR.vector_partition(
            self.distance,
            arguments(parameter_mode="fixed", distance_cutoff=4.0),
            "butina",
            "euclidean",
            self.profile,
        )
        self.assertEqual("selected", selection["selection_status"])
        self.assertEqual(4.0, selection["selected_parameters"]["distance_cutoff"])
        self.assertEqual(3, len(set(int(value) for value in labels if int(value) >= 0)))

    def test_no_usable_partition_is_explicit(self) -> None:
        labels = np.zeros(10, dtype=int)
        candidates = [VECTOR.candidate_record({"distance_cutoff": 100.0}, labels, np.zeros((10, 10)), 5)]
        selected, status, flags = VECTOR.select_candidate(candidates, {"weak_distance_contrast": False}, "auto")
        self.assertIsNotNone(selected)
        self.assertEqual("no_usable_partition", status)
        self.assertIn("collapsed", flags)
        clusters, reasons = VECTOR.labeled_clusters_with_reasons(
            [f"C{i:03d}" for i in range(10)], np.full(10, -1), 5, status
        )
        self.assertFalse(clusters)
        self.assertEqual({"no_usable_partition"}, set(reasons.values()))

    def test_zero_and_duplicate_vectors_are_retained(self) -> None:
        import pandas as pd

        frame = pd.DataFrame(
            {
                "compound_id": ["C001", "C002", "C003"],
                "f1": [0.0, 0.0, 1.0],
                "f2": [0.0, 0.0, 0.0],
            }
        )
        args = argparse.Namespace(
            description_result=None,
            value_semantics="sparse_count",
            conductor=False,
            input_representation="D004",
            metric="cosine",
        )
        positions, distance, _features, metric, profile = VECTOR.vector_distances(frame, args)
        self.assertEqual([0, 1, 2], positions)
        self.assertEqual("cosine", metric)
        self.assertEqual(2, profile["zero_vector_count"])
        self.assertEqual(0.0, distance[0, 1])
        self.assertEqual(1.0, distance[0, 2])

    def test_manifest_metric_overrides_value_pattern_heuristics(self) -> None:
        import pandas as pd

        values = pd.DataFrame({"svd_1": [0.0, 1.0], "svd_2": [1.0, 0.0]})
        args = argparse.Namespace(input_representation="D011", metric="auto")
        metric = VECTOR.resolve_vector_metric(
            values,
            list(values.columns),
            args,
            {"capability_id": "D011", "value_semantics": "dense_embedding", "natural_metric": "cosine"},
        )
        self.assertEqual("cosine", metric)

    def test_runtime_description_result_is_the_only_conductor_vector_contract(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            payload = Path(folder) / "features.csv"
            payload.write_text("compound_id,f1,f2\nC001,1,0\n", encoding="utf-8")
            result_path = Path(folder) / "result.json"
            result_path.write_text(
                json.dumps(
                    {
                        "document_type": "description_result",
                        "schema_version": "1.0.0",
                        "node_id": "N000001",
                        "capability_id": "D011",
                        "payload": "features.csv",
                        "row_count": 1,
                        "feature_count": 2,
                        "value_semantics": "dense_embedding",
                        "natural_metric": "cosine",
                        "feature_columns": ["f1", "f2"],
                        "quality_flags": [],
                        "created_at": "2026-01-01T00:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )
            args = argparse.Namespace(
                description_result=str(result_path), value_semantics=None, conductor=True,
                input=str(payload), input_representation="D011", metric="auto",
            )
            parsed = VECTOR.description_contract(args)
            self.assertEqual("1.0.0", parsed["schema_version"])
            self.assertEqual("cosine", parsed["natural_metric"])

    def test_unknown_or_incomplete_description_contract_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            payload = Path(folder) / "features.csv"
            payload.write_text("compound_id,f1\nC001,1\n", encoding="utf-8")
            result_path = Path(folder) / "result.json"
            result_path.write_text(
                json.dumps({"schema_version": "1.0.0", "capability_id": "D001"}),
                encoding="utf-8",
            )
            args = argparse.Namespace(
                description_result=str(result_path), value_semantics=None, conductor=True,
                input=str(payload), input_representation="D001", metric="auto",
            )
            with self.assertRaises(Exception):
                VECTOR.description_contract(args)

    def test_artifact_manifest_is_rejected_as_a_downstream_contract(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            payload = Path(folder) / "features.csv"
            payload.write_text("compound_id,f1\nC001,1\n", encoding="utf-8")
            manifest = Path(folder) / "description_manifest.json"
            manifest.write_text(json.dumps({"schema_version": "2.0.0", "artifact_stage": "description", "capability_id": "D001"}), encoding="utf-8")
            args = argparse.Namespace(description_result=str(manifest), value_semantics=None, conductor=True, input=str(payload), input_representation="D001", metric="auto")
            with self.assertRaises(Exception):
                VECTOR.description_contract(args)

    def test_endpoint_column_does_not_change_distances_when_manifest_binds_features(self) -> None:
        import pandas as pd

        base = pd.DataFrame(
            {
                "compound_id": [f"C{i:03d}" for i in range(6)],
                "f1": [0.0, 0.2, 0.4, 3.0, 3.2, 3.4],
                "f2": [1.0, 1.1, 0.9, 4.0, 3.9, 4.1],
                "pIC50": [1, 2, 3, 4, 5, 6],
            }
        )
        with tempfile.TemporaryDirectory() as folder:
            result_path = Path(folder) / "result.json"
            result_path.write_text(
                json.dumps({"document_type": "description_result", "schema_version": "1.0.0", "node_id": "N000001", "capability_id": "D001", "payload": "description.csv", "row_count": 6, "feature_count": 2, "value_semantics": "dense_continuous", "natural_metric": "euclidean", "feature_columns": ["f1", "f2"], "quality_flags": [], "created_at": "2026-01-01T00:00:00+00:00"}),
                encoding="utf-8",
            )
            vector_path = Path(folder) / "description.csv"
            base.to_csv(vector_path, index=False)
            args = argparse.Namespace(description_result=str(result_path), value_semantics=None, conductor=True, input=str(vector_path), input_representation="D001", metric="auto")
            first = VECTOR.vector_distances(base, args)[1]
            changed = base.copy()
            changed["pIC50"] = [600, -50, 900, 2, 1000, -800]
            second = VECTOR.vector_distances(changed, args)[1]
            np.testing.assert_allclose(first, second)

    def test_cli_general_and_conductor_output_boundaries(self) -> None:
        import pandas as pd

        with tempfile.TemporaryDirectory() as folder:
            temporary = Path(folder)
            columns = [f"f{i:03d}" for i in range(48)]
            table = pd.DataFrame(self.vectors if hasattr(self, "vectors") else np.zeros((0, 48)), columns=columns)
            if table.empty:
                rng = np.random.default_rng(61453)
                table = pd.DataFrame(
                    np.vstack([rng.normal(-3, .3, (12, 48)), rng.normal(0, .3, (12, 48)), rng.normal(3, .3, (12, 48))]),
                    columns=columns,
                )
            table.insert(0, "compound_id", [f"C{i:03d}" for i in range(len(table))])
            vector_path = temporary / "description.csv"
            table.to_csv(vector_path, index=False)
            result_path = temporary / "result.json"
            result_path.write_text(
                json.dumps({"document_type": "description_result", "schema_version": "1.0.0", "node_id": "N000010", "capability_id": "D001", "payload": "description.csv", "row_count": len(table), "feature_count": len(columns), "value_semantics": "dense_continuous", "natural_metric": "euclidean", "feature_columns": columns, "quality_flags": [], "created_at": "2026-01-01T00:00:00+00:00"}),
                encoding="utf-8",
            )
            general = temporary / "general"
            completed = subprocess.run(
                [sys.executable, str(RUNNER), "--input", str(vector_path), "--input-representation", "D001", "--value-semantics", "dense_continuous", "--metric", "euclidean", "--output-dir", str(general)],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            self.assertTrue((general / "cluster_membership.csv").is_file())
            self.assertTrue((general / "clustering_diagnostics.csv").is_file())
            self.assertFalse((general / "clustering_manifest.json").exists())
            conductor = temporary / "conductor"
            completed = subprocess.run(
                [sys.executable, str(RUNNER), "--input", str(vector_path), "--description-result", str(result_path), "--input-representation", "D001", "--conductor", "--project", "unit", "--run-id", "run", "--round-id", "RND0002", "--node-id", "N000001", "--attempt-id", "ATT0001", "--output-dir", str(conductor)],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            self.assertTrue((conductor / "distance_profile.json").is_file())
            self.assertTrue((conductor / "execution_event.json").is_file())
            manifest = json.loads((conductor / "clustering_manifest.json").read_text(encoding="utf-8"))
            self.assertIn(manifest["selection_status"], {"selected", "no_usable_partition"})


if __name__ == "__main__":
    unittest.main()
