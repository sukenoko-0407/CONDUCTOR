from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "CONDUCTOR_modules" / "tools" / "migrate_description_010_to_011.py"
SPEC = importlib.util.spec_from_file_location("description_migration", SCRIPT)
MIGRATE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MIGRATE)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


class DescriptionMigrationTests(unittest.TestCase):
    def test_description_only_round1_migration(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            temporary = Path(folder)
            source = temporary / "source"
            attempt = source / "description" / "cs-compute-description-rdkit-2d" / "ND000071" / "attempts" / "ATT0003"
            attempt.mkdir(parents=True)
            input_path = temporary / "input.csv"
            with input_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["compound_id", "smiles", "pIC50"])
                for number in range(1, 7):
                    writer.writerow([f"C{number:03d}", "CCO", 5.0 + number / 10])
            vector = attempt / "D001_rdkit_2d.csv"
            with vector.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["compound_id", "MolWt", "MolLogP"])
                for number in range(1, 7):
                    writer.writerow([f"C{number:03d}", 40 + number, number / 10])
            write_json(
                attempt / "description_manifest.json",
                {
                    "schema_version": "2.0.0",
                    "conductor_version": "0.1.0",
                    "artifact_stage": "description",
                    "capability_id": "D001",
                    "value_semantics": "continuous_descriptor",
                    "natural_metric": "euclidean",
                    "feature_columns": ["MolWt", "MolLogP"],
                    "warnings": [],
                    "errors": [],
                },
            )
            write_json(attempt / "warnings.json", {"warnings": [], "errors": []})
            input_hash = hashlib.sha256(input_path.read_bytes()).hexdigest()
            state = {
                "schema_version": "2.0.0",
                "conductor_version": "0.1.0",
                "run": {
                    "run_id": "source-run",
                    "project": "unit",
                    "run_root": str(source),
                    "input": str(input_path),
                    "input_hash": input_hash,
                    "endpoint": "pIC50",
                    "higher_is_better": True,
                    "parallel_limit": 4,
                    "row_count": 6,
                    "profile_id": "comprehensive-multiround-beta",
                },
                "execution_graph": {
                    "nodes": [
                        {
                            "node_id": "ND000071",
                            "stage": "description",
                            "capability_id": "D001",
                            "skill_name": "cs-compute-description-rdkit-2d",
                            "status": "succeeded",
                            "parameters": {},
                            "output_dir": str(attempt.parents[1]),
                            "committed_attempt_id": "ATT0003",
                            "execution_attempts": [{"attempt_id": "ATT0003", "status": "succeeded"}],
                            "artifacts": [
                                {"type": "description", "resolved_path": str(vector)},
                                {"type": "manifest", "resolved_path": str(attempt / "description_manifest.json")},
                                {"type": "warnings", "resolved_path": str(attempt / "warnings.json")},
                            ],
                        },
                        {"node_id": "NC000001", "stage": "clustering", "status": "succeeded"},
                    ],
                    "edges": [{"source": "ND000071", "target": "NC000001"}],
                },
            }
            write_json(source / "state.json", state)

            scan = MIGRATE.scan_source(source, ROOT)
            self.assertEqual(1, scan["description_count"])
            with self.assertRaisesRegex(ValueError, "non-nested"):
                MIGRATE.apply_migration(scan, source / "nested-target", ROOT, "bad-target", "unit", input_path)
            target = temporary / "target"
            state_path = MIGRATE.apply_migration(scan, target, ROOT, "target-run", "unit", input_path)
            report = MIGRATE.validate_target(scan, target, ROOT)
            migrated = json.loads(state_path.read_text(encoding="utf-8"))

            self.assertEqual("pass", report["status"])
            self.assertEqual("0.1.1", migrated["conductor_version"])
            self.assertIsNone(migrated["round_control"]["active_round_id"])
            self.assertEqual(2, migrated["round_control"]["next_round_number"])
            self.assertEqual(1, len(migrated["round_control"]["rounds"]))
            round1 = migrated["round_control"]["rounds"][0]
            self.assertEqual("closed", round1["status"])
            self.assertEqual("partial_basic_compute", round1["completion_state"])
            self.assertEqual("version_migration_during_basic_compute", round1["stop_reason"])
            self.assertEqual(["description"], [node["stage"] for node in migrated["execution_graph"]["nodes"]])
            imported = Path(migrated["execution_graph"]["nodes"][0]["final_output_dir"]) / "D001_rdkit_2d.csv"
            self.assertEqual(hashlib.sha256(vector.read_bytes()).hexdigest(), hashlib.sha256(imported.read_bytes()).hexdigest())

            runtime = ROOT / ".claude" / "skills" / "cs-conductor-runtime" / "scripts" / "state_manager.py"
            bootstrap = subprocess.run(
                [sys.executable, str(runtime), "bootstrap", "--state", str(state_path), "--owner-id", "migration-test"],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=True,
            )
            token = json.loads(bootstrap.stdout)["lease_token"]
            subprocess.run(
                [sys.executable, str(runtime), "round-start", "--state", str(state_path), "--round-id", "RND0002", "--request", "continue", "--lease-token", token],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                [sys.executable, str(runtime), "plan-basic", "--state", str(state_path), "--lease-token", token],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=True,
            )
            continued = json.loads(state_path.read_text(encoding="utf-8"))
            d001 = [node for node in continued["execution_graph"]["nodes"] if node["capability_id"] == "D001"]
            self.assertEqual(1, len(d001))
            self.assertEqual("RND0001", d001[0]["execution_round_id"])
            self.assertEqual("succeeded", d001[0]["status"])
            self.assertEqual("RND0002", continued["round_control"]["active_round_id"])


if __name__ == "__main__":
    unittest.main()
