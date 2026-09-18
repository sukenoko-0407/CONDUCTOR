from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[3]
TOOLS = PROJECT_ROOT / "CONDUCTOR_modules" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from production_run import execute_run, implementation_fingerprint  # noqa: E402
from conductor_runtime import PipelinePlan  # noqa: E402
from conductor_stat_core import file_sha256  # noqa: E402


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    input_csv = tmp_path / "input.csv"
    input_csv.write_text("compound_id,smiles,pIC50\nC1,CC,6.0\n", encoding="utf-8")
    endpoint = tmp_path / "endpoint.json"
    endpoint.write_text(json.dumps({
        "schema_version": "0.2.1", "selected_endpoint_id": "EP",
        "endpoints": [{"endpoint_id": "EP", "role": "primary", "kind": "measured", "source_column": "pIC50", "transform": "none", "higher_is_better": True, "unit": "log_molar", "dependencies": []}],
    }), encoding="utf-8")
    provider = tmp_path / "provider.json"
    provider.write_text("{}\n", encoding="utf-8")
    config = tmp_path / "resolved_config.yaml"
    config.write_text(
        f"schema_version: '0.2.1'\nllm:\n  command: 'provider --config {provider}'\n",
        encoding="utf-8",
    )
    receipt_paths = [tmp_path / f"{name}.json" for name in ("3.2A", "3.2B", "3.3")]
    run_root = tmp_path / "run"
    spec_path = tmp_path / "run_spec.json"
    spec = {
        "schema_version": "0.2.1", "project": "TEST", "project_root": str(PROJECT_ROOT),
        "program_name": f"TEST_{tmp_path.name}", "input_csv": str(input_csv),
        "endpoint_registry": str(endpoint), "endpoint_id": "EP", "config_path": str(config),
        "provider_config_path": str(provider), "id_column": "compound_id", "smiles_column": "smiles",
        "run_root": str(run_root), "workers": 1, "memory_mb": 1024, "mode": "new_database",
        "preflight_receipts": [str(path) for path in receipt_paths],
    }
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    affinity = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
    scope = {
        "project_root": str(PROJECT_ROOT), "program_name": spec["program_name"],
        "input_csv": str(input_csv), "endpoint_registry": str(endpoint), "endpoint_id": "EP",
        "config_path": str(config), "provider_config_path": str(provider), "run_root": str(run_root), "workers": 1,
    }
    hashes = {
        "input_csv": file_sha256(input_csv), "endpoint_registry": file_sha256(endpoint),
        "config_path": file_sha256(config), "provider_config_path": file_sha256(provider),
        "run_spec": file_sha256(spec_path),
    }
    blueprint_hash = file_sha256(PROJECT_ROOT / "CONDUCTOR_modules" / "pipeline" / "production_pipeline.v0.2.1.json")
    for check_id, receipt_path in zip(("3.2A", "3.2B", "3.3"), receipt_paths, strict=True):
        receipt_path.write_text(json.dumps({
            "schema_version": "0.2.1", "check_id": check_id, "status": "passed",
            "run_scope": scope, "input_hashes": hashes, "blueprint_sha256": blueprint_hash,
            "implementation_sha256": implementation_fingerprint(PROJECT_ROOT),
            "code_version": "0.2.1", "machine": {"hostname": socket.gethostname(), "cpu_affinity": affinity},
            "completed_at": datetime.now(timezone.utc).isoformat(), "checked_by": "pytest", "evidence_summary": "fixture passed",
        }), encoding="utf-8")
    return spec_path, run_root


def test_production_run_compiles_canonical_dag_without_contract_discovery(tmp_path: Path) -> None:
    spec_path, run_root = _fixture(tmp_path)
    result = execute_run(spec_path, compile_only=True)
    assert result["status"] == "compiled"
    assert result["node_count"] == 13
    plan = PipelinePlan.load(Path(result["pipeline_plan"]))
    assert len(plan.nodes) == 13
    assert {node.node_id for node in plan.nodes} >= {"P01-DESCRIPTIONS", "P03-L4", "P06-REPORT"}
    report_request = json.loads((run_root / "control" / "requests" / "P06-REPORT.json").read_text(encoding="utf-8"))
    assert any(item["path"] == "manifest://P03-L4" for item in report_request["inputs"])
    assert (run_root / "control" / "preflight_receipts" / "3.2A.json").is_file()
    frozen_config = (run_root / "control" / "resolved_config.yaml").read_text(encoding="utf-8")
    assert str(run_root / "control" / "provider_config.json") in frozen_config


def test_production_run_rejects_changed_input_before_creating_run_root(tmp_path: Path) -> None:
    spec_path, run_root = _fixture(tmp_path)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    Path(spec["input_csv"]).write_text("compound_id,smiles,pIC50\nC2,CCC,7.0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        execute_run(spec_path, compile_only=True)
    assert not run_root.exists()


def test_preflight_receipt_cli_is_dependency_free_and_hash_bound(tmp_path: Path) -> None:
    spec_path, _ = _fixture(tmp_path)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    receipt_path = Path(spec["preflight_receipts"][0])
    receipt_path.unlink()
    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "CONDUCTOR_modules" / "tools" / "create_preflight_receipt.py"),
            "--check-id", "3.2A", "--run-spec", str(spec_path),
            "--output", str(receipt_path), "--checked-by", "pytest",
            "--evidence-summary", "fixture passed",
        ],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["input_hashes"]["run_spec"] == file_sha256(spec_path)
    assert receipt["implementation_sha256"] == implementation_fingerprint(PROJECT_ROOT)
