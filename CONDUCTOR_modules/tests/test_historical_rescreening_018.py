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
    "runtime_controller_historical_rescreening_018",
    ROOT / "CONDUCTOR_modules" / "tools" / "runtime_controller.py",
)
assert SPEC and SPEC.loader
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)


def bundle() -> dict:
    return {
        "schema_version": "2.0.0",
        "bundle_id": "RVB0000000000000001",
        "bundle_type": "global",
        "round_id": "RND0001",
        "capability_id": "A001",
        "interpretation_profile_id": "IP-A001-2.0.0",
        "comparison_family_id": "CFM0000000000000001",
        "target_result_refs": ["N000001@ATT0001"],
        "comparator_result_refs": [],
        "all_result_refs": ["N000001@ATT0001"],
        "cluster_ids": [],
        "comparison_status": "ready",
        "applicable_axes": ["favorable_evidence", "evidence_specificity"],
        "evaluation_anchors": {
            "favorable_evidence": ["0", "1", "2", "3"],
            "evidence_specificity": ["0", "1", "2", "3"],
        },
        "comparison_table": [],
        "runtime_facts": {
            "sample_support": "moderate",
            "comparator_validity": "none",
            "overlap_status": "not_applicable",
            "minimum_support_met": True,
        },
        "source_hash": "a" * 64,
        "created_at": "2026-08-26T00:00:00+00:00",
    }


def prepare_args(root: Path) -> argparse.Namespace:
    return argparse.Namespace(
        run_root=str(root), objective="RND0001の一次評価を再実行", report_mode="screening",
        optional_direction=None, human_priority=None, omission=None,
        walltime_minutes=60, parallel_limit=None, available_cpu_cores=None,
        max_additional_nodes=50, interpretation_iterations=3,
        approve_high_cost=False, required_deliverables_json=None,
        cumulative_interpretation=False, historical_rescreening=True,
        source_round_id=["RND0001"], screening_parallelism=3,
    )


