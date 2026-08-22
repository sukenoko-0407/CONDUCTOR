from __future__ import annotations

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
SPEC = importlib.util.spec_from_file_location("runtime015", ROOT / "CONDUCTOR_modules" / "tools" / "runtime_controller.py")
assert SPEC and SPEC.loader
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)
HAS_JSONSCHEMA = importlib.util.find_spec("jsonschema") is not None


class Runtime015(unittest.TestCase):
    def test_runtime_identifies_version_015(self) -> None:
        self.assertEqual("0.1.5", RUNTIME.VERSION)
        self.assertEqual("0.1.5", RUNTIME.PROTOCOL_VERSION)
        self.assertEqual("CONDUCTOR 0.1.5 deterministic Runtime Controller", RUNTIME.build_parser().description)

    def test_mmp_round_guard_accepts_only_current_runtime(self) -> None:
        control = {"active_round_id": "RND0002"}
        old = {"rounds": {"RND0002": {"runtime_version": "0.1.4"}}}
        current = {"rounds": {"RND0002": {"runtime_version": "0.1.5"}}}
        self.assertFalse(RUNTIME._mmp_enabled_for_active_round(control, old))
        self.assertTrue(RUNTIME._mmp_enabled_for_active_round(control, current))

    @unittest.skipUnless(HAS_JSONSCHEMA, "jsonschema is installed by the Runtime Pixi environment")
    def test_global_mmp_request_uses_common_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset = ROOT / "CONDUCTOR_modules" / "tests" / "data" / "small_sar.csv"
            node = {
                "node_id": "N000123", "kind": "analysis", "capability_id": "A014",
                "skill_name": "cs-analysis-matched-molecular-pairs", "assigned_round": "RND0002",
                "input_nodes": [], "scope": {"mode": "global"}, "parameters": {"role": "global-build"},
            }
            control = {"run": {"project": "p", "run_id": "r", "input": str(dataset), "id_column": "compound_id",
                               "smiles_column": "smiles", "endpoint": "pIC50", "higher_is_better": True,
                               "available_cpu_cores": 12, "parallel_limit": 4}}
            request = RUNTIME._execution_request(root, control, {"nodes": []}, node, "ATT0001", root / "scratch")
            self.assertEqual("A014", request["identity"]["capability_id"])
            self.assertEqual(["dataset"], [item["role"] for item in request["inputs"]])
            self.assertEqual(8, request["resources"]["node_cpu_cores"])
            self.assertEqual(2, request["parameters"]["num_cuts"])
            self.assertEqual(2, request["parameters"]["max_radius"])
            self.assertEqual(10, request["parameters"]["max_variable_heavy_atoms"])

    def test_global_mmp_is_exclusive_but_queries_are_lightweight(self) -> None:
        self.assertTrue(RUNTIME._requires_exclusive_cpu({"capability_id": "A014", "parameters": {"role": "global-build"}}))
        self.assertFalse(RUNTIME._requires_exclusive_cpu({"capability_id": "A014", "parameters": {"role": "local-screen"}}))

    @unittest.skipUnless(HAS_JSONSCHEMA, "jsonschema is installed by the MMP Pixi environment")
    def test_global_mmp_fragment_jobs_are_capped_at_eight(self) -> None:
        scripts = ROOT / ".claude" / "skills" / "cs-analysis-matched-molecular-pairs" / "scripts"
        spec = importlib.util.spec_from_file_location("mmp_fragment_jobs_test", scripts / "run.py")
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.path.insert(0, str(scripts))
        try:
            spec.loader.exec_module(module)
        finally:
            sys.path.pop(0)
        self.assertEqual(8, module.fragment_job_count(64, None))
        self.assertEqual(4, module.fragment_job_count(4, None))
        with self.assertRaisesRegex(ValueError, "min\\(8"):
            module.fragment_job_count(64, 9)

    def test_mmp_payload_promotion_checks_csv_database_and_profile_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill_output = root / "skill"
            promoted = root / "promoted"
            skill_output.mkdir()
            promoted.mkdir()
            frame = pd.DataFrame({"mmp_id": ["MMP-a", "MMP-b"], "value": [1.0, 2.0]})
            frame.to_csv(skill_output / "mmp_pair_detail.csv", index=False)
            with closing(sqlite3.connect(skill_output / "mmp_database.sqlite")) as connection:
                frame.to_sql("mmp_pairs", connection, index=False)
                connection.commit()
            (skill_output / "mmp_storage_profile.json").write_text(json.dumps({"table_rows": {"mmp_pairs": 2}}), encoding="utf-8")
            names = {"mmp_pair_detail.csv", "mmp_database.sqlite", "mmp_storage_profile.json"}
            manifest = {"payloads": {Path(name).stem: name for name in names}}
            artifacts = {f"artifact-{index}": {"path": name, "sha256": RUNTIME.file_hash(skill_output / name)} for index, name in enumerate(names)}
            result = RUNTIME._promote_mmp_payloads(skill_output, promoted, manifest, artifacts)
            self.assertEqual(names, set(result.values()))
            with closing(sqlite3.connect(skill_output / "mmp_database.sqlite")) as connection:
                connection.execute("DELETE FROM mmp_pairs WHERE mmp_id = 'MMP-b'")
                connection.commit()
            next(item for item in artifacts.values() if item["path"] == "mmp_database.sqlite")["sha256"] = RUNTIME.file_hash(skill_output / "mmp_database.sqlite")
            with self.assertRaisesRegex(ValueError, "row-count mismatch"):
                RUNTIME._promote_mmp_payloads(skill_output, root / "mismatch", manifest, artifacts)


if __name__ == "__main__":
    unittest.main()
