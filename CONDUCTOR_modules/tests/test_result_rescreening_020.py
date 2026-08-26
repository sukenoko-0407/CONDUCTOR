from __future__ import annotations

import argparse
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "runtime_controller_result_rescreening_020",
    ROOT / "CONDUCTOR_modules" / "tools" / "runtime_controller.py",
)
assert SPEC and SPEC.loader
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)


def review_bundle(bundle_id: str = "RVB0000000000000001") -> dict:
    return {
        "bundle_id": bundle_id,
        "comparison_status": "ready",
        "capability_id": "A001",
        "bundle_type": "global",
        "source_hash": "a" * 64,
    }


class ResultRescreeningTests(unittest.TestCase):
    def test_active_request_forces_a_current_assessment_back_into_screening(self) -> None:
        bundle = review_bundle()
        assessment = {
            "bundle_id": bundle["bundle_id"],
            "source_hash": bundle["source_hash"],
            "rubric_version": RUNTIME.SCREENING_RUBRIC_VERSION,
            "assessment_status": "evaluated",
        }
        snapshot = {
            "rounds": {
                "RND0001": {
                    "result_rescreening": {
                        "status": "active",
                        "target_bundle_ids": [bundle["bundle_id"]],
                    }
                }
            }
        }
        with mock.patch.object(RUNTIME, "_current_round_bundles", return_value=[bundle]), mock.patch.object(
            RUNTIME, "_latest_assessments", return_value={bundle["bundle_id"]: assessment}
        ):
            pending = RUNTIME._pending_screening_bundles(Path("run"), snapshot, "RND0001")
            self.assertEqual([bundle["bundle_id"]], [item["bundle_id"] for item in pending])

            snapshot["rounds"]["RND0001"]["result_rescreening"]["status"] = "completed"
            self.assertEqual([], RUNTIME._pending_screening_bundles(Path("run"), snapshot, "RND0001"))

    def test_request_all_current_reopens_same_awaiting_round_without_new_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runtime").mkdir()
            (root / "conductor_control.json").write_text("{}\n", encoding="utf-8")
            bundles = [review_bundle("RVB0000000000000001"), review_bundle("RVB0000000000000002")]
            control = {
                "active_round_id": "RND0001",
                "round_state": "AWAITING_HUMAN_REVIEW",
                "blocker": None,
                "closure": {"contract_satisfied": True},
            }
            snapshot = {
                "nodes": [],
                "rounds": {
                    "RND0001": {
                        "state": "AWAITING_HUMAN_REVIEW",
                        "report_mode": "full",
                        "current_screening_batch": None,
                        "result_rescreening_serial": 0,
                        "interpretation_revision_serial": 0,
                    }
                },
            }
            args = argparse.Namespace(
                run_root=str(root),
                control_key="human-key",
                all_current=True,
                bundle_id=None,
                batch_size=4,
                additional_walltime_minutes=60,
                reason="Screening was incomplete in this Round",
            )
            with mock.patch.object(RUNTIME, "_require_control_authority"), mock.patch.object(
                RUNTIME, "_recover_transaction"
            ), mock.patch.object(RUNTIME, "_read_state", return_value=(control, snapshot)), mock.patch.object(
                RUNTIME, "_current_round_bundles", return_value=bundles
            ), mock.patch.object(RUNTIME, "_round_report_mode", return_value="full"), mock.patch.object(
                RUNTIME, "_commit"
            ) as commit, mock.patch.object(RUNTIME, "_write_working_set"), mock.patch.object(
                RUNTIME, "_print_compact"
            ):
                result = RUNTIME.cmd_request_result_rescreening(args)

            self.assertEqual(0, result)
            self.assertEqual("ACTIVE", control["round_state"])
            self.assertEqual("ACTIVE", snapshot["rounds"]["RND0001"]["state"])
            request = snapshot["rounds"]["RND0001"]["result_rescreening"]
            self.assertEqual("RSCR0001", request["request_id"])
            self.assertEqual(4, request["batch_size"])
            self.assertEqual([bundle["bundle_id"] for bundle in bundles], request["target_bundle_ids"])
            self.assertTrue(snapshot["rounds"]["RND0001"]["interpretation_revision_required"])
            self.assertTrue(snapshot["rounds"]["RND0001"]["human_checkpoint_requested"])
            self.assertEqual([], snapshot["nodes"])
            self.assertEqual("result_rescreening_requested", commit.call_args.args[3])

    def test_request_rejects_a_closed_round(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runtime").mkdir()
            (root / "conductor_control.json").write_text("{}\n", encoding="utf-8")
            control = {"active_round_id": "RND0001", "round_state": "CLOSED"}
            snapshot = {"nodes": [], "rounds": {"RND0001": {}}}
            args = argparse.Namespace(
                run_root=str(root), control_key="human-key", all_current=True,
                bundle_id=None, batch_size=4, additional_walltime_minutes=None, reason="test",
            )
            with mock.patch.object(RUNTIME, "_require_control_authority"), mock.patch.object(
                RUNTIME, "_recover_transaction"
            ), mock.patch.object(RUNTIME, "_read_state", return_value=(control, snapshot)):
                with self.assertRaisesRegex(ValueError, "historical re-Screening Round"):
                    RUNTIME.cmd_request_result_rescreening(args)

    def test_request_can_reopen_finalizing_for_rescreening_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runtime").mkdir()
            (root / "conductor_control.json").write_text("{}\n", encoding="utf-8")
            item = review_bundle()
            control = {
                "active_round_id": "RND0001", "round_state": "FINALIZING",
                "blocker": None, "closure": {"contract_satisfied": False},
            }
            snapshot = {
                "nodes": [],
                "rounds": {"RND0001": {
                    "state": "FINALIZING", "report_mode": "screening",
                    "current_screening_batch": None, "current_screening_batches": [],
                    "result_rescreening_serial": 0,
                }},
            }
            args = argparse.Namespace(
                run_root=str(root), control_key="human-key", all_current=True,
                bundle_id=None, batch_size=4, screening_parallelism=2,
                additional_walltime_minutes=45, reason="repair screening",
            )
            with mock.patch.object(RUNTIME, "_require_control_authority"), mock.patch.object(
                RUNTIME, "_recover_transaction"
            ), mock.patch.object(RUNTIME, "_read_state", return_value=(control, snapshot)), mock.patch.object(
                RUNTIME, "_current_round_bundles", return_value=[item]
            ), mock.patch.object(RUNTIME, "_round_report_mode", return_value="screening"), mock.patch.object(
                RUNTIME, "_commit"
            ), mock.patch.object(RUNTIME, "_write_working_set"), mock.patch.object(
                RUNTIME, "_print_compact"
            ):
                self.assertEqual(0, RUNTIME.cmd_request_result_rescreening(args))
            self.assertEqual("ACTIVE", control["round_state"])
            self.assertEqual("ACTIVE", snapshot["rounds"]["RND0001"]["state"])
            self.assertEqual(2, snapshot["rounds"]["RND0001"]["result_rescreening"]["screening_parallelism"])

    def test_parser_exposes_bounded_human_authorized_command(self) -> None:
        args = RUNTIME.build_parser().parse_args([
            "request-result-rescreening",
            "--run-root", "run",
            "--control-key", "key",
            "--all-current",
            "--reason", "redo",
        ])
        self.assertIs(args.func, RUNTIME.cmd_request_result_rescreening)
        self.assertEqual(4, args.batch_size)
        self.assertEqual(1, args.screening_parallelism)
        self.assertTrue(args.all_current)


if __name__ == "__main__":
    unittest.main()
