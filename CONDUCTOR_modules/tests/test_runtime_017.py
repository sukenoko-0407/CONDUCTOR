from __future__ import annotations

import importlib.util
import json
import argparse
from datetime import datetime, timedelta, timezone
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "runtime_controller_017",
    ROOT / "CONDUCTOR_modules" / "tools" / "runtime_controller.py",
)
assert SPEC and SPEC.loader
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)


def analysis_node(index: int, status: str) -> dict:
    return {
        "node_id": f"N{index:06d}",
        "kind": "analysis",
        "capability_id": "A001",
        "status": status,
        "created_in_round": "RND0001",
        "assigned_round": "RND0001",
        "input_nodes": [],
        "scope": {"mode": "global"},
        "parameters": {"sample": index},
        "signature": f"sig-{index}",
        "result_quality": {"eligible_for_downstream": status == "succeeded"},
    }


def result_card(index: int, scope_mode: str = "global", cluster_id: str | None = None) -> dict:
    clusters = [cluster_id] if cluster_id else []
    subject = {
        "scope_mode": scope_mode,
        "cluster_ids": clusters,
        "clustering_input_kind": "none" if scope_mode == "global" else "vector",
        "cluster_source_description_nodes": [] if scope_mode == "global" else ["N000010"],
        "analysis_description_nodes": ["N000010"],
        "clustering_nodes": [] if scope_mode == "global" else ["N000020"],
        "population_count": 100,
        "endpoint_valid_count": 100,
        "analyzed_count": 100 if scope_mode == "global" else 20,
        "excluded_count": 0 if scope_mode == "global" else 80,
        "compound_set_hash": f"{index:x}".zfill(64),
    }
    return {
        "schema_version": "2.0.0",
        "result_ref": f"N{index:06d}@ATT0001",
        "node_id": f"N{index:06d}",
        "capability_id": "A001",
        "round_id": "RND0001",
        "analysis_subject": subject,
        "endpoint": {"column": "pIC50", "higher_is_better": True, "unit": None, "transform": None},
        "metric": "pearson",
        "headline": "test card",
        "result_role": "activity_signal",
        "interpretation_profile_id": "IP-A001-1.0.0",
        "comparison_family_id": "CFM0123456789abcdef",
        "favorable_payload": {
            "applicable": True,
            "normalization": "higher_is_better",
            "source_metric": "endpoint_median",
            "raw_value": 5.0,
            "favorable_value": 5.0,
            "favorable_effect": None,
            "direction_confidence": "derived",
        },
        "comparison_metrics": [{
            "name": "endpoint_median", "value": 5.0, "normalized_favorable_value": 5.0,
            "unit": "endpoint", "direction": "favorable", "comparison_scope": "all",
        }],
        "operator_details": {},
        "quality": {
            "population_count": subject["population_count"],
            "endpoint_valid_count": subject["endpoint_valid_count"],
            "analyzed_count": subject["analyzed_count"],
            "excluded_count": subject["excluded_count"],
            "sample_fraction": subject["analyzed_count"] / subject["population_count"],
            "minimum_support_met": True,
        },
        "validation_passed": True,
        "eligible_for_downstream": True,
        "quality_flags": [],
        "limitations": [],
        "artifact_links": {},
        "created_at": "2026-01-01T00:00:00+00:00",
    }


