from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from conductor_runtime import PipelineCoordinator, PipelinePlan, RuntimeStateStore, prepare_phase1
from conductor_stat_core import SchemaValidationError, atomic_write_json, file_sha256, stable_id, validate_instance
from conductor_stat_core.contracts import prepare_output_directory, verify_request_inputs


SKILL_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SKILL_DIR.parents[2]
SCHEMA_DIR = PROJECT_ROOT / "CONDUCTOR_modules" / "schemas"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _one_input(request: dict[str, Any], role: str) -> Path:
    matches = [Path(item["path"]) for item in request["inputs"] if item["role"] == role]
    if len(matches) != 1:
        raise ValueError(f"Exactly one {role!r} input is required")
    return matches[0]


def _artifact(output: Path, role: str, relative: str, schema: str, rows: int | None) -> dict[str, Any]:
    path = output / relative
    return {
        "artifact_id": stable_id("ART", {"role": role, "sha256": file_sha256(path)}),
        "role": role,
        "path": relative,
        "media_type": "text/csv" if path.suffix == ".csv" else "application/json",
        "schema": schema,
        "rows": rows,
        "sha256": file_sha256(path),
    }


def _run(args: argparse.Namespace) -> dict[str, str]:
    request = json.loads(Path(args.request).resolve().read_text(encoding="utf-8"))
    validate_instance(request, SCHEMA_DIR / "execution_request.schema.json")
    if request["identity"]["skill_name"] != "cs-runtime":
        raise SchemaValidationError("Execution Request skill_name does not match cs-runtime")
    verify_request_inputs(request)
    config_path = Path(request["config_path"]).resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or config.get("schema_version") != "0.2.1":
        raise SchemaValidationError("Resolved configuration must use schema_version 0.2.1")
    operation = request["parameters"].get("operation")
    if operation not in {"prepare_phase1", "coordinate"}:
        raise SchemaValidationError(f"Unsupported runtime operation: {operation!r}")
    if operation == "coordinate":
        output = Path(args.output_dir).resolve()
        output.mkdir(parents=True, exist_ok=True)
        plan = PipelinePlan.load(_one_input(request, "pipeline_plan"))
        if plan.run_id != request["identity"]["run_id"]:
            raise SchemaValidationError("Pipeline plan run_id does not match Execution Request")
        store = RuntimeStateStore(output / "runtime.sqlite")
        summary = PipelineCoordinator(plan, store, output, SCHEMA_DIR).run(
            lease_seconds=int(request["parameters"].get("lease_seconds", 3600)),
            workers=int(request["resources"]["workers"]),
        )
        atomic_write_json(output / "runtime_summary.json", summary)
        artifacts = [
            _artifact(output, "runtime_state", "runtime.sqlite", "runtime_state@0.2.1", None),
            _artifact(output, "runtime_summary", "runtime_summary.json", "runtime_summary@0.2.1", len(summary["nodes"])),
        ]
        manifest = {
            "schema_version": "0.2.1",
            "producer": {key: request["identity"][key] for key in ("run_id", "node_id", "attempt_id", "skill_name")},
            "status": summary["status"],
            "config_sha256": file_sha256(config_path),
            "input_artifacts": [{"role": item["role"], "path": item["path"], "sha256": item["sha256"]} for item in request["inputs"]],
            "artifacts": artifacts,
            "metrics": {"node_count": len(summary["nodes"]), "succeeded_count": sum(item["state"] == "succeeded" for item in summary["nodes"])},
            "warnings": [] if summary["status"] == "succeeded" else [f"Pipeline stopped with status {summary['status']}"],
            "created_at": _utc_now(),
        }
        atomic_write_json(output / "artifact_manifest.json", manifest)
        validate_instance(manifest, SCHEMA_DIR / "artifact_manifest.schema.json")
        return {"status": summary["status"], "manifest": "artifact_manifest.json", "primary": "runtime_summary.json"}
    output = prepare_output_directory(Path(args.output_dir), args.overwrite)
    result = prepare_phase1(
        dataset_path=_one_input(request, "dataset"),
        registry_path=_one_input(request, "endpoint_registry"),
        selected_endpoint_id=request["endpoint_id"],
        output_directory=output,
        schema_directory=SCHEMA_DIR,
        id_column=request["parameters"].get("id_column", "compound_id"),
        smiles_column=request["parameters"].get("smiles_column", "smiles"),
    )
    artifacts = [
        _artifact(output, "compounds", "compounds.csv", "compounds@0.2.1", len(result.compounds)),
        _artifact(output, "endpoint_table", "endpoints.csv", "endpoints@0.2.1", len(result.endpoints)),
        _artifact(output, "endpoint_missingness", "endpoint_missingness.csv", "endpoint_missingness@0.2.1", len(result.missingness)),
        _artifact(output, "endpoint_registry", "endpoint_registry.json", "endpoint_registry@0.2.1", len(result.registry["endpoints"])),
    ]
    manifest = {
        "schema_version": "0.2.1",
        "producer": {
            key: request["identity"][key]
            for key in ("run_id", "node_id", "attempt_id", "skill_name")
        },
        "status": "succeeded",
        "config_sha256": file_sha256(config_path),
        "input_artifacts": [
            {"role": item["role"], "path": item["path"], "sha256": item["sha256"]}
            for item in request["inputs"]
        ],
        "artifacts": artifacts,
        "metrics": {
            "compound_count": len(result.compounds),
            "valid_structure_count": int(result.compounds["mol_parse_ok"].sum()),
            "endpoint_count": len(result.registry["endpoints"]),
        },
        "warnings": list(result.warnings),
        "created_at": _utc_now(),
    }
    manifest_path = output / "artifact_manifest.json"
    atomic_write_json(manifest_path, manifest)
    validate_instance(manifest, SCHEMA_DIR / "artifact_manifest.schema.json")
    return {"status": "succeeded", "manifest": manifest_path.name, "primary": "endpoints.csv"}


def main() -> int:
    parser = argparse.ArgumentParser(description="CONDUCTOR 0.2.1 Runtime")
    parser.add_argument("--request", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        response = _run(args)
    except (json.JSONDecodeError, yaml.YAMLError, SchemaValidationError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}), file=sys.stderr)
        return 2
    except (FileNotFoundError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}), file=sys.stderr)
        return 3
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}), file=sys.stderr)
        return 4
    print(json.dumps(response, separators=(",", ":")))
    return 4 if response["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
