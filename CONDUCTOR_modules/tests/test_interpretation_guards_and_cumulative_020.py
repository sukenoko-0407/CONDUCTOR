from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "runtime_controller_interpretation_guards_020",
    ROOT / "CONDUCTOR_modules" / "tools" / "runtime_controller.py",
)
assert SPEC and SPEC.loader
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)


def assessment(bundle_id: str, source_hash: str, round_id: str, reason: str) -> dict:
    return {
        "bundle_id": bundle_id,
        "capability_id": "A001",
        "source_hash": source_hash,
        "round_id": round_id,
        "rubric_version": RUNTIME.SCREENING_RUBRIC_VERSION,
        "assessment_status": "evaluated",
        "candidate_class": "design_lead",
        "scores": {
            "favorable_signal": 2,
            "context_deviation": "not_applicable",
            "chemical_actionability": 2,
            "independent_support": "not_applicable",
            "follow_up_leverage": 1,
        },
        "reliability": {"sample_support": "moderate"},
        "effect_stability": "stable",
        "independence": "unknown",
        "reason": reason,
        "supporting_result_refs": [],
        "counter_result_refs": [],
        "revision": 1,
    }


def draft_row(bundle_id: str, result_ref: str, reason: str) -> dict:
    return {
        "bundle_id": bundle_id,
        "assessment_status": "evaluated",
        "scores": {
            "favorable_signal": 2,
            "context_deviation": "not_applicable",
            "chemical_actionability": 2,
            "independent_support": "not_applicable",
            "follow_up_leverage": 1,
        },
        "effect_stability": "stable",
        "independence": "unknown",
        "reason": reason,
        "supporting_result_refs": [result_ref] if result_ref else [],
        "counter_result_refs": [],
    }