class Runtime017(unittest.TestCase):
    def command(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "CONDUCTOR_modules" / "tools" / "runtime_controller.py"), *arguments],
            cwd=ROOT,
            text=True,
            capture_output=True,
            env=os.environ.copy(),
        )
        if completed.returncode:
            self.fail(completed.stderr or completed.stdout)
        return completed

    def test_assessment_schema_accepts_every_review_bundle_type(self) -> None:
        for bundle_type in ("global", "global_local", "sibling_cluster", "cross_evidence"):
            value = {
                "schema_version": "2.0.0",
                "assessment_id": "ASR0123456789abcdef",
                "bundle_id": "RVB0123456789abcdef",
                "bundle_type": bundle_type,
                "round_id": "RND0001",
                "capability_id": "A003",
                "target_result_refs": ["N000001@ATT0001"],
                "assessment_status": "evaluated",
                "candidate_class": "supporting_evidence",
                "scores": {
                    "favorable_signal": 1,
                    "context_deviation": "not_applicable" if bundle_type == "global" else 1,
                    "chemical_actionability": 1,
                    "independent_support": "not_applicable",
                    "follow_up_leverage": 1,
                },
                "reliability": {
                    "sample_support": "moderate",
                    "comparator_validity": "none" if bundle_type == "global" else "matched",
                    "effect_stability": "unknown",
                    "independence": "unknown",
                    "quality_flags": [],
                },
                "reason": "bounded review priority",
                "supporting_result_refs": ["N000001@ATT0001"],
                "counter_result_refs": [],
                "rubric_version": "2.0.0",
                "source_hash": "0" * 64,
                "revision": 1,
                "created_at": "2026-01-01T00:00:00+00:00",
            }
            RUNTIME.validate(value, "result_assessment.schema.json")

    def test_new_round_plans_only_one_activation_slice(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            control = {"active_round_id": "RND0001", "run": {"run_root": str(root)}}
            snapshot = {
                "nodes": [],
                "counters": {"node": 0},
                "rounds": {"RND0001": {"runtime_version": "0.2.0", "reused_node_ids": []}},
                "plans": {"RND0001": {"basic_compute": True}},
            }
            global_specs = [
                {"capability_id": "A001", "input_nodes": [], "scope": {"mode": "global"}, "parameters": {"sample": index}}
                for index in range(100)
            ]
            local_specs = [
                {"capability_id": "A001", "input_nodes": [], "scope": {"mode": "single_cluster", "cluster_ids": [f"C{index:06d}"]}, "parameters": {"sample": index}}
                for index in range(100)
            ]
            contract = {"budgets": {"max_additional_nodes": 80}}
            with mock.patch.object(RUNTIME, "_active_contract", return_value=contract), mock.patch.object(
                RUNTIME, "_exploration_global_specs", return_value=global_specs
            ), mock.patch.object(RUNTIME, "_exploration_local_specs", return_value=local_specs):
                first = RUNTIME._plan_exploration(root, control, snapshot)
                second = RUNTIME._plan_exploration(root, control, snapshot)
            self.assertEqual(25, len(first))
            self.assertEqual(25, len(second))
            self.assertEqual(50, len(snapshot["nodes"]))
            self.assertEqual(50, snapshot["plans"]["RND0001"]["exploration_nodes_planned"])

    def test_round_parser_defaults_to_screening_but_accepts_full(self) -> None:
        parser = RUNTIME.build_parser()
        default = parser.parse_args([
            "prepare-round", "--run-root", "run", "--objective", "explore",
            "--walltime-minutes", "60",
        ])
        full = parser.parse_args([
            "prepare-round", "--run-root", "run", "--objective", "synthesize",
            "--walltime-minutes", "60", "--report-mode", "full",
        ])
        self.assertEqual("screening", default.report_mode)
        self.assertEqual("full", full.report_mode)

    def test_result_card_normalizes_lower_is_better_endpoint_to_favorable_direction(self) -> None:
        control = {"run": {"endpoint": "IC50", "higher_is_better": False, "endpoint_unit": "nM", "endpoint_transform": None, "input_hash": "0" * 64}}
        node = {"node_id": "N000001", "capability_id": "A001", "assigned_round": "RND0001", "parameters": {}}
        subject = result_card(1)["analysis_subject"]
        summary = {"metric": None, "headline": "distribution", "key_metrics": {"global_median": 25.0}, "limitations": []}
        card = RUNTIME._result_card_v2(control, node, subject, summary, "N000001@ATT0001", {})
        self.assertEqual(25.0, card["favorable_payload"]["raw_value"])
        self.assertEqual(-25.0, card["favorable_payload"]["favorable_value"])
        self.assertNotIn("interest_score", card)

    def test_result_card_marks_missing_profile_metrics_without_inventing_values(self) -> None:
        control = {"run": {"endpoint": "pIC50", "higher_is_better": True, "endpoint_unit": None, "endpoint_transform": None, "input_hash": "0" * 64}}
        node = {"node_id": "N000001", "capability_id": "A001", "assigned_round": "RND0001", "parameters": {}}
        subject = result_card(1)["analysis_subject"]
        summary = {"metric": None, "headline": "distribution", "key_metrics": {}, "limitations": []}
        card = RUNTIME._result_card_v2(control, node, subject, summary, "N000001@ATT0001", {})
        self.assertIsNone(card["favorable_payload"]["favorable_value"])
        self.assertIn("missing_comparison_metrics", card["quality_flags"])
        self.assertIn("missing_primary_favorable_metric", card["quality_flags"])

    def test_bundle_omits_axes_that_have_no_numeric_evidence(self) -> None:
        global_card = result_card(1)
        local_card = result_card(2, "single_cluster", "C000001")
        for card in (global_card, local_card):
            card["favorable_payload"]["raw_value"] = None
            card["favorable_payload"]["favorable_value"] = None
            card["comparison_metrics"][0]["value"] = None
            card["comparison_metrics"][0]["normalized_favorable_value"] = None
        bundle = RUNTIME._make_review_bundle(
            Path("."), "RND0001", "global_local", [local_card], [global_card], "ready"
        )
        self.assertNotIn("favorable_signal", bundle["applicable_axes"])
        self.assertNotIn("context_deviation", bundle["applicable_axes"])

    def test_sibling_bundle_contains_global_baseline_rank_and_variance(self) -> None:
        global_card = result_card(1)
        local_a = result_card(2, "single_cluster", "C000001")
        local_b = result_card(3, "single_cluster", "C000002")
        local_a["favorable_payload"]["favorable_value"] = 6.0
        local_b["favorable_payload"]["favorable_value"] = 4.0
        bundle = RUNTIME._make_review_bundle(
            Path("."), "RND0001", "sibling_cluster", [local_a, local_b], [global_card], "ready"
        )
        rows = {row["result_ref"]: row for row in bundle["comparison_table"]}
        self.assertEqual("matched", bundle["runtime_facts"]["comparator_validity"])
        self.assertEqual(1, rows[local_a["result_ref"]]["sibling_rank"])
        self.assertEqual(2, rows[local_b["result_ref"]]["sibling_rank"])
        self.assertEqual(5.0, rows[local_a["result_ref"]]["sibling_median_favorable_value"])
        self.assertEqual(1.0, rows[local_a["result_ref"]]["sibling_favorable_variance"])

    def test_finalizing_gate_follows_report_mode(self) -> None:
        root = Path("run")
        control = {"active_round_id": "RND0001", "round_state": "FINALIZING", "blocker": None}
        snapshot = {
            "nodes": [],
            "rounds": {"RND0001": {"runtime_version": "0.2.0", "latest_audit": None}},
        }
        with mock.patch.object(RUNTIME, "_pending_screening_bundles", return_value=[]), mock.patch.object(
            RUNTIME, "_screening_summary_fresh", return_value=(False, None)
        ), mock.patch.object(RUNTIME, "_round_report_mode", return_value="screening"):
            self.assertEqual("WRITE_SCREENING_SUMMARY", RUNTIME._required_action(root, control, snapshot)["code"])
        with mock.patch.object(RUNTIME, "_pending_screening_bundles", return_value=[]), mock.patch.object(
            RUNTIME, "_screening_summary_fresh", return_value=(True, "rounds/RND0001/screening_summary.json")
        ), mock.patch.object(RUNTIME, "_round_report_mode", return_value="full"), mock.patch.object(
            RUNTIME, "_interpretation_fresh", return_value=(False, None)
        ):
            self.assertEqual("PLAN_INTERPRETATION", RUNTIME._required_action(root, control, snapshot)["code"])

    def test_analysis_budget_does_not_finalize_a_pending_last_slice(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            control = {"active_round_id": "RND0001"}
            snapshot = {
                "nodes": [*[analysis_node(index, "succeeded") for index in range(1, 50)], analysis_node(50, "pending")],
                "rounds": {"RND0001": {"runtime_version": "0.2.0"}},
                "plans": {"RND0001": {"basic_compute": True}},
            }
            contract = {"budgets": {"max_additional_nodes": 50}, "required_deliverables": []}
            timing = {"soft_stop_reached": False, "deadline_reached": False}
            with mock.patch.object(RUNTIME, "_active_contract", return_value=contract), mock.patch.object(
                RUNTIME, "_round_time", return_value=timing
            ):
                allowed, _reason = RUNTIME._finalize_allowed(root, control, snapshot)
                self.assertFalse(allowed)
                snapshot["nodes"][-1].update({"status": "succeeded", "result_quality": {"eligible_for_downstream": True}})
                allowed, reason = RUNTIME._finalize_allowed(root, control, snapshot)
            self.assertTrue(allowed)
            self.assertEqual("analysis_node_budget_exhausted", reason)

    def test_every_active_round_uses_bundle_screening(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            control = {"active_round_id": "RND0001"}
            snapshot = {"rounds": {"RND0001": {"runtime_version": "0.2.0"}}}
            self.assertTrue(RUNTIME._screening_enabled(root, control, snapshot))
            self.assertEqual("full", RUNTIME._round_report_mode(root, control, snapshot))

    def test_legacy_control_plane_is_rejected_instead_of_silently_upgraded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "input.csv"
            source.write_text("compound_id,smiles,pIC50\nCMP1,CCO,5.1\nCMP2,CCN,5.4\n", encoding="utf-8")
            root = base / "run"
            self.command(
                "init", "--input", str(source), "--endpoint", "pIC50", "--higher-is-better",
                "--project", "test", "--parallel-limit", "1", "--run-id", "legacy-upgrade", "--output-dir", str(root),
            )
            control_path = root / "conductor_control.json"
            control = json.loads(control_path.read_text(encoding="utf-8"))
            control["conductor_version"] = "0.1.6"
            control["pointers"].pop("result_assessment_index", None)
            control_path.write_text(json.dumps(control), encoding="utf-8")
            (root / "runtime" / "result_assessment_index.jsonl").unlink()
            completed = subprocess.run(
                [sys.executable, str(ROOT / "CONDUCTOR_modules" / "tools" / "runtime_controller.py"),
                 "prepare-round", "--run-root", str(root), "--objective", "reject legacy",
                 "--walltime-minutes", "60", "--report-mode", "screening"],
                cwd=ROOT, text=True, capture_output=True, env=os.environ.copy(),
            )
            self.assertNotEqual(0, completed.returncode)
            self.assertIn("is not compatible with CONDUCTOR 0.2.0", completed.stderr)

    def test_synthesis_shortlist_retains_an_explicit_related_comparator(self) -> None:
        current = result_card(2, "single_cluster", "C000001")
        prior = result_card(1)
        bundle = RUNTIME._make_review_bundle(Path("."), "RND0002", "global_local", [current], [prior], "ready")
        assessments = {
            bundle["bundle_id"]: {
                "bundle_id": bundle["bundle_id"], "capability_id": "A001",
                "assessment_status": "evaluated", "candidate_class": "design_lead",
                "scores": {"favorable_signal": 3, "context_deviation": 2, "chemical_actionability": 2, "independent_support": 1, "follow_up_leverage": 2},
                "reliability": {"sample_support": "moderate"},
            }
        }
        manifest = RUNTIME._assessment_review_manifest("RND0002", [bundle], assessments, 2)
        self.assertEqual({current["result_ref"], prior["result_ref"]}, set(manifest["detailed_result_refs"]))

    def test_review_bundles_ignore_orphan_result_cards(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runtime").mkdir()
            target = result_card(2, "single_cluster", "C000001")
            orphan = {**result_card(999999), "result_ref": "N999999@ATT0001", "node_id": "N999999"}
            (root / "runtime" / "result_index.jsonl").write_text(json.dumps(orphan) + "\n", encoding="utf-8")
            (root / "runtime" / "result_index.jsonl").write_text(
                json.dumps(target) + "\n" + json.dumps(orphan) + "\n", encoding="utf-8"
            )
            target_node = analysis_node(2, "succeeded")
            snapshot = {"nodes": [target_node]}
            bundles = RUNTIME._current_round_bundles(root, snapshot, "RND0001")
            self.assertEqual(1, len(bundles))
            self.assertEqual("awaiting_comparator", bundles[0]["comparison_status"])
            self.assertEqual([], bundles[0]["comparator_result_refs"])

    def test_round_assessment_csv_contains_score_components(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            assessment = {
                "assessment_id": "ASR0123456789abcdef",
                "bundle_id": "RVB0123456789abcdef",
                "bundle_type": "global",
                "round_id": "RND0001",
                "capability_id": "A001",
                "target_result_refs": ["N000001@ATT0001"],
                "assessment_status": "evaluated",
                "candidate_class": "supporting_evidence",
                "scores": {"favorable_signal": 1, "context_deviation": "not_applicable", "chemical_actionability": 1, "independent_support": "not_applicable", "follow_up_leverage": 1},
                "reliability": {"sample_support": "moderate", "comparator_validity": "none", "effect_stability": "unknown", "independence": "unknown", "quality_flags": []},
                "reason": "test",
                "supporting_result_refs": ["N000001@ATT0001"],
                "counter_result_refs": [],
                "rubric_version": "2.0.0",
                "source_hash": "0" * 64,
                "revision": 1,
                "created_at": "2026-01-01T00:00:00+00:00",
            }
            (root / "rounds" / "RND0001").mkdir(parents=True)
            with mock.patch.object(RUNTIME, "_round_current_assessments", return_value=[assessment]):
                path = RUNTIME._write_round_assessment_csv(root, {}, "RND0001")
            header, row = path.read_text(encoding="utf-8").splitlines()[:2]
            self.assertIn("follow_up_leverage", header)
            self.assertNotIn("interest_score", header)
            self.assertEqual(len(header.split(",")), len(row.split(",")))

    def test_screening_prepare_and_commit_update_the_index_as_one_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runtime").mkdir()
            (root / "rounds" / "RND0001").mkdir(parents=True)
            (root / "conductor_control.json").write_text("{}\n", encoding="utf-8")
            token = "lease-token"
            card = result_card(1)
            (root / "runtime" / "result_index.jsonl").write_text(json.dumps(card) + "\n", encoding="utf-8")
            control = {
                "active_round_id": "RND0001",
                "required_action": {"code": "PREPARE_RESULT_SCREENING", "reason": "test"},
                "lease": {
                    "owner_id": "test",
                    "token_hash": RUNTIME.value_hash(token),
                    "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
                },
                "run": {"run_id": "RUN1"},
            }
            node = {
                "node_id": "N000001", "kind": "analysis", "status": "succeeded",
                "assigned_round": "RND0001", "created_in_round": "RND0001",
                "result_quality": {"eligible_for_downstream": True},
            }
            snapshot = {
                "nodes": [node],
                "rounds": {"RND0001": {"runtime_version": "0.2.0", "current_screening_batch": None}},
            }
            with mock.patch.object(RUNTIME, "_read_state", return_value=(control, snapshot)), mock.patch.object(
                RUNTIME, "_recover_transaction"
            ), mock.patch.object(RUNTIME, "_commit"), mock.patch.object(
                RUNTIME, "_write_working_set"
            ), mock.patch.object(RUNTIME, "_print_compact"):
                result = RUNTIME.cmd_prepare_result_screening(argparse.Namespace(run_root=str(root), lease_token=token))
                self.assertEqual(0, result)
                batch = snapshot["rounds"]["RND0001"]["current_screening_batch"]
                draft = {
                    "schema_version": "2.0.0",
                    "batch_id": batch["batch_id"],
                    "assessments": [{
                        "bundle_id": json.loads(Path(batch["context_path"]).read_text(encoding="utf-8"))["target_bundle_ids"][0],
                        "assessment_status": "evaluated",
                        "scores": {"favorable_signal": 2, "context_deviation": "not_applicable", "chemical_actionability": "not_applicable", "independent_support": "not_applicable", "follow_up_leverage": 2},
                        "effect_stability": "unknown",
                        "independence": "unknown",
                        "reason": "A bounded result with a useful follow-up candidate.",
                        "supporting_result_refs": [card["result_ref"]],
                        "counter_result_refs": [],
                    }],
                }
                RUNTIME.write_json(Path(batch["draft_path"]), draft)
                control["required_action"] = {"code": "WRITE_RESULT_SCREENING", "reason": "test"}
                result = RUNTIME.cmd_commit_result_screening(argparse.Namespace(
                    run_root=str(root), lease_token=token, batch_id=batch["batch_id"], draft=None,
                ))
            self.assertEqual(0, result)
            rows = RUNTIME.read_jsonl(root / "runtime" / "result_assessment_index.jsonl")
            self.assertEqual(1, len(rows))
            self.assertEqual("supporting_evidence", rows[0]["candidate_class"])
            self.assertEqual(2, rows[0]["scores"]["favorable_signal"])
            self.assertIsNone(snapshot["rounds"]["RND0001"]["current_screening_batch"])
            self.assertTrue((root / "rounds" / "RND0001" / "result_assessments.csv").is_file())


if __name__ == "__main__":
    unittest.main()
