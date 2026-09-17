from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from conductor_context_builder import build_contexts
from conductor_stat_core import SchemaValidationError, atomic_write_json, file_sha256, stable_id, validate_instance
from conductor_stat_core.contracts import prepare_output_directory, verify_request_inputs


SKILL_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SKILL_DIR.parents[2]
SCHEMA_DIR = PROJECT_ROOT / "CONDUCTOR_modules" / "schemas"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _one_input(request: dict[str, Any], role: str) -> Path:
    matches = [Path(item["path"]).resolve() for item in request["inputs"] if item["role"] == role]
    if len(matches) != 1:
        raise ValueError(f"Exactly one {role!r} input is required")
    return matches[0]


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        frame.to_csv(temporary, index=False, lineterminator="\n")
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _artifact(output: Path, role: str, name: str, rows: int) -> dict[str, Any]:
    digest = file_sha256(output / name)
    return {
        "artifact_id": stable_id("ART", {"role": role, "sha256": digest}),
        "role": role,
        "path": name,
        "media_type": "text/csv",
        "schema": f"{role}@0.2.1",
        "rows": rows,
        "sha256": digest,
    }


def _run(args: argparse.Namespace) -> dict[str, str]:
    request = json.loads(Path(args.request).resolve().read_text(encoding="utf-8"))
    validate_instance(request, SCHEMA_DIR / "execution_request.schema.json")
    if request["identity"]["skill_name"] != "cs-context-builder":
        raise SchemaValidationError("Execution Request skill_name does not match cs-context-builder")
    if request["parameters"].get("operation") != "build_contexts":
        raise SchemaValidationError("parameters.operation must be 'build_contexts'")
    verify_request_inputs(request)
    config_path = Path(request["config_path"]).resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or config.get("schema_version") != "0.2.1":
        raise SchemaValidationError("Resolved configuration must use schema_version 0.2.1")
    context_config = config["contexts"]
    feature_registry = json.loads(_one_input(request, "feature_spaces").read_text(encoding="utf-8"))
    spaces = feature_registry.get("spaces")
    if not isinstance(spaces, list):
        raise SchemaValidationError("feature_spaces input must contain a spaces array")
    output = prepare_output_directory(Path(args.output_dir), args.overwrite)
    result = build_contexts(
        pd.read_csv(_one_input(request, "compounds"), dtype={"compound_id": "string"}),
        pd.read_csv(_one_input(request, "endpoint_table"), dtype={"compound_id": "string"}),
        spaces,
        request["endpoint_id"],
        cluster_counts=context_config["cluster_counts"],
        quantiles=context_config["quantiles"],
        min_endpoint_n=int(context_config["min_endpoint_n"]),
        jaccard_threshold=float(context_config["jaccard_dedup_min"]),
        translation_auc_min=float(context_config["translation_auc_min"]),
        random_seed=int(request["random_seed"]),
    )
    outputs = [
        ("context_catalog", "context_catalog.csv", result.catalog),
        ("context_membership", "context_membership.csv", result.membership),
        ("context_deduplication", "context_deduplication.csv", result.deduplication),
        ("context_translation", "context_translation.csv", result.translations),
        ("activity_diagnostic", "activity_diagnostic.csv", result.activity_diagnostic),
    ]
    for _, name, frame in outputs:
        _write_csv(frame, output / name)
    manifest = {
        "schema_version": "0.2.1",
        "producer": {key: request["identity"][key] for key in ("run_id", "node_id", "attempt_id", "skill_name")},
        "status": "succeeded",
        "config_sha256": file_sha256(config_path),
        "input_artifacts": [{"role": item["role"], "path": item["path"], "sha256": item["sha256"]} for item in request["inputs"]],
        "artifacts": [_artifact(output, role, name, len(frame)) for role, name, frame in outputs],
        "metrics": result.metrics,
        "warnings": [],
        "created_at": _utc_now(),
    }
    manifest_path = output / "artifact_manifest.json"
    atomic_write_json(manifest_path, manifest)
    validate_instance(manifest, SCHEMA_DIR / "artifact_manifest.schema.json")
    return {"status": "succeeded", "manifest": manifest_path.name, "primary": "context_catalog.csv"}


def main() -> int:
    parser = argparse.ArgumentParser(description="CONDUCTOR 0.2.1 context builder")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
