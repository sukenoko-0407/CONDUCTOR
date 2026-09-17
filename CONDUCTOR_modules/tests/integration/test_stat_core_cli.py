from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODULE_ROOT = PROJECT_ROOT / "CONDUCTOR_modules"
RUNNER = PROJECT_ROOT / ".claude" / "skills" / "cs-stat-core" / "scripts" / "run.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_stat_core_cli_writes_valid_manifest(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps(
            {
                "operation": "empirical_p_value",
                "observed": 2.0,
                "null_statistics": [0.0, 1.0, 3.0],
                "alternative": "upper",
            }
        ),
        encoding="utf-8",
    )
    config = yaml.safe_load((MODULE_ROOT / "config" / "defaults.yaml").read_text(encoding="utf-8"))
    config_path = tmp_path / "resolved_config.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    request = {
        "schema_version": "0.2.1",
        "identity": {
            "project": "test",
            "run_id": "RUN-test",
            "phase_id": "P03",
            "node_id": "NODE-stat",
            "attempt_id": "ATT-1",
            "skill_name": "cs-stat-core",
        },
        "endpoint_id": "EP_TEST",
        "config_path": str(config_path.resolve()),
        "random_seed": 7,
        "inputs": [{"role": "statistic_plan", "path": str(plan.resolve()), "sha256": _sha256(plan)}],
        "parameters": {},
        "resources": {"workers": 1, "memory_mb": 512},
    }
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    output = tmp_path / "attempt"

    completed = subprocess.run(
        [sys.executable, str(RUNNER), "--request", str(request_path), "--output-dir", str(output)],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "status": "succeeded",
        "manifest": "artifact_manifest.json",
        "primary": "tables/statistic_results.json",
    }
    result = json.loads((output / "tables" / "statistic_results.json").read_text(encoding="utf-8"))
    assert result["p_value"] == 0.5
    assert (output / "artifact_manifest.json").is_file()


def test_stat_core_cli_uses_exit_two_for_schema_errors(tmp_path: Path) -> None:
    request = tmp_path / "invalid-request.json"
    request.write_text(json.dumps({"schema_version": "0.2.1"}), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(RUNNER), "--request", str(request), "--output-dir", str(tmp_path / "output")],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert json.loads(completed.stderr)["status"] == "failed"
