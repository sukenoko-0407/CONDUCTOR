from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNTIME = load(ROOT / "CONDUCTOR_modules" / "tools" / "runtime_controller.py", "runtime_renderer_contract_018")
RENDERER = load(ROOT / "CONDUCTOR_modules" / "tools" / "templates" / "interpretation_render.py", "interpretation_renderer_contract_018")


class InterpretationRendererContract018(unittest.TestCase):
    def test_runtime_manifest_v2_renders_without_legacy_fields(self) -> None:
        selected_id = "RVB0000000000000001"
        unselected_id = "RVB0000000000000002"
        bundles = [
            {"bundle_id": selected_id, "bundle_type": "global", "capability_id": "A001", "all_result_refs": ["N000001@ATT0001"]},
            {"bundle_id": unselected_id, "bundle_type": "global_local", "capability_id": "A002", "all_result_refs": ["N000002@ATT0001"]},
        ]
        assessments = {
            selected_id: {
                "bundle_id": selected_id, "capability_id": "A001", "candidate_class": "favorable_clue",
                "scores": {"favorable_evidence": 3, "context_contrast": "not_applicable", "evidence_specificity": 3}, "reliability": {"sample_support": "strong"},
            },
            unselected_id: {
                "bundle_id": unselected_id, "capability_id": "A002", "candidate_class": "supporting_evidence",
                "scores": {"favorable_evidence": 0, "context_contrast": 1, "evidence_specificity": 2}, "reliability": {"sample_support": "moderate"},
            },
        }
        manifest = RUNTIME._assessment_review_manifest("RND0001", bundles, assessments, 10)
        self.assertNotIn("aggregate_result_refs", manifest)
        self.assertNotIn("unreviewed_results", manifest)
        self.assertNotIn("scope_counts", manifest)
        report = {
            "title": "CONDUCTOR解析結果",
            "run_id": "RUN-DEMO",
            "round_id": "RND0001",
            "report_header": {
                "endpoint": "pIC50", "higher_is_better": True, "endpoint_unit": None,
                "endpoint_transform": None, "completion": "complete",
            },
            "executive_summary": "一次評価で選ばれた候補を、現行Review Bundle契約に従って表示する。",
            "coverage_summary": "Runtimeが選択したReview Bundleと未選択Bundleの範囲を表示する。",
            "insights": [],
            "result_catalog": [],
            "review_manifest": manifest,
        }
        markdown = RENDERER.render_markdown(report)
        rendered_html = RENDERER.render_html(report)
        self.assertIn("選択Review Bundle: 1", markdown)
        self.assertIn("未選択Review Bundle", markdown)
        self.assertIn(unselected_id, markdown + rendered_html)
        self.assertIn("Bundle 1 / Result 1 / 未選択 1", rendered_html)


if __name__ == "__main__":
    unittest.main()
