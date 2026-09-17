from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from conductor_fragment_engine import FragmentationConfig, build_fragment_database
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


def _artifact(output: Path, role: str, name: str, schema: str, rows: int | None) -> dict[str, Any]:
    path = output / name
    media_type = "application/vnd.sqlite3" if path.suffix == ".sqlite" else "text/csv"
    digest = file_sha256(path)
    return {
        "artifact_id": stable_id("ART", {"role": role, "sha256": digest}),
        "role": role,
        "path": name,
        "media_type": media_type,
        "schema": schema,
        "rows": rows,
        "sha256": digest,
    }


def _run(args: argparse.Namespace) -> dict[str, str]:
    request = json.loads(Path(args.request).resolve().read_text(encoding="utf-8"))
    validate_instance(request, SCHEMA_DIR / "execution_request.schema.json")
    if request["identity"]["skill_name"] != "cs-fragment-engine":
        raise SchemaValidationError("Execution Request skill_name does not match cs-fragment-engine")
    if request["parameters"].get("operation") != "build_database":
        raise SchemaValidationError("parameters.operation must be 'build_database'")
    verify_request_inputs(request)
    config_path = Path(request["config_path"]).resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or config.get("schema_version") != "0.2.1":
        raise SchemaValidationError("Resolved configuration must use schema_version 0.2.1")
    fragment = config.get("fragmentation")
    measurement = config.get("measurement")
    if not isinstance(fragment, dict) or not isinstance(measurement, dict):
        raise SchemaValidationError("Configuration requires fragmentation and measurement sections")
    output = prepare_output_directory(Path(args.output_dir), args.overwrite)
    result = build_fragment_database(
        pd.read_csv(_one_input(request, "compounds"), dtype={"compound_id": "string"}),
        pd.read_csv(_one_input(request, "endpoint_table"), dtype={"compound_id": "string"}),
        request["endpoint_id"],
        output,
        fragmentation_config=FragmentationConfig(
            min_molecule_heavy_atoms=int(fragment["min_molecule_heavy_atoms"]),
            min_constant_heavy_atoms=int(fragment["min_constant_heavy_atoms"]),
            max_variable_fraction=float(fragment["max_variable_fraction"]),
            min_ring_variable_heavy_atoms=int(fragment["min_ring_variable_heavy_atoms"]),
            max_ring_attachments=int(fragment["max_ring_attachments"]),
        ),
        cliff_tanimoto_min=float(measurement["cliff_tanimoto_min"]),
        cliff_abs_delta_min=float(measurement["cliff_abs_delta_min"]),
        similar_core_workers=(
            args.workers
            or int(request["resources"]["workers"])
            or max(1, (os.cpu_count() or 2) - 1)
        ),
    )
    artifacts = [
        _artifact(output, "mmp_database", "mmp.sqlite", "mmp_database@0.2.1", None),
        _artifact(output, "fragment_observations", "fragment_observations.csv", "fragment_observations@0.2.1", len(result.observations)),
        _artifact(output, "fragmentation_exclusions", "fragmentation_exclusions.csv", "fragmentation_exclusions@0.2.1", len(result.exclusions)),
        _artifact(output, "pair_endpoint_values", "pair_endpoint_values.csv", "pair_endpoint_values@0.2.1", len(result.pair_endpoint_values)),
        _artifact(output, "cliff_candidates", "cliff_candidates.csv", "cliff_candidates@0.2.1", len(result.cliffs)),
    ]
    manifest = {
        "schema_version": "0.2.1",
        "producer": {key: request["identity"][key] for key in ("run_id", "node_id", "attempt_id", "skill_name")},
        "status": "succeeded",
        "config_sha256": file_sha256(config_path),
        "input_artifacts": [
            {"role": item["role"], "path": item["path"], "sha256": item["sha256"]}
            for item in request["inputs"]
        ],
        "artifacts": artifacts,
        "metrics": result.metrics,
        "warnings": [],
        "created_at": _utc_now(),
    }
    manifest_path = output / "artifact_manifest.json"
    atomic_write_json(manifest_path, manifest)
    validate_instance(manifest, SCHEMA_DIR / "artifact_manifest.schema.json")
    return {"status": "succeeded", "manifest": manifest_path.name, "primary": "mmp.sqlite"}


def main() -> int:
    parser = argparse.ArgumentParser(description="CONDUCTOR 0.2.1 fragment engine")
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
