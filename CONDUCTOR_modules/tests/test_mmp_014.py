from __future__ import annotations

import importlib.util
import json
import sqlite3
from contextlib import closing
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / ".claude" / "skills" / "cs-analysis-matched-molecular-pairs"
RUNNER = SKILL / "scripts" / "run.py"
RENDERER = SKILL / "scripts" / "render.py"
FIXTURE = ROOT / "CONDUCTOR_modules" / "tests" / "data" / "small_sar.csv"
MEMBERSHIP = ROOT / "CONDUCTOR_modules" / "tests" / "data" / "mmp_membership.csv"
NO_PAIRS = ROOT / "CONDUCTOR_modules" / "tests" / "data" / "mmp_no_pairs.csv"


class MatchedMolecularPairs014(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            import mmpdblib  # noqa: F401
        except ImportError as exc:
            raise unittest.SkipTest(f"mmpdb integration dependency is unavailable: {exc}")

    def command(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(RUNNER), *arguments], cwd=ROOT, text=True, capture_output=True, check=True)

    def test_global_database_csv_parquet_and_context_counting_are_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "global"
            self.command(
                "global-build", "--input", str(FIXTURE), "--id-column", "compound_id",
                "--smiles-column", "smiles", "--endpoint-column", "pIC50",
                "--higher-is-better", "true", "--min-core-heavy-atoms", "1",
                "--extended-min-core-fraction", "0.1", "--primary-min-core-fraction", "0.2",
                "--available-cpu-cores", "2", "--output-dir", str(output),
            )
            csv = pd.read_csv(output / "mmp_pair_detail.csv")
            parquet = pd.read_parquet(output / "mmp_pair_detail.parquet")
            with closing(sqlite3.connect(output / "mmp_database.sqlite")) as connection:
                database_count = connection.execute("SELECT COUNT(*) FROM mmp_pairs").fetchone()[0]
                context_count = connection.execute("SELECT COUNT(*) FROM mmp_contexts").fetchone()[0]
            self.assertGreater(len(csv), 0)
            self.assertEqual(len(csv), len(parquet))
            self.assertEqual(len(csv), database_count)
            self.assertGreaterEqual(context_count, len(csv))
            self.assertEqual(len(csv), csv["mmp_id"].nunique())
            self.assertTrue({"exact_core_smiles", "transform_smirks", "favorable_delta", "environment_radius_0"} <= set(csv.columns))
            result = json.loads((output / "mmp_result.json").read_text(encoding="utf-8"))
            self.assertFalse(result["negative_result"])
            report = (output / "operator_report.html").read_text(encoding="utf-8")
            for heading in (
                "複数Coreで再現する置換効果", "Exact Core依存性と符号反転", "Environment依存性",
                "Global対Cluster-local", "大きな個別Pair変化", "SAR hotspot Core", "反証・矛盾",
                "CoverageとNegative Result", "制約と反証確認", "成果物",
            ):
                self.assertIn(heading, report)
            self.assertIn("<svg", report)
            self.assertNotIn("<script src=", report)
            rerendered = Path(temporary) / "rerendered.html"
            subprocess.run([sys.executable, str(RENDERER), "--result-dir", str(output), "--output", str(rerendered)], cwd=ROOT, check=True)
            self.assertIn("pIC50", rerendered.read_text(encoding="utf-8"))

            reversed_input = Path(temporary) / "small_sar_reversed.csv"
            pd.read_csv(FIXTURE).iloc[::-1].to_csv(reversed_input, index=False)
            reversed_output = Path(temporary) / "global-reversed"
            self.command(
                "global-build", "--input", str(reversed_input), "--id-column", "compound_id",
                "--smiles-column", "smiles", "--endpoint-column", "pIC50",
                "--higher-is-better", "true", "--min-core-heavy-atoms", "1",
                "--extended-min-core-fraction", "0.1", "--primary-min-core-fraction", "0.2",
                "--available-cpu-cores", "2", "--output-dir", str(reversed_output),
            )
            reversed_csv = pd.read_csv(reversed_output / "mmp_pair_detail.csv")
            identity = ["compound_id_from", "compound_id_to", "variable_from", "variable_to", "exact_core_smiles", "mmp_id"]
            pd.testing.assert_frame_equal(
                csv[identity].sort_values(identity[:-1]).reset_index(drop=True),
                reversed_csv[identity].sort_values(identity[:-1]).reset_index(drop=True),
                check_dtype=False,
            )

    def test_local_roles_query_global_database_without_modifying_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            global_output = root / "global"
            self.command(
                "global-build", "--input", str(FIXTURE), "--id-column", "compound_id",
                "--smiles-column", "smiles", "--endpoint-column", "pIC50",
                "--higher-is-better", "true", "--min-core-heavy-atoms", "1",
                "--extended-core-fraction", "0.1", "--primary-core-fraction", "0.2",
                "--available-cpu-cores", "2", "--output-dir", str(global_output),
            )
            database = global_output / "mmp_database.sqlite"
            before = database.read_bytes()
            screen_output = root / "screen"
            registry = root / "cluster_registry.jsonl"
            registry.write_text(
                json.dumps({"cluster_id": "C000001", "source_node_id": "N000222", "clustering_capability_id": "C002",
                            "source_description_node_ids": [], "source_description_capability_ids": []}) + "\n",
                encoding="utf-8",
            )
            self.command("local-screen", "--mmp-database", str(database), "--cluster-membership", str(MEMBERSHIP),
                         "--cluster-registry", str(registry), "--output-dir", str(screen_output))
            screen = pd.read_csv(screen_output / "mmp_local_screening.csv")
            self.assertEqual({"C000001", "C000002", "C000003"}, set(screen["cluster_id"]))
            first = screen.loc[screen["cluster_id"] == "C000001"].iloc[0]
            self.assertEqual("N000222", first["clustering_node_id"])
            self.assertEqual("C002", first["clustering_capability_id"])
            self.assertEqual("structure", first["clustering_input_kind"])
            self.assertLessEqual(first["primary_within_pair_count"], first["within_pair_count"])
            self.assertGreater(first["global_fraction"], 0)
            detail_output = root / "detail"
            self.command("local-detail", "--mmp-database", str(database), "--cluster-membership", str(MEMBERSHIP), "--cluster-id", "C000001", "--output-dir", str(detail_output))
            self.assertTrue((detail_output / "mmp_global_vs_local.csv").is_file())
            detail_report = (detail_output / "operator_report.html").read_text(encoding="utf-8")
            self.assertIn("Cluster C000001", detail_report)
            self.assertEqual(before, database.read_bytes())

    def test_capability_and_schemas_validate(self) -> None:
        capability = json.loads((SKILL / "capability.json").read_text(encoding="utf-8"))
        self.assertEqual(("A014", "0.1.4"), (capability["capability_id"], capability["version"]))
        self.assertEqual(["global-build", "local-screen", "local-detail"], capability["roles"])
        for path in (SKILL / "schemas").glob("*.json"):
            json.loads(path.read_text(encoding="utf-8"))

    def test_no_qualifying_pairs_is_a_successful_negative_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "negative"
            self.command(
                "global-build", "--input", str(NO_PAIRS), "--id-column", "compound_id",
                "--smiles-column", "smiles", "--endpoint-column", "pIC50",
                "--higher-is-better", "true", "--available-cpu-cores", "2", "--output-dir", str(output),
            )
            result = json.loads((output / "mmp_result.json").read_text(encoding="utf-8"))
            self.assertTrue(result["negative_result"])
            self.assertEqual(0, len(pd.read_csv(output / "mmp_pair_detail.csv")))
            self.assertIn("Negative Result", (output / "operator_report.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
