from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATOR = ROOT / ".claude" / "skills" / "cs-conductor-migrate-v430-run" / "scripts" / "migrate.py"
DATA = ROOT / "CONDUCTOR_modules" / "tests" / "data" / "small_sar.csv"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class V431MigrationTests(unittest.TestCase):
    def cli(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(MIGRATOR), *arguments], cwd=ROOT, check=check, text=True, capture_output=True)

    def fixture(self, root: Path) -> Path:
        root.mkdir()
        description = root / "description" / "skill" / "ND0999"; description.mkdir(parents=True)
        description_csv = description / "description.csv"; description_csv.write_text("compound_id,x\nCMPD_001,1\n", encoding="utf-8")
        analysis = root / "analysis" / "skill" / "NO1500"; analysis.mkdir(parents=True)
        evidence = analysis / "evidence.json"; evidence.write_text(json.dumps({"run_id": "legacy", "node_id": "NO1500", "evidence_id": "E000001", "summary": "legacy signal"}), encoding="utf-8")
        report = analysis / "operator_report.html"; report.write_text("<html>legacy</html>", encoding="utf-8")
        result = analysis / "result.csv"; result.write_text("compound_id,value\nCMPD_001,1\n", encoding="utf-8")
        nodes = [
            {"node_id": "ND0999", "capability_id": "D001", "skill_name": "cs-compute-description-rdkit-2d", "stage": "description", "phase": "basic_compute", "round_id": "RND0001", "status": "succeeded", "dependencies": [], "input_bindings": {}, "parameters": {"input": str(DATA), "output_dir": str(description)}, "analysis_signature": "a" * 64, "human_approval": "not_required", "output_dir": str(description), "requested_at": "2026-01-01T00:00:00+00:00", "artifacts": [{"type": "description", "resolved_path": str(description_csv), "sha256": digest(description_csv)}]},
            {"node_id": "NO1500", "capability_id": "A002", "skill_name": "cs-analysis-activity-distribution", "stage": "analysis", "phase": "initial_global", "round_id": "RND0001", "status": "succeeded", "dependencies": ["ND0999"], "input_bindings": {"description": ["ND0999"]}, "parameters": {"input": str(DATA), "output_dir": str(analysis), "scope_mode": "global"}, "analysis_signature": "b" * 64, "human_approval": "not_required", "output_dir": str(analysis), "requested_at": "2026-01-01T00:00:00+00:00", "evidence_id": "E000001", "artifacts": [{"type": "evidence", "resolved_path": str(evidence), "sha256": digest(evidence)}, {"type": "operator_report", "resolved_path": str(report), "sha256": digest(report)}, {"type": "operator_result", "resolved_path": str(result), "sha256": digest(result)}]},
            {"node_id": "NI0900", "capability_id": "I001", "skill_name": "cs-analysis-interpret-evidence", "stage": "interpretation", "phase": "human_directed", "round_id": "RND0001", "status": "succeeded", "dependencies": ["NO1500"], "input_bindings": {}, "parameters": {}, "analysis_signature": "c" * 64, "human_approval": "not_required", "output_dir": str(root / "interpretation" / "NI0900"), "requested_at": "2026-01-01T00:00:00+00:00", "artifacts": []},
        ]
        state = {
            "schema_version": "2.0.0", "conductor_version": "4.3.0",
            "run": {"run_id": "legacy", "project": "unit", "input": str(DATA.resolve()), "input_hash": digest(DATA), "endpoint": "pIC50", "higher_is_better": True, "parallel_limit": 2, "row_count": 6, "id_column": "compound_id", "assay_column": "assay", "assay_level_count": 2, "profile_id": "comprehensive-multiround-v1", "high_cost_bundle": {"capability_ids": [], "status": "approved", "scope": {}, "scope_hash": "0" * 64}},
            "id_counters": {"description_node": 999, "grouping_node": 0, "operator_node": 1500, "interpretation_node": 900, "group": 0, "evidence": 1, "finding": 20, "hypothesis": 5, "question": 7, "relation": 2, "request": 3, "scope": 0, "salience_event": 1},
            "execution_graph": {"nodes": nodes, "edges": [{"source": "ND0999", "target": "NO1500", "relation": "depends_on"}, {"source": "NO1500", "target": "NI0900", "relation": "depends_on"}]},
        }
        (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
        interpretation = root / "interpretation" / "NI0900"; interpretation.mkdir(parents=True); (interpretation / "interpretation.html").write_text("legacy", encoding="utf-8")
        return root / "state.json"

    def test_scan_apply_verify_creates_distinct_run_and_preserves_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory); source = temporary / "source"; target = temporary / "target"
            source_state = self.fixture(source); before = digest(source_state)
            scan = json.loads(self.cli("scan", "--source-run-root", str(source), "--target-run-root", str(target), "--new-run-id", "imported").stdout)
            self.assertTrue(scan["applicable"]); self.assertEqual(2, scan["included_node_count"]); self.assertEqual(1, scan["excluded_node_count"])
            plan = Path(scan["plan_path"])
            with (plan.parent / "node_id_map.csv").open(encoding="utf-8") as handle:
                mapping = list(__import__("csv").DictReader(handle))
            self.assertEqual(["ND0001", "NO0001"], [row["new_node_id"] for row in mapping])
            applied = json.loads(self.cli("apply", "--plan", str(plan), "--approve").stdout)
            self.assertEqual("pass", applied["status"]); self.assertEqual(before, digest(source_state))
            migrated = json.loads((target / "state.json").read_text(encoding="utf-8"))
            self.assertEqual("4.3.1", migrated["conductor_version"]); self.assertEqual("RND0002", migrated["round_control"]["active_round_id"])
            self.assertEqual(20, migrated["id_counters"]["finding"])
            self.assertFalse(any(node["stage"] == "interpretation" for node in migrated["execution_graph"]["nodes"]))
            verified = json.loads(self.cli("verify", "--target-run-root", str(target)).stdout)
            self.assertEqual("pass", verified["status"])

    def test_apply_refuses_artifact_changed_after_scan_before_creating_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory); source = temporary / "source"; target = temporary / "target"
            self.fixture(source)
            scan = json.loads(self.cli("scan", "--source-run-root", str(source), "--target-run-root", str(target)).stdout)
            plan = Path(scan["plan_path"])
            artifact = source / "description" / "skill" / "ND0999" / "description.csv"
            artifact.write_text("compound_id,x\nCMPD_001,999\n", encoding="utf-8")
            rejected = self.cli("apply", "--plan", str(plan), "--approve", check=False)
            self.assertNotEqual(0, rejected.returncode)
            self.assertIn("Source artifacts changed after scan", rejected.stderr)
            self.assertFalse(target.exists())

    def test_group_registry_and_membership_index_are_rebuilt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory); source = temporary / "source"; target = temporary / "target"
            source_state_path = self.fixture(source)
            grouping = source / "grouping" / "skill" / "NG0042"; grouping.mkdir(parents=True)
            membership = grouping / "group_membership.csv"
            membership.write_text("compound_id,G000001\nCMPD_001,true\n", encoding="utf-8")
            group_index = source / "grouping" / "group_index"; group_index.mkdir(parents=True)
            registry = group_index / "group_registry.csv"
            registry.write_text("group_id,status,source_node_id\nG000001,active,NG0042\n", encoding="utf-8")
            matrix = group_index / "Cpd_Group_matrix_G000000_099999.csv"
            matrix.write_text("compound_id,G000001\nCMPD_001,true\n", encoding="utf-8")
            state = json.loads(source_state_path.read_text(encoding="utf-8"))
            state["execution_graph"]["nodes"].append({
                "node_id": "NG0042", "capability_id": "G001", "skill_name": "cs-compute-clustering-kmeans",
                "stage": "grouping", "phase": "basic_compute", "round_id": "RND0001", "status": "succeeded",
                "dependencies": ["ND0999"], "input_bindings": {"description": ["ND0999"]},
                "parameters": {"description": str(source / "description" / "skill" / "ND0999" / "description.csv"), "output_dir": str(grouping)},
                "analysis_signature": "d" * 64, "human_approval": "not_required", "output_dir": str(grouping),
                "global_membership_path": str(membership), "requested_at": "2026-01-01T00:00:00+00:00",
                "artifacts": [{"type": "group_membership", "resolved_path": str(membership), "sha256": digest(membership)}],
            })
            state["execution_graph"]["edges"].append({"source": "ND0999", "target": "NG0042", "relation": "depends_on"})
            state["id_counters"]["grouping_node"] = 42
            state["id_counters"]["group"] = 1
            state["indices"] = {"group": {"registry_path": str(registry)}}
            source_state_path.write_text(json.dumps(state), encoding="utf-8")

            scan = json.loads(self.cli("scan", "--source-run-root", str(source), "--target-run-root", str(target)).stdout)
            applied = json.loads(self.cli("apply", "--plan", scan["plan_path"], "--approve").stdout)
            self.assertEqual("pass", applied["status"])
            migrated = json.loads((target / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(1, migrated["indices"]["group"]["group_count"])
            self.assertIn("NG0001", migrated["indices"]["group"]["by_node"])
            self.assertTrue(Path(migrated["indices"]["group"]["by_node"]["NG0001"]).is_file())


if __name__ == "__main__":
    unittest.main()