class HistoricalRescreeningTests(unittest.TestCase):
    def test_rescreening_prepares_a_bounded_parallel_wave(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runtime").mkdir()
            (root / "conductor_control.json").write_text("{}\n", encoding="utf-8")
            selected = []
            cards = []
            for index in range(7):
                item = bundle()
                item["bundle_id"] = f"RVB{index + 1:016x}"
                item["target_result_refs"] = [f"N{index + 1:06d}@ATT0001"]
                item["all_result_refs"] = list(item["target_result_refs"])
                item["source_hash"] = f"{index + 1:064x}"
                selected.append(item)
                cards.append({"result_ref": item["all_result_refs"][0]})
            control = {
                "active_round_id": "RND0002",
                "round_state": "ACTIVE",
                "run": {"run_id": "RUN1"},
            }
            snapshot = {
                "nodes": [],
                "rounds": {"RND0002": {
                    "current_screening_batch": None,
                    "current_screening_batches": [],
                    "result_rescreening": {
                        "request_id": "HRSCR-RND0002", "status": "active",
                        "batch_size": 2, "screening_parallelism": 3,
                    },
                }},
            }
            args = argparse.Namespace(run_root=str(root), lease_token="lease")
            with mock.patch.object(RUNTIME, "_recover_transaction"), mock.patch.object(
                RUNTIME, "_read_state", return_value=(control, snapshot)
            ), mock.patch.object(RUNTIME, "_require_action"), mock.patch.object(
                RUNTIME, "_pending_screening_bundles", return_value=selected
            ), mock.patch.object(RUNTIME, "_screening_bundles", return_value=selected), mock.patch.object(
                RUNTIME, "_persist_review_bundles"
            ), mock.patch.object(RUNTIME, "_usable_result_cards", return_value=cards), mock.patch.object(
                RUNTIME, "validate"
            ), mock.patch.object(RUNTIME, "_commit"), mock.patch.object(
                RUNTIME, "_write_working_set"
            ), mock.patch.object(RUNTIME, "_print_compact"):
                self.assertEqual(0, RUNTIME.cmd_prepare_result_screening(args))

            prepared = snapshot["rounds"]["RND0002"]["current_screening_batches"]
            self.assertEqual(3, len(prepared))
            self.assertEqual([2, 2, 2], [len(row["target_bundle_ids"]) for row in prepared])
            flattened = [bundle_id for row in prepared for bundle_id in row["target_bundle_ids"]]
            self.assertEqual(6, len(flattened))
            self.assertEqual(6, len(set(flattened)))
            action = RUNTIME._required_action(root, control, snapshot)
            self.assertEqual("WRITE_RESULT_SCREENING", action["code"])
            self.assertEqual(3, action["parallel_batch_count"])
            self.assertEqual(3, len(action["batches"]))

    def test_historical_bundle_loader_uses_frozen_results_and_current_anchors(self) -> None:
        stored = bundle()
        stored.pop("evaluation_anchors")
        with mock.patch.object(RUNTIME, "read_jsonl", return_value=[stored]), mock.patch.object(
            RUNTIME, "_usable_result_cards", return_value=[{"result_ref": "N000001@ATT0001"}]
        ):
            first = RUNTIME._historical_review_bundles(Path("run"), {}, ["RND0001"])
            second = RUNTIME._historical_review_bundles(Path("run"), {}, ["RND0001"])
        self.assertEqual(1, len(first))
        self.assertEqual(first[0]["source_hash"], second[0]["source_hash"])
        self.assertNotEqual(stored["source_hash"], first[0]["source_hash"])
        self.assertEqual(set(first[0]["applicable_axes"]), set(first[0]["evaluation_anchors"]))

    def test_prepare_and_authorize_create_a_screening_only_round(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runtime" / "requests").mkdir(parents=True)
            (root / "rounds").mkdir()
            (root / "conductor_control.json").write_text("{}\n", encoding="utf-8")
            control = {
                "active_round_id": None,
                "next_round_number": 2,
                "run": {"parallel_limit": 2, "available_cpu_cores": 8},
                "pointers": {},
            }
            snapshot = {
                "nodes": [], "plans": {},
                "rounds": {"RND0001": {"state": "CLOSED"}},
            }
            selected = [bundle()]
            with mock.patch.object(RUNTIME, "_recover_transaction"), mock.patch.object(
                RUNTIME, "_read_state", return_value=(control, snapshot)
            ), mock.patch.object(
                RUNTIME, "_historical_review_bundles", return_value=selected
            ), mock.patch.object(RUNTIME.secrets, "token_hex", return_value="auth-token"), mock.patch.object(
                RUNTIME, "_print_compact"
            ):
                self.assertEqual(0, RUNTIME.cmd_prepare_round(prepare_args(root)))

            request_path = next((root / "runtime" / "requests").glob("RND0002_*.json"))
            contract = json.loads(request_path.read_text(encoding="utf-8"))["contract"]
            self.assertEqual("historical_closed_rounds", contract["screening_scope"])
            self.assertEqual(["RND0001"], contract["source_round_ids"])
            self.assertEqual([selected[0]["bundle_id"]], contract["target_bundle_ids"])
            self.assertEqual(0, contract["budgets"]["max_additional_nodes"])
            self.assertEqual(3, contract["budgets"]["screening_parallelism"])
            self.assertEqual(["screening_completed"], [row["type"] for row in contract["required_deliverables"]])

            authorize = argparse.Namespace(
                run_root=str(root), control_key="control", request_file=str(request_path),
                authorization_token="auth-token",
            )
            with mock.patch.object(RUNTIME, "_require_control_authority"), mock.patch.object(
                RUNTIME, "_recover_transaction"
            ), mock.patch.object(RUNTIME, "_read_state", return_value=(control, snapshot)), mock.patch.object(
                RUNTIME, "_historical_review_bundles", return_value=selected
            ), mock.patch.object(RUNTIME, "_commit"), mock.patch.object(RUNTIME, "_print_compact"):
                self.assertEqual(0, RUNTIME.cmd_authorize_round(authorize))

            record = snapshot["rounds"]["RND0002"]
            self.assertEqual("historical_closed_rounds", record["screening_scope"])
            self.assertTrue(record["human_checkpoint_requested"])
            self.assertEqual("active", record["result_rescreening"]["status"])
            self.assertEqual(3, record["result_rescreening"]["screening_parallelism"])
            self.assertEqual([selected[0]["bundle_id"]], record["result_rescreening"]["target_bundle_ids"])
            self.assertEqual([], snapshot["nodes"])
            self.assertEqual(0, snapshot["plans"]["RND0002"]["analysis_node_limit"])

    def test_historical_round_forces_old_current_assessment_into_screening(self) -> None:
        selected = bundle()
        snapshot = {
            "rounds": {
                "RND0002": {
                    "screening_scope": "historical_closed_rounds",
                    "source_round_ids": ["RND0001"],
                    "target_bundle_ids": [selected["bundle_id"]],
                    "result_rescreening": {
                        "status": "active",
                        "target_bundle_ids": [selected["bundle_id"]],
                    },
                }
            }
        }
        previous = {
            "bundle_id": selected["bundle_id"], "source_hash": selected["source_hash"],
            "rubric_version": RUNTIME.SCREENING_RUBRIC_VERSION,
            "assessment_status": "evaluated",
        }
        with mock.patch.object(RUNTIME, "_historical_review_bundles", return_value=[selected]), mock.patch.object(
            RUNTIME, "_latest_assessments", return_value={selected["bundle_id"]: previous}
        ):
            pending = RUNTIME._pending_screening_bundles(Path("run"), snapshot, "RND0002")
        self.assertEqual([selected["bundle_id"]], [row["bundle_id"] for row in pending])

    def test_required_action_never_enters_scientific_planning(self) -> None:
        control = {"active_round_id": "RND0002", "round_state": "ACTIVE", "blocker": None}
        snapshot = {
            "nodes": [],
            "rounds": {"RND0002": {
                "screening_scope": "historical_closed_rounds",
                "human_checkpoint_requested": True,
                "current_screening_batch": None,
            }},
            "plans": {"RND0002": {"basic_compute": False, "exploration": False}},
        }
        with mock.patch.object(RUNTIME, "_screening_enabled", return_value=True), mock.patch.object(
            RUNTIME, "_pending_screening_bundles", return_value=[bundle()]
        ):
            action = RUNTIME._required_action(Path("run"), control, snapshot)
        self.assertEqual("PREPARE_RESULT_SCREENING", action["code"])

        with mock.patch.object(RUNTIME, "_screening_enabled", return_value=True), mock.patch.object(
            RUNTIME, "_pending_screening_bundles", return_value=[]
        ):
            action = RUNTIME._required_action(Path("run"), control, snapshot)
        self.assertEqual("ENTER_FINALIZING", action["code"])

    def test_committed_revision_records_source_and_execution_rounds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scratch = root / "runtime" / "scratch"
            scratch.mkdir(parents=True)
            (root / "conductor_control.json").write_text("{}\n", encoding="utf-8")
            selected = bundle()
            context_path = scratch / "context.json"
            draft_path = scratch / "draft.json"
            context = {
                "target_bundle_ids": [selected["bundle_id"]],
                "allowed_result_refs": selected["all_result_refs"],
                "review_bundles": [selected],
                "result_cards": [{"result_ref": "N000001@ATT0001", "quality_flags": []}],
            }
            draft = {
                "schema_version": "3.0.0", "batch_id": "SCR0000000000000001",
                "assessments": [{
                    "bundle_id": selected["bundle_id"], "assessment_status": "evaluated",
                    "scores": {
                        "favorable_evidence": 2, "context_contrast": "not_applicable",
                        "evidence_specificity": 1,
                    },
                    "effect_stability": "stable", "independence": "unknown",
                    "reason": "A001のfavorable metric 0.62を根拠とする再評価です。",
                    "supporting_result_refs": ["N000001@ATT0001"], "counter_result_refs": [],
                }],
            }
            context_path.write_text(json.dumps(context), encoding="utf-8")
            draft_path.write_text(json.dumps(draft), encoding="utf-8")
            control = {"active_round_id": "RND0002", "round_state": "ACTIVE", "blocker": None}
            other_batch = {
                "batch_id": "SCRffffffffffffffff", "context_path": str(scratch / "other_context.json"),
                "draft_path": str(scratch / "other_draft.json"), "attempts": 0,
            }
            selected_batch = {
                "batch_id": draft["batch_id"], "context_path": str(context_path),
                "draft_path": str(draft_path), "attempts": 0,
            }
            snapshot = {
                "rounds": {"RND0002": {
                    "current_screening_batch": other_batch,
                    "current_screening_batches": [other_batch, selected_batch],
                    "result_rescreening": {"status": "active", "target_bundle_ids": [selected["bundle_id"]]},
                    "screening_summary_ref": None,
                }}
            }
            old = {
                "bundle_id": selected["bundle_id"], "revision": 1,
                "reason": "以前の評価", "source_hash": selected["source_hash"],
                "assessment_status": "evaluated", "scores": draft["assessments"][0]["scores"],
                "reliability": {"effect_stability": "mixed", "independence": "unknown"},
            }
            args = argparse.Namespace(
                run_root=str(root), lease_token="lease", batch_id=draft["batch_id"], draft=None,
            )
            with mock.patch.object(RUNTIME, "_recover_transaction"), mock.patch.object(
                RUNTIME, "_read_state", return_value=(control, snapshot)
            ), mock.patch.object(RUNTIME, "_require_action"), mock.patch.object(
                RUNTIME, "_latest_assessments", return_value={selected["bundle_id"]: old}
            ), mock.patch.object(RUNTIME, "_write_round_assessment_csv", return_value=root / "rounds" / "RND0002" / "result_assessments.csv"), mock.patch.object(
                RUNTIME, "_pending_screening_bundles", return_value=[]
            ), mock.patch.object(RUNTIME, "_commit"), mock.patch.object(
                RUNTIME, "_write_working_set"
            ), mock.patch.object(RUNTIME, "_print_compact"):
                self.assertEqual(0, RUNTIME.cmd_commit_result_screening(args))

            rows = RUNTIME.read_jsonl(root / "runtime" / "result_assessment_index.jsonl")
            self.assertEqual(1, len(rows))
            self.assertEqual("RND0002", rows[0]["round_id"])
            self.assertEqual("RND0001", rows[0]["source_round_id"])
            self.assertEqual(2, rows[0]["revision"])
            self.assertEqual([other_batch], snapshot["rounds"]["RND0002"]["current_screening_batches"])
            self.assertEqual(other_batch, snapshot["rounds"]["RND0002"]["current_screening_batch"])

    def test_parser_requires_explicit_historical_mode(self) -> None:
        args = RUNTIME.build_parser().parse_args([
            "prepare-round", "--run-root", "run", "--objective", "rescreen",
            "--historical-rescreening", "--source-round-id", "RND0001",
            "--source-round-id", "RND0003", "--screening-parallelism", "4",
        ])
        self.assertTrue(args.historical_rescreening)
        self.assertFalse(args.cumulative_interpretation)
        self.assertEqual(["RND0001", "RND0003"], args.source_round_id)
        self.assertEqual(4, args.screening_parallelism)


if __name__ == "__main__":
    unittest.main()
