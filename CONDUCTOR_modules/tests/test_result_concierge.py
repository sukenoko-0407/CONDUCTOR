from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".claude" / "skills" / "cs-conductor-result-concierge" / "scripts" / "run.py"
SPEC = importlib.util.spec_from_file_location("concierge_012", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class ConciergeTests(unittest.TestCase):
    def frozen_run(self, base: Path) -> Path:
        root = base / "run"; (root / "runtime").mkdir(parents=True)
        control = {"conductor_version": "0.1.2", "run": {"run_id": "r1"}, "active_round_id": None, "round_state": "CLOSED", "lease": {"owner_id": None, "expires_at": None}}
        snapshot = {"nodes": [], "rounds": {}}
        (root / "conductor_control.json").write_text(json.dumps(control), encoding="utf-8")
        (root / "runtime" / "dag_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
        return root

    def test_prepare_is_scoped_to_run_concierge(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.frozen_run(Path(temporary))
            result = MODULE.prepare(Namespace(run_root=str(root), request="既存結果を説明", request_file=None, focus_id=[], explicit_request=True))
            request_dir = Path(result["request_dir"])
            self.assertEqual(request_dir.parent, root / "concierge")
            self.assertRegex(request_dir.name, r"^REQ\d{6}$")
            self.assertTrue((request_dir / "control_snapshot.json").is_file())
            self.assertTrue((request_dir / "dag_snapshot.json").is_file())

    def test_active_run_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.frozen_run(Path(temporary))
            control = json.loads((root / "conductor_control.json").read_text(encoding="utf-8")); control["active_round_id"] = "RND0001"; control["round_state"] = "ACTIVE"
            (root / "conductor_control.json").write_text(json.dumps(control), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                MODULE.prepare(Namespace(run_root=str(root), request="説明", request_file=None, focus_id=[], explicit_request=True))

    def test_human_review_state_is_frozen_and_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.frozen_run(Path(temporary))
            control = json.loads((root / "conductor_control.json").read_text(encoding="utf-8"))
            control["active_round_id"] = "RND0001"
            control["round_state"] = "AWAITING_HUMAN_REVIEW"
            (root / "conductor_control.json").write_text(json.dumps(control), encoding="utf-8")
            result = MODULE.prepare(Namespace(run_root=str(root), request="Interpretationの根拠を説明", request_file=None, focus_id=[], explicit_request=True))
            self.assertTrue(Path(result["request_dir"]).is_dir())


if __name__ == "__main__":
    unittest.main()
