from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNNER = PROJECT_ROOT / ".claude" / "skills" / "cs-conductor-assessment-report" / "scripts" / "run.py"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def append_jsonl(path: Path, values: list[dict]) -> None:
    path.write_text("".join(json.dumps(value, ensure_ascii=False) + "\n" for value in values), encoding="utf-8")


def bundle(index: int, round_id: str = "RND0001") -> dict:
    return {
        "bundle_id": f"RVB{index:016x}",
        "bundle_type": "global" if index == 1 else "global_local",
        "round_id": round_id,
        "capability_id": f"A{index:03d}",
        "cluster_ids": [] if index == 1 else [f"C{index:06d}"],
        "source_hash": str(index) * 64,
        "revision": 1,
        "created_at": "2026-08-01T00:00:00+00:00",
    }


def assessment(index: int, candidate_class: str, *, revision: int = 1, round_id: str = "RND0001") -> dict:
    return {
        "assessment_id": f"ASR{index:016x}",
        "bundle_id": f"RVB{index:016x}",
        "bundle_type": "global" if index == 1 else "global_local",
        "round_id": round_id,
        "capability_id": f"A{index:03d}",
        "target_result_refs": [f"N{index:06d}@ATT0001"],
        "assessment_status": "evaluated",
        "candidate_class": candidate_class,
        "scores": {
            "favorable_signal": 3 if index == 1 else 2,
            "context_deviation": "not_applicable" if index == 1 else 3,
            "chemical_actionability": 2,
            "independent_support": 1,
            "follow_up_leverage": 3,
        },
        "reliability": {
            "sample_support": "strong" if index == 1 else "moderate",
            "comparator_validity": "none" if index == 1 else "matched",
            "effect_stability": "stable",
            "independence": "independent",
            "quality_flags": [],
        },
        "reason": f"Candidate {index} has a bounded favorable signal.",
        "supporting_result_refs": [f"N{index:06d}@ATT0001"],
        "counter_result_refs": [],
        "rubric_version": "2.0.0",
        "source_hash": str(index) * 64,
        "revision": revision,
        "created_at": f"2026-08-{revision:02d}T00:00:00+00:00",
    }


class AssessmentReportSkillTest(unittest.TestCase):
    def make_run(self, parent: Path) -> Path:
        root = parent / "RUN"
        runtime = root / "runtime"
        runtime.mkdir(parents=True)
        (root / "conductor_control.json").write_text(
            json.dumps({"conductor_version": "0.2.0", "run": {"run_id": "RUN-DEMO"}}) + "\n",
            encoding="utf-8",
        )
        append_jsonl(runtime / "review_bundle_index.jsonl", [bundle(1), bundle(2), bundle(3, "RND0002")])
        old = assessment(1, "supporting_evidence")
        current = assessment(1, "design_lead", revision=2)
        append_jsonl(
            runtime / "result_assessment_index.jsonl",
            [old, current, assessment(2, "contextual_anomaly"), assessment(3, "background", round_id="RND0002")],
        )
        append_jsonl(runtime / "insight_index.jsonl", [{
            "insight_id": "INS000001",
            "revision": 1,
            "review_bundle_ids": ["RVB0000000000000001"],
            "round_id": "RND0001",
            "interpretation_node_id": "N000010",
            "updated_at": "2026-08-02T00:00:00+00:00",
        }])
        return root

    def run_report(self, root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(RUNNER), "--run-root", str(root), "--explicit-request", *extra],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_report_is_read_only_and_marks_full_report_uptake(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.make_run(Path(temporary))
            protected = [root / "conductor_control.json", *sorted((root / "runtime").glob("*.jsonl"))]
            before = {path: digest(path) for path in protected}
            completed = self.run_report(root)
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual(before, {path: digest(path) for path in protected})
            outputs = list((root / "assessment_reports").iterdir())
            self.assertEqual(1, len(outputs))
            report = (outputs[0] / "assessment_summary.html").read_text(encoding="utf-8")
            self.assertIn("評価軸ヒストグラム", report)
            self.assertIn("Full report未収載の有望候補", report)
            self.assertIn("INS000001", report)
            self.assertNotIn("total_score", report)
            manifest = json.loads((outputs[0] / "report_manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(manifest["scientific_axis_sum_used"])
            self.assertEqual(2, manifest["counts"]["reportable_candidates"])
            with (outputs[0] / "assessment_latest.csv").open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(3, len(rows))
            picked = next(row for row in rows if row["bundle_id"] == "RVB0000000000000001")
            self.assertEqual("True", picked["included_in_full_report"])
            self.assertEqual("2", picked["revision"])

    def test_round_filter_is_applied_after_latest_revision_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.make_run(Path(temporary))
            completed = self.run_report(root, "--round-id", "RND0002")
            self.assertEqual(0, completed.returncode, completed.stderr)
            output = next((root / "assessment_reports").iterdir())
            with (output / "assessment_latest.csv").open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(["RND0002"], [row["round_id"] for row in rows])

    def test_legacy_run_is_rejected_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.make_run(Path(temporary))
            (root / "conductor_control.json").write_text('{"conductor_version":"0.1.7"}\n', encoding="utf-8")
            completed = self.run_report(root)
            self.assertNotEqual(0, completed.returncode)
            self.assertFalse((root / "assessment_reports").exists())


if __name__ == "__main__":
    unittest.main()