class InterpretationGuardAndCumulativeTests(unittest.TestCase):
    def test_screening_rejects_an_assessment_without_a_result_basis(self) -> None:
        row = draft_row("RVB0000000000000001", "", "A001のmetric値に基づく固有評価です。")
        with self.assertRaisesRegex(ValueError, "cite at least one Bundle Result"):
            RUNTIME._reject_ungrounded_or_duplicated_assessments([row], {})

    def test_screening_rejects_template_content_across_different_bundles(self) -> None:
        reason = "同じ定型文と同じ採点を複製した評価内容です。"
        rows = [
            draft_row("RVB0000000000000001", "N000001@ATT0001", reason),
            draft_row("RVB0000000000000002", "N000002@ATT0001", reason),
        ]
        with self.assertRaisesRegex(ValueError, "Template-like duplicate"):
            RUNTIME._reject_ungrounded_or_duplicated_assessments(rows, {})

    def test_screening_accepts_same_scores_with_bundle_specific_reasons(self) -> None:
        rows = [
            draft_row("RVB0000000000000001", "N000001@ATT0001", "A001のendpoint_median 6.2を根拠とする評価です。"),
            draft_row("RVB0000000000000002", "N000002@ATT0001", "A003のRMSE改善0.4を根拠とする評価です。"),
        ]
        RUNTIME._reject_ungrounded_or_duplicated_assessments(rows, {})

    def test_cumulative_evidence_excludes_bundles_used_by_formal_insights(self) -> None:
        hash_one, hash_two = "1" * 64, "2" * 64
        bundle_one = {
            "bundle_id": "RVB0000000000000001", "source_hash": hash_one,
            "all_result_refs": ["N000001@ATT0001"], "round_id": "RND0001",
        }
        bundle_two = {
            "bundle_id": "RVB0000000000000002", "source_hash": hash_two,
            "all_result_refs": ["N000002@ATT0001"], "round_id": "RND0002",
        }
        assessments = {
            bundle_one["bundle_id"]: assessment(bundle_one["bundle_id"], hash_one, "RND0001", "first specific reason"),
            bundle_two["bundle_id"]: assessment(bundle_two["bundle_id"], hash_two, "RND0002", "second specific reason"),
        }
        # A historical re-Screening revision is executed in a later maintenance
        # Round but remains scientifically attributed to its original source.
        assessments[bundle_two["bundle_id"]]["round_id"] = "RND0003"
        assessments[bundle_two["bundle_id"]]["source_round_id"] = "RND0002"
        insight = {
            "insight_id": "INS000001", "revision": 1, "title": "既報知見",
            "review_bundle_ids": [bundle_one["bundle_id"]],
        }

        def fake_read_jsonl(path: Path) -> list[dict]:
            name = Path(path).name
            if name == "review_bundle_index.jsonl":
                return [bundle_one, bundle_two]
            if name == "insight_index.jsonl":
                return [insight]
            return []

        cards = [
            {"result_ref": "N000001@ATT0001"},
            {"result_ref": "N000002@ATT0001"},
        ]
        with mock.patch.object(RUNTIME, "_latest_assessments", return_value=assessments), mock.patch.object(
            RUNTIME, "read_jsonl", side_effect=fake_read_jsonl
        ), mock.patch.object(RUNTIME, "_usable_result_cards", return_value=cards):
            bundles, selected, metadata, prior = RUNTIME._cumulative_interpretation_evidence(
                Path("run"), {"nodes": []}, ["RND0001", "RND0002"]
            )

        self.assertEqual([bundle_two["bundle_id"]], [row["bundle_id"] for row in bundles])
        self.assertEqual([bundle_two["bundle_id"]], list(selected))
        self.assertEqual(2, metadata["source_assessment_count"])
        self.assertEqual(1, metadata["previously_reported_count"])
        self.assertEqual([bundle_one["bundle_id"]], metadata["excluded_previously_reported_bundle_ids"])
        self.assertEqual("既報知見", prior[0]["title"])

    def test_prepare_round_builds_a_report_only_cumulative_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runtime").mkdir()
            (root / "conductor_control.json").write_text("{}\n", encoding="utf-8")
            control = {
                "active_round_id": None,
                "next_round_number": 3,
                "run": {"parallel_limit": 2, "available_cpu_cores": 8},
            }
            snapshot = {
                "nodes": [],
                "rounds": {
                    "RND0001": {"state": "CLOSED"},
                    "RND0002": {"state": "CLOSED"},
                },
            }
            args = argparse.Namespace(
                run_root=str(root), objective="累積Interpretation", report_mode="full",
                optional_direction=None, human_priority=None, omission=None,
                walltime_minutes=60, parallel_limit=None, available_cpu_cores=None,
                max_additional_nodes=50, interpretation_iterations=3,
                approve_high_cost=False, required_deliverables_json=None,
                cumulative_interpretation=True, source_round_id=None,
            )
            with mock.patch.object(RUNTIME, "_recover_transaction"), mock.patch.object(
                RUNTIME, "_read_state", return_value=(control, snapshot)
            ), mock.patch.object(RUNTIME, "_print_compact"):
                result = RUNTIME.cmd_prepare_round(args)
            self.assertEqual(0, result)
            request_path = next((root / "runtime" / "requests").glob("RND0003_*.json"))
            contract = json.loads(request_path.read_text(encoding="utf-8"))["contract"]
            self.assertEqual("cumulative_unreported", contract["interpretation_scope"])
            self.assertEqual(["RND0001", "RND0002"], contract["source_round_ids"])
            self.assertEqual(0, contract["budgets"]["max_additional_nodes"])
            self.assertEqual(["interpretation_completed"], [row["type"] for row in contract["required_deliverables"]])

    def test_prepare_interpretation_writes_a_cumulative_unreported_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runtime").mkdir()
            (root / "conductor_control.json").write_text("{}\n", encoding="utf-8")
            bundle_id = "RVB0000000000000002"
            result_ref = "N000002@ATT0001"
            bundle = {
                "bundle_id": bundle_id, "bundle_type": "global", "capability_id": "A001",
                "all_result_refs": [result_ref], "target_result_refs": [result_ref],
                "source_hash": "2" * 64,
            }
            assessed = assessment(bundle_id, "2" * 64, "RND0002", "A001のmetric値に基づく固有評価です。")
            card = {"result_ref": result_ref, "node_id": "N000002"}
            metadata = {
                "interpretation_scope": "cumulative_unreported",
                "source_round_ids": ["RND0001", "RND0002"],
                "source_assessment_count": 8,
                "previously_reported_count": 3,
                "unavailable_or_stale_count": 0,
                "excluded_previously_reported_bundle_ids": ["RVB0000000000000001"],
            }
            prior = [{"insight_id": "INS000001", "title": "既報知見", "review_bundle_ids": ["RVB0000000000000001"]}]
            control = {
                "active_round_id": "RND0003", "round_state": "FINALIZING",
                "run": {"run_id": "RUN1", "project": "p", "endpoint": "pIC50", "higher_is_better": True},
            }
            snapshot = {
                "nodes": [], "counters": {"node": 0, "cluster": 0, "insight": 1},
                "rounds": {"RND0003": {"interpretation_scope": "cumulative_unreported", "source_round_ids": ["RND0001", "RND0002"], "interpretation_revision_serial": 0}},
            }
            node = {
                "node_id": "N000003", "kind": "interpretation", "parameters": {},
                "output_ref": str(root / "rounds" / "RND0003" / "interpretation" / "I001"),
            }
            args = argparse.Namespace(
                run_root=str(root), lease_token="lease", focus=None,
                rereview_result_ref=None, detailed_limit=50,
            )
            with mock.patch.object(RUNTIME, "_recover_transaction"), mock.patch.object(
                RUNTIME, "_read_state", return_value=(control, snapshot)
            ), mock.patch.object(RUNTIME, "_require_action"), mock.patch.object(
                RUNTIME, "_usable_result_cards", return_value=[card]
            ), mock.patch.object(
                RUNTIME, "_cumulative_interpretation_evidence",
                return_value=([bundle], {bundle_id: assessed}, metadata, prior),
            ), mock.patch.object(RUNTIME, "_add_node", return_value=(node, True)), mock.patch.object(
                RUNTIME, "_commit"
            ), mock.patch.object(RUNTIME, "_write_working_set"), mock.patch.object(
                RUNTIME, "_print_compact"
            ):
                result = RUNTIME.cmd_prepare_interpretation(args)
            self.assertEqual(0, result)
            context = json.loads(Path(node["parameters"]["context_path"]).read_text(encoding="utf-8"))
            self.assertEqual("cumulative_unreported", context["interpretation_scope"])
            self.assertEqual(["RND0001", "RND0002"], context["review_manifest"]["source_round_ids"])
            self.assertEqual(3, context["review_manifest"]["previously_reported_count"])
            self.assertEqual("既報知見", context["prior_reported_insights"][0]["title"])
            self.assertEqual([bundle_id], context["review_manifest"]["selected_bundle_ids"])

    def test_cumulative_parser_options_are_public(self) -> None:
        args = RUNTIME.build_parser().parse_args([
            "prepare-round", "--run-root", "run", "--objective", "report",
            "--report-mode", "full", "--cumulative-interpretation",
            "--source-round-id", "RND0001",
        ])
        self.assertTrue(args.cumulative_interpretation)
        self.assertEqual(["RND0001"], args.source_round_id)


if __name__ == "__main__":
    unittest.main()
