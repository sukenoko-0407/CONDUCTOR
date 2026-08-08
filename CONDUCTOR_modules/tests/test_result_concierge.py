from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / ".claude" / "skills" / "cs-conductor-result-concierge" / "scripts" / "run.py"


class ResultConciergeTests(unittest.TestCase):
    def invoke(self, *arguments: str, expected: int = 0) -> tuple[dict, subprocess.CompletedProcess[str]]:
        completed = subprocess.run(
            [sys.executable, str(RUNNER), *arguments],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(expected, completed.returncode, completed.stderr or completed.stdout)
        stream = completed.stdout if completed.returncode == 0 else completed.stderr
        return json.loads(stream), completed

    def make_run(self, directory: Path, *, active: bool = False) -> Path:
        run_root = directory / "RUN001"
        interpretation_dir = run_root / "interpretation" / "I001"
        operator_dir = run_root / "analysis" / "NO0001"
        interpretation_dir.mkdir(parents=True)
        operator_dir.mkdir(parents=True)
        (interpretation_dir / "interpretation.md").write_text("# Finding F001\nGlobalとG000001の差。\n", encoding="utf-8")
        (operator_dir / "evidence_digest.json").write_text(
            json.dumps({"evidence_id": "E000001", "value": 0.42}, ensure_ascii=False), encoding="utf-8"
        )
        state = {
            "schema_version": "2.1.0",
            "conductor_version": "4.3.1",
            "run": {"run_id": "RUN001", "project": "TEST"},
            "round_control": {
                "active_round_id": "RND0002" if active else None,
                "next_round_number": 3,
                "rounds": [{"round_id": "RND0001", "number": 1, "status": "completed"}],
            },
            "orchestration_control": {
                "lease": {"owner_id": None, "expires_at": None},
            },
            "execution_graph": {
                "nodes": [
                    {
                        "node_id": "NI0001",
                        "round_id": "RND0001",
                        "stage": "interpretation",
                        "status": "succeeded",
                        "output_dir": str(interpretation_dir),
                    },
                    {
                        "node_id": "NO0001",
                        "round_id": "RND0001",
                        "stage": "analysis",
                        "status": "succeeded",
                        "output_dir": str(operator_dir),
                    },
                ],
                "edges": [],
            },
            "indices": {},
            "history": [],
            "updated_at": "2026-08-08T00:00:00Z",
        }
        state_path = run_root / "state.json"
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        return state_path

    def test_prepare_finalize_and_verify_leave_state_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = self.make_run(Path(directory))
            before = state_path.read_bytes()
            prepared, _ = self.invoke(
                "prepare", "--state", str(state_path), "--request", "F001を詳しく説明する",
                "--focus-id", "F001", "--explicit-request",
            )
            request_dir = Path(prepared["request_dir"])
            self.assertEqual("CRQ000001", request_dir.name)
            self.assertTrue((request_dir / "state_snapshot.json").is_file())
            self.assertTrue((request_dir / "run_inventory.json").is_file())
            context = json.loads((request_dir / "context.json").read_text(encoding="utf-8"))
            self.assertEqual(["F001"], context["focus_ids"])
            self.assertTrue(context["focus_matches"])

            evidence = state_path.parent / "analysis" / "NO0001" / "evidence_digest.json"
            added, _ = self.invoke("add-source", "--request-dir", str(request_dir), "--source", str(evidence))
            self.assertEqual(["analysis/NO0001/evidence_digest.json"], added["added"])

            draft_path = request_dir / "response_draft.json"
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            draft.update(
                {
                    "title": "F001の根拠確認",
                    "request_summary": "F001を詳しく説明する",
                    "answer_markdown": "F001はGlobalと局所Groupの差を示す。**既存Evidenceの範囲**で確認した。",
                    "source_paths": ["state.json", "interpretation/I001/interpretation.md", "analysis/NO0001/evidence_digest.json"],
                    "figures": [
                        {
                            "figure_id": "FIG001",
                            "kind": "bar",
                            "title": "既存値の比較",
                            "x": ["Global", "G000001"],
                            "y": [0.8, 0.42],
                            "x_label": "Scope",
                            "y_label": "Observed score",
                            "caption": "新規解析ではなく既存値の再表現。",
                            "source_paths": ["analysis/NO0001/evidence_digest.json"],
                        }
                    ],
                    "limitations": ["因果関係は示さない。"],
                    "suggested_next_round_prompt": "次RoundではF001の反証候補を優先してください。",
                }
            )
            draft_path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
            finalized, _ = self.invoke("finalize", "--request-dir", str(request_dir))
            self.assertEqual("completed", finalized["status"])
            self.assertEqual(before, state_path.read_bytes())
            self.assertTrue((request_dir / "response.md").is_file())
            self.assertTrue((request_dir / "figures" / "FIG001.svg").is_file())
            html_text = (request_dir / "response.html").read_text(encoding="utf-8")
            self.assertIn("data:image/svg+xml;base64,", html_text)
            self.assertIn("State/DAGには登録されていません", html_text)
            verified, _ = self.invoke("verify", "--request-dir", str(request_dir))
            self.assertEqual("pass", verified["status"])
            self.assertTrue(verified["outputs_valid"])
            self.assertTrue(verified["sources_unchanged_since_prepare"])
            self.assertTrue(verified["run_files_unchanged_since_prepare"])

    def test_prepare_refuses_active_round(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = self.make_run(Path(directory), active=True)
            result, _ = self.invoke(
                "prepare", "--state", str(state_path), "--request", "確認する", "--explicit-request", expected=1,
            )
            self.assertEqual("error", result["status"])
            self.assertIn("active Round exists", result["error"])
            self.assertFalse((state_path.parent / "concierge").exists())

    def test_add_source_refuses_files_outside_run_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = self.make_run(root)
            prepared, _ = self.invoke(
                "prepare", "--state", str(state_path), "--request", "確認する", "--explicit-request",
            )
            outside = root / "outside.txt"
            outside.write_text("outside", encoding="utf-8")
            result, _ = self.invoke(
                "add-source", "--request-dir", prepared["request_dir"], "--source", str(outside), expected=1,
            )
            self.assertEqual("error", result["status"])
            self.assertIn("under run_root", result["error"])

    def test_finalize_refuses_any_non_concierge_run_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = self.make_run(Path(directory))
            prepared, _ = self.invoke(
                "prepare", "--state", str(state_path), "--request", "確認する", "--explicit-request",
            )
            request_dir = Path(prepared["request_dir"])
            draft_path = request_dir / "response_draft.json"
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            draft["answer_markdown"] = "既存結果の説明。"
            draft_path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
            (state_path.parent / "unexpected.txt").write_text("mutation", encoding="utf-8")
            result, _ = self.invoke("finalize", "--request-dir", str(request_dir), expected=1)
            self.assertEqual("error", result["status"])
            self.assertIn("Run files changed after prepare", result["error"])
            self.assertFalse((request_dir / "response.html").exists())


if __name__ == "__main__":
    unittest.main()
