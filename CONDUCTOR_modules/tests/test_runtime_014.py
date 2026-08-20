from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("runtime014", ROOT / "CONDUCTOR_modules" / "tools" / "runtime_controller.py")
assert SPEC and SPEC.loader
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)


class Runtime014(unittest.TestCase):
    def test_runtime_help_identifies_version_014(self) -> None:
        self.assertEqual("CONDUCTOR 0.1.4 deterministic Runtime Controller", RUNTIME.build_parser().description)

    def test_version_013_control_remains_readable_without_migration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input.csv"
            source.write_text("compound_id,smiles,pIC50\nX1,CCO,5.0\nX2,CCN,5.5\n", encoding="utf-8")
            run_root = root / "run"
            controller = ROOT / "CONDUCTOR_modules" / "tools" / "runtime_controller.py"
            subprocess.run([
                sys.executable, str(controller), "init", "--input", str(source), "--endpoint", "pIC50",
                "--higher-is-better", "--project", "compat", "--parallel-limit", "1", "--output-dir", str(run_root),
            ], cwd=ROOT, check=True, capture_output=True, text=True)
            control_path = run_root / "conductor_control.json"
            control = json.loads(control_path.read_text(encoding="utf-8"))
            control["conductor_version"] = "0.1.3"
            control_path.write_text(json.dumps(control, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            queried = subprocess.run([
                sys.executable, str(controller), "query", "--run-root", str(run_root), "--kind", "control",
            ], cwd=ROOT, check=True, capture_output=True, text=True)
            self.assertEqual("0.1.3", json.loads(queried.stdout)["conductor_version"])

    def test_mmp_round_guard_accepts_newly_authorized_round_only(self) -> None:
        control = {"active_round_id": "RND0002"}
        old = {"rounds": {"RND0002": {"state": "ACTIVE"}}}
        new = {"rounds": {"RND0002": {"state": "ACTIVE", "runtime_version": "0.1.4"}}}
        self.assertFalse(RUNTIME._mmp_enabled_for_active_round(control, old))
        self.assertTrue(RUNTIME._mmp_enabled_for_active_round(control, new))

    def test_global_mmp_command_uses_explicit_role_and_run_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            node = {
                "node_id": "N000123", "capability_id": "A014", "skill_name": "cs-analysis-matched-molecular-pairs",
                "assigned_round": "RND0002", "input_nodes": [], "parameters": {"role": "global-build"},
            }
            control = {
                "run": {"project": "p", "run_id": "r", "input": str(ROOT / "CONDUCTOR_modules" / "tests" / "data" / "small_sar.csv"),
                        "id_column": "compound_id", "smiles_column": "smiles", "endpoint": "pIC50", "higher_is_better": True,
                        "available_cpu_cores": 12, "parallel_limit": 4}
            }
            command = RUNTIME._mmp_skill_command(root, control, {"nodes": []}, node, "ATT0001", root / "scratch", ROOT / ".claude" / "skills" / "cs-analysis-matched-molecular-pairs" / "scripts" / "launch.py")
            self.assertEqual("global-build", command[2])
            self.assertLess(command.index("global-build"), command.index("--conductor"))
            self.assertEqual("12", command[command.index("--available-cpu-cores") + 1])
            self.assertEqual("smiles", command[command.index("--smiles-column") + 1])

    def test_global_mmp_is_exclusive_but_queries_are_lightweight(self) -> None:
        self.assertTrue(RUNTIME._requires_exclusive_cpu({"capability_id": "A014", "parameters": {"role": "global-build"}}))
        self.assertFalse(RUNTIME._requires_exclusive_cpu({"capability_id": "A014", "parameters": {"role": "local-screen"}}))

    def test_local_screen_command_passes_canonical_cluster_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            global_node = {"node_id": "N000100", "capability_id": "A014", "kind": "analysis",
                           "parameters": {"role": "global-build"}, "output_ref": str(root / "analysis" / "N000100")}
            clustering = {"node_id": "N000101", "capability_id": "C002", "kind": "clustering", "parameters": {}}
            node = {"node_id": "N000102", "capability_id": "A014", "skill_name": "cs-analysis-matched-molecular-pairs",
                    "assigned_round": "RND0001", "input_nodes": ["N000100", "N000101"],
                    "parameters": {"role": "local-screen"}}
            control = {"run": {"project": "p", "run_id": "r"}}
            command = RUNTIME._mmp_skill_command(root, control, {"nodes": [global_node, clustering]}, node, "ATT0001", root / "scratch", Path("launch.py"))
            self.assertEqual(str(root / "runtime" / "cluster_registry.jsonl"), command[command.index("--cluster-registry") + 1])

    def test_initial_local_does_not_bypass_round_analysis_limit(self) -> None:
        control = {"active_round_id": "RND0001"}
        snapshot = {"nodes": [], "plans": {"RND0001": {}}, "rounds": {"RND0001": {}}}
        global_mmp = {"node_id": "N000100", "parameters": {"role": "global-build"}}
        clustering = {"node_id": "N000101", "capability_id": "C002"}
        profile = {
            "initial_exploration": {"description_master_panel": [], "representative_clusters_per_clustering": 1,
                                    "local_operator_capabilities": [], "projection_overlay_capabilities": []},
            "modeling": {"fixed_description_panel": [], "minimum_local_samples": 30},
            "matched_molecular_pairs": {"capability_id": "A014", "global_role": "global-build",
                                          "screen_role": "local-screen", "detail_role": "local-detail",
                                          "representative_clustering_capabilities": ["C002"],
                                          "representative_clusters_per_clustering": 1},
        }

        def succeeded(_snapshot: dict, kind: str, capabilities=None):
            return [global_mmp] if kind == "analysis" and capabilities == ["A014"] else []

        with patch.object(RUNTIME, "profile", return_value=profile), \
                patch.object(RUNTIME, "catalog", return_value={}), \
                patch.object(RUNTIME, "_succeeded", side_effect=succeeded), \
                patch.object(RUNTIME, "_usable_clusterings", return_value=[clustering]), \
                patch.object(RUNTIME, "_mmp_enabled_for_active_round", return_value=True), \
                patch.object(RUNTIME, "_analysis_planning_limits", return_value=(200, 50)), \
                patch.object(RUNTIME, "_round_analysis_work_count", return_value=200), \
                patch.object(RUNTIME, "_materialize_analysis_specs", return_value=([], 0)), \
                patch.object(RUNTIME, "_add_node") as add_node:
            self.assertEqual([], RUNTIME._plan_initial_local(Path("."), control, snapshot))
            add_node.assert_not_called()

    def test_mmp_payload_promotion_checks_csv_parquet_database_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill_output = root / "skill"
            promoted = root / "promoted"
            skill_output.mkdir()
            promoted.mkdir()
            frame = pd.DataFrame({"mmp_id": ["MMP-a", "MMP-b"], "value": [1.0, 2.0]})
            frame.to_csv(skill_output / "mmp_pair_detail.csv", index=False)
            frame.to_parquet(skill_output / "mmp_pair_detail.parquet", index=False)
            with closing(sqlite3.connect(skill_output / "mmp_database.sqlite")) as connection:
                frame.to_sql("mmp_pairs", connection, index=False)
                connection.commit()
            names = {"mmp_pair_detail.csv", "mmp_pair_detail.parquet", "mmp_database.sqlite"}
            manifest = {"payloads": {
                "mmp_pair_detail": "mmp_pair_detail.csv",
                "mmp_pair_detail_parquet": "mmp_pair_detail.parquet",
                "mmp_database": "mmp_database.sqlite",
            }}
            artifacts = {
                f"artifact-{index}": {"path": name, "sha256": RUNTIME.file_hash(skill_output / name)}
                for index, name in enumerate(names)
            }
            result = RUNTIME._promote_mmp_payloads(skill_output, promoted, manifest, artifacts)
            self.assertEqual(names, set(result.values()))
            self.assertEqual("mmp_database.sqlite", result["mmp_database"])
            self.assertEqual("mmp_pair_detail.csv", result["mmp_pair_detail"])

            with closing(sqlite3.connect(skill_output / "mmp_database.sqlite")) as connection:
                connection.execute("DELETE FROM mmp_pairs WHERE mmp_id = 'MMP-b'")
                connection.commit()
            database_artifact = next(item for item in artifacts.values() if item["path"] == "mmp_database.sqlite")
            database_artifact["sha256"] = RUNTIME.file_hash(skill_output / "mmp_database.sqlite")
            (root / "promoted-mismatch").mkdir()
            with self.assertRaisesRegex(ValueError, "row-count mismatch"):
                RUNTIME._promote_mmp_payloads(skill_output, root / "promoted-mismatch", manifest, artifacts)


if __name__ == "__main__":
    unittest.main()
