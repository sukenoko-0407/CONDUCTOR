from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
EXPORTER = ROOT / "CONDUCTOR_modules" / "tools" / "export_validated_report_html.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_exporter_verifies_accepted_artifacts_and_does_not_overwrite(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "status": "succeeded",
                "endpoint_id": "EP",
                "components": [],
                "finding_count": 0,
            }
        ),
        encoding="utf-8",
    )
    findings = tmp_path / "final_findings.jsonl"
    findings.write_text("", encoding="utf-8")
    validation = tmp_path / "citation_validation.json"
    validation.write_text(
        json.dumps({"status": "succeeded", "errors": [], "failure_fraction": 0.0}),
        encoding="utf-8",
    )
    artifacts = [
        ("report_json", report),
        ("final_findings", findings),
        ("citation_validation", validation),
    ]
    manifest = tmp_path / "artifact_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "status": "succeeded",
                "producer": {
                    "run_id": "RUN|fixture",
                    "node_id": "P06-REPORT",
                    "attempt_id": "ATTEMPT|fixture",
                    "skill_name": "cs-report",
                },
                "created_at": "2026-09-21T00:00:00Z",
                "artifacts": [
                    {"role": role, "path": path.name, "sha256": _sha256(path)}
                    for role, path in artifacts
                ],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "external" / "report.html"
    command = [
        sys.executable,
        str(EXPORTER),
        "--artifact-manifest",
        str(manifest),
        "--output",
        str(output),
    ]

    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    assert completed.returncode == 0, completed.stderr
    assert output.read_text(encoding="utf-8").startswith("<!doctype html>")
    assert json.loads(completed.stdout)["run_root_modified"] is False

    repeated = subprocess.run(command, text=True, capture_output=True, check=False)
    assert repeated.returncode != 0
    assert "Refusing to overwrite" in repeated.stderr
