from __future__ import annotations

import json
import sys
import tempfile
import unittest
import importlib.util
from pathlib import Path
from unittest import mock

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "CONDUCTOR_modules" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import description_database as db


class DescriptionDatabase0110Tests(unittest.TestCase):
    def capability(self, skill_dir: Path, *, skill_version: str = "0.1.10", calculation_version: str = "1") -> dict:
        (skill_dir / "env").mkdir(parents=True, exist_ok=True)
        (skill_dir / "env" / "pixi.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
        return {
            "capability_id": "D001",
            "skill_name": "cs-compute-description-rdkit-2d",
            "version": skill_version,
            "calculation_version": calculation_version,
            "representation_id": "D001",
            "value_semantics": "dense_continuous",
            "natural_metric": "euclidean",
            "implementation": {"algorithm": "rdkit_2d"},
            "output": {"basename": "D001_rdkit_2d"},
            "_skill_dir": str(skill_dir),
        }

    def dataset(self, path: Path, smiles: str = "C(C)O") -> None:
        path.write_text(
            f"compound_id,SMILES,Endpoint\nC1,{smiles},1.0\n",
            encoding="utf-8",
        )

    def plan(self, root: Path, dataset: Path, capability: dict) -> dict:
        scratch = root / "scratch"
        scratch.mkdir(exist_ok=True)
        return db.prepare_cache_plan(
            project_root=root,
            program_name="program-a",
            dataset_path=dataset,
            id_column="compound_id",
            smiles_column="SMILES",
            capability=capability,
            parameters={},
            scratch=scratch,
            source_run_id="RUN001",
        )

    def register(self, plan: dict, root: Path) -> Path:
        payload = root / "payload.csv"
        pd.DataFrame([{
            "compound_id": "C1",
            "input_smiles": "CCO",
            "mol_parse_ok": True,
            "description_error": "",
            "MolWt": 46.07,
        }]).to_csv(payload, index=False)
        inserted = db.register_misses(
            plan=plan,
            payload_path=payload,
            manifest={
                "feature_columns": ["MolWt"],
                "value_semantics": "dense_continuous",
                "natural_metric": "euclidean",
            },
            identity={
                "run_id": "RUN001", "round_id": "RND0001", "node_id": "N000001"
            },
        )
        self.assertEqual(inserted, 1)
        return payload

    def test_canonical_smiles_drives_cache_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = root / "skill"
            cap = self.capability(skill)
            first = root / "first.csv"
            self.dataset(first, "C(C)O")
            cold = self.plan(root, first, cap)
            self.assertEqual(cold["miss_ids"], ["C1"])
            self.register(cold, root)

            second = root / "second.csv"
            self.dataset(second, "OCC")
            warm = self.plan(root, second, cap)
            self.assertEqual(warm["hit_ids"], ["C1"])
            self.assertEqual(warm["miss_count"], 0)

    def test_skill_version_is_provenance_but_calculation_version_invalidates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset = root / "input.csv"
            self.dataset(dataset)
            cap = self.capability(root / "skill", skill_version="0.1.10")
            cold = self.plan(root, dataset, cap)
            self.register(cold, root)

            report_only = self.capability(
                root / "skill", skill_version="0.1.11", calculation_version="1"
            )
            reused = self.plan(root, dataset, report_only)
            self.assertEqual(reused["hit_count"], 1)
            self.assertEqual(
                reused["cache_source_versions"],
                {"calculation=1;skill=0.1.10": 1},
            )

            changed = self.capability(
                root / "skill", skill_version="0.1.11", calculation_version="2"
            )
            invalidated = self.plan(root, dataset, changed)
            self.assertEqual(invalidated["miss_count"], 1)
            self.assertEqual(invalidated["version_mismatch_count"], 1)
            self.assertEqual(invalidated["configuration_mismatch_count"], 0)

            configured = db.prepare_cache_plan(
                project_root=root,
                program_name="program-a",
                dataset_path=dataset,
                id_column="compound_id",
                smiles_column="SMILES",
                capability=report_only,
                parameters={"new_parameter": 1},
                scratch=root / "scratch-configured",
                source_run_id="RUN002",
            )
            self.assertEqual(configured["miss_count"], 1)
            self.assertEqual(configured["version_mismatch_count"], 0)
            self.assertEqual(configured["configuration_mismatch_count"], 1)

    def test_same_id_different_structure_fails_fast_across_description_databases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset = root / "input.csv"
            self.dataset(dataset, "CCO")
            cap = self.capability(root / "skill")
            self.register(self.plan(root, dataset, cap), root)

            changed = root / "changed.csv"
            self.dataset(changed, "CCN")
            other = dict(cap)
            other.update({
                "capability_id": "D002",
                "skill_name": "cs-compute-description-morgan",
                "representation_id": "D002",
            })
            with self.assertRaisesRegex(ValueError, "different canonical structure"):
                self.plan(root, changed, other)

    def test_invalidation_is_audited_and_becomes_a_cache_miss(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset = root / "input.csv"
            self.dataset(dataset)
            cap = self.capability(root / "skill")
            plan = self.plan(root, dataset, cap)
            self.register(plan, root)
            path = Path(plan["database_path"])
            invalidated = db.invalidate_records(
                path, compound_id="C1", reason="test correction", operator="tester"
            )
            self.assertEqual(len(invalidated), 1)
            self.assertEqual(self.plan(root, dataset, cap)["miss_count"], 1)
            events = [
                json.loads(line)
                for line in db.audit_path(path).read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(events[-1]["event"], "RECORD_INVALIDATED")

    def test_warm_cache_reconstructs_a_full_output_without_kernel(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset = root / "input.csv"
            self.dataset(dataset)
            cap = self.capability(root / "skill")
            cold = self.plan(root, dataset, cap)
            self.register(cold, root)
            warm = self.plan(root, dataset, cap)
            output = root / "output"
            request = {
                "conductor_version": "0.1.10",
                "created_at": db.utc_now(),
                "identity": {
                    "project": "program-a", "run_id": "RUN002",
                    "round_id": "RND0001", "node_id": "N000002",
                    "attempt_id": "ATT0001", "capability_id": "D001",
                    "skill_name": cap["skill_name"],
                },
            }
            payload = db.finalize_cached_output(
                plan=warm, output=output, request=request, capability=cap
            )
            restored = pd.read_csv(payload)
            self.assertEqual(restored["compound_id"].tolist(), ["C1"])
            self.assertEqual(restored["MolWt"].tolist(), [46.07])
            event = json.loads((output / "execution_event.json").read_text(encoding="utf-8"))
            self.assertEqual(event["cache"]["hit_count"], 1)

    def test_runtime_all_hit_path_skips_description_kernel(self) -> None:
        runtime_path = TOOLS / "runtime_controller.py"
        specification = importlib.util.spec_from_file_location(
            "runtime_0110_warm_cache_test", runtime_path
        )
        runtime = importlib.util.module_from_spec(specification)
        assert specification.loader is not None
        specification.loader.exec_module(runtime)
        capability = runtime.capabilities()["D001"]
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            dataset = base / "input.csv"
            self.dataset(dataset, "CCO")
            cold_scratch = base / "cold-scratch"
            cold_scratch.mkdir()
            cold = db.prepare_cache_plan(
                project_root=base,
                program_name="program-a",
                dataset_path=dataset,
                id_column="compound_id",
                smiles_column="SMILES",
                capability=capability,
                parameters=dict(capability.get("default_parameters") or {}),
                scratch=cold_scratch,
                source_run_id="RUN001",
            )
            payload = base / "D001_rdkit_2d.csv"
            pd.DataFrame([{
                "compound_id": "C1", "input_smiles": "CCO",
                "mol_parse_ok": True, "description_error": "",
                "MolWt": 46.07,
            }]).to_csv(payload, index=False)
            db.register_misses(
                plan=cold, payload_path=payload,
                manifest={
                    "feature_columns": ["MolWt"],
                    "value_semantics": capability["value_semantics"],
                    "natural_metric": capability["natural_metric"],
                },
                identity={
                    "run_id": "RUN001", "round_id": "RND0001",
                    "node_id": "N000000",
                },
            )
            warm_scratch = base / "warm-plan"
            warm_scratch.mkdir()
            warm = db.prepare_cache_plan(
                project_root=base,
                program_name="program-a",
                dataset_path=dataset,
                id_column="compound_id",
                smiles_column="SMILES",
                capability=capability,
                parameters=dict(capability.get("default_parameters") or {}),
                scratch=warm_scratch,
                source_run_id="RUN002",
            )
            self.assertEqual(warm["miss_count"], 0)

            run_root = base / "run"
            for directory in ("runtime", "state", "description"):
                (run_root / directory).mkdir(parents=True, exist_ok=True)
            control = {
                "schema_version": "1.0.0", "conductor_version": "0.1.10",
                "revision": 0, "project": "program-a", "run_id": "RUN002",
                "input_path": str(dataset), "input_sha256": runtime.sha256(dataset),
                "columns": {
                    "compound_id": "compound_id", "smiles": "SMILES",
                    "endpoint": "Endpoint",
                },
                "higher_is_better": True, "available_cpu_cores": 2,
                "parallel_limit": 1, "active_round_id": "RND0001",
                "round_status": "ACTIVE",
            }
            node = {
                "node_id": "N000001", "capability_id": "D001",
                "skill_name": capability["skill_name"], "stage": "description",
                "wave": "basic", "round_id": "RND0001", "dependencies": [],
                "parameters": dict(capability.get("default_parameters") or {}),
                "signature": "warm-cache-test", "status": "pending",
                "attempts": [], "result": None, "error": None,
                "waived": False,
            }
            dag = {
                "schema_version": "1.0.0", "conductor_version": "0.1.10",
                "revision": 0, "nodes": [node],
            }
            runtime.atomic_json(runtime.control_path(run_root), control)
            runtime.atomic_json(runtime.dag_path(run_root), dag)
            with (
                mock.patch.object(runtime, "prepare_cache_plan", return_value=warm),
                mock.patch.object(runtime.subprocess, "run") as kernel,
            ):
                result = runtime.run_node(run_root, "N000001")
            _, committed = runtime.load_state(run_root)
            completed = committed["nodes"][0]
            restored = pd.read_csv(completed["result"]["primary_path"])
            log = (
                run_root / "runtime" / "scratch" / "N000001" / "ATT0001"
                / "execution.log"
            ).read_text(encoding="utf-8")
        self.assertEqual(result["status"], "succeeded")
        kernel.assert_not_called()
        self.assertEqual(restored["compound_id"].tolist(), ["C1"])
        self.assertEqual(restored["MolWt"].tolist(), [46.07])
        self.assertEqual(completed["result"]["description_cache"]["hit_count"], 1)
        self.assertIn("calculation skipped", log)


if __name__ == "__main__":
    unittest.main()
