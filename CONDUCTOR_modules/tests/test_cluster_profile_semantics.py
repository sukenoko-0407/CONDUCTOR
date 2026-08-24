from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".claude" / "skills" / "cs-analysis-cluster-profile" / "scripts"
HAS_PANDAS = importlib.util.find_spec("pandas") is not None


def load_module(name: str, path: Path):
    sys.path.insert(0, str(path.parent))
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


@unittest.skipUnless(HAS_PANDAS, "pandas is installed by the A010 Skill Pixi environment")
class ClusterProfileSemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import pandas as pd

        cls.pd = pd
        cls.run_module = load_module("cluster_profile_run_test", SCRIPTS / "run.py")
        cls.report_module = load_module("cluster_profile_report_test", SCRIPTS / "operator_report.py")

    def endpoint_table(self):
        return self.pd.DataFrame({
            "compound_id": [f"C{i:03d}" for i in range(20)],
            "property_value": [float(i) for i in range(20)],
        })

    def test_lower_is_better_uses_global_low_tail_and_reports_80_percent_cluster(self) -> None:
        table = self.endpoint_table()
        clusters = {"C000001": {"C000", "C001", "C002", "C003", "C019"}}
        args = Namespace(high_quantile=0.8, low_quantile=0.2, higher_is_better=False, target_cluster=None)

        result, summary = self.run_module.cluster_profile(table, clusters, args)
        row = result.iloc[0]

        self.assertAlmostEqual(3.8, summary["low_threshold"])
        self.assertEqual("<=", summary["favorable_comparator"])
        self.assertAlmostEqual(3.8, summary["favorable_threshold"])
        self.assertEqual("global_endpoint_valid", summary["threshold_population"])
        self.assertEqual("pandas_linear", summary["threshold_quantile_method"])
        self.assertEqual(4, row["favorable_count"])
        self.assertAlmostEqual(0.8, row["favorable_fraction"])
        self.assertAlmostEqual(0.2, row["favorable_quantile"])
        self.assertEqual(1, row["unfavorable_count"])
        self.assertNotIn("high_activity_fraction", result.columns)
        self.assertNotIn("low_activity_fraction", result.columns)

    def test_higher_is_better_uses_global_high_tail(self) -> None:
        table = self.endpoint_table()
        clusters = {"C000001": {"C000", "C016", "C017", "C018", "C019"}}
        args = Namespace(high_quantile=0.8, low_quantile=0.2, higher_is_better=True, target_cluster=None)

        result, summary = self.run_module.cluster_profile(table, clusters, args)

        self.assertEqual(">=", summary["favorable_comparator"])
        self.assertAlmostEqual(15.2, summary["favorable_threshold"])
        self.assertEqual(4, result.iloc[0]["favorable_count"])
        self.assertAlmostEqual(0.8, result.iloc[0]["favorable_fraction"])

    def test_inclusive_boundary_records_actual_global_fraction_with_ties(self) -> None:
        table = self.pd.DataFrame({
            "compound_id": [f"C{i:03d}" for i in range(10)],
            "property_value": [0.0] * 8 + [10.0] * 2,
        })
        clusters = {"C000001": set(table["compound_id"])}
        args = Namespace(high_quantile=0.8, low_quantile=0.2, higher_is_better=False, target_cluster=None)

        _, summary = self.run_module.cluster_profile(table, clusters, args)

        self.assertEqual(0.0, summary["favorable_threshold"])
        self.assertEqual(8, summary["global_favorable_count"])
        self.assertAlmostEqual(0.8, summary["global_favorable_fraction"])

    def test_html_states_the_favorable_rule_and_uses_unambiguous_metric(self) -> None:
        table = self.endpoint_table()
        clusters = {"C000001": {"C000", "C001", "C002", "C003", "C019"}}
        calculation_args = Namespace(high_quantile=0.8, low_quantile=0.2, higher_is_better=False, target_cluster=None)
        result, summary = self.run_module.cluster_profile(table, clusters, calculation_args)
        report_args = Namespace(
            higher_is_better=False,
            property_column="IC50",
            description=None,
            membership="cluster_membership.csv",
            description_node_id=None,
            clustering_node_id="N000010",
            node_id="N000020",
            target_cluster=None,
        )
        operator_summary = {
            "scope": {"mode": "global", "sample_count": 20},
            "sample_count": 20,
            "headline": "Cluster profile result",
            "run_id": "RUN001",
            "created_at": "2026-01-01T00:00:00Z",
            "limitations": [],
            "result_ref": "N000020@ATT0001",
        }
        capability = {"operator_id": "A010", "display_name": "Cluster profile", "implementation": {"operator": "cluster_profile"}}

        report = self.report_module.render_operator_report(
            capability, report_args, result, summary, operator_summary, {"configuration": {}}, Path("A010_cluster_profile.csv")
        )

        self.assertIn("Favorable definition", report)
        self.assertIn("Endpoint &lt;= 3.8", report)
        self.assertIn("Global favorable baseline", report)
        self.assertIn("favorable_fraction", report)
        self.assertNotIn("high_activity_fraction", report)

    def test_conductor_cli_writes_valid_self_describing_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            endpoint = folder / "endpoint.csv"
            membership = folder / "membership.csv"
            output = folder / "output"
            endpoint.write_text(
                "compound_id,IC50\n" + "".join(f"C{i:03d},{i}\n" for i in range(20)),
                encoding="utf-8",
            )
            membership.write_text(
                "compound_id,C000001\n" + "".join(
                    f"C{i:03d},{1 if i in {0, 1, 2, 3, 19} else 0}\n" for i in range(20)
                ),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "run.py"),
                    "--input", str(endpoint),
                    "--property-column", "IC50",
                    "--no-higher-is-better",
                    "--membership", str(membership),
                    "--conductor",
                    "--project", "PROJECT",
                    "--run-id", "RUN001",
                    "--round-id", "RND0001",
                    "--node-id", "N000020",
                    "--attempt-id", "ATT0001",
                    "--output-dir", str(output),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            summary = json.loads((output / "operator_summary.json").read_text(encoding="utf-8"))
            csv_text = (output / "A010_cluster_profile.csv").read_text(encoding="utf-8")
            html_text = (output / "operator_report.html").read_text(encoding="utf-8")

            self.assertEqual("<=", summary["key_metrics"]["favorable_comparator"])
            self.assertEqual("global_endpoint_valid", summary["key_metrics"]["threshold_population"])
            self.assertIn("Favorable: Endpoint <= 3.8", summary["headline"])
            self.assertIn("favorable_fraction", csv_text.splitlines()[0])
            self.assertNotIn("high_activity_fraction", csv_text.splitlines()[0])
            self.assertIn("Favorable definition", html_text)


if __name__ == "__main__":
    unittest.main()
