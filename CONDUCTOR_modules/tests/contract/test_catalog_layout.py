from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from verify_package_layout import verify


PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODULE_ROOT = PROJECT_ROOT / "CONDUCTOR_modules"


def test_catalog_and_filesystem_are_bidirectionally_complete() -> None:
    assert verify() == []
    included = json.loads((MODULE_ROOT / "catalog" / "included_skills.json").read_text(encoding="utf-8"))
    catalog = json.loads((MODULE_ROOT / "catalog" / "catalog.json").read_text(encoding="utf-8"))
    selected = set(included["description_skills"] + included["pipeline_skills"])
    assert selected == {row["skill_name"] for row in catalog["capabilities"]}
    assert included["reserved_description_ids"] == ["D017", "D018"]


def test_installer_dry_run_is_non_mutating(tmp_path) -> None:
    target = tmp_path / "project"
    target.mkdir()
    completed = subprocess.run(
        [sys.executable, str(MODULE_ROOT / "tools" / "install_into_project.py"), "--target", str(target)],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "Dry run only" in completed.stdout
    assert list(target.iterdir()) == []
