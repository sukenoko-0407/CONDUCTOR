"""Canonical Phase 1 Description node for CONDUCTOR 0.2.1.

This is the tracked Runtime entry point for all retained 0.1.x Description
Skills.  It keeps per-Skill outputs under ``descriptions/`` and all reusable
distance artifacts under ``distance/`` at the node output root.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STAT_PACKAGE = PROJECT_ROOT / ".claude" / "skills" / "cs-stat-core" / "python"
if str(STAT_PACKAGE) not in sys.path:
    sys.path.insert(0, str(STAT_PACKAGE))

from conductor_stat_core import (  # noqa: E402
    atomic_write_json,
    file_sha256,
    stable_id,
    validate_instance,
)
from conductor_stat_core.contracts import (  # noqa: E402
    prepare_output_directory,
    verify_request_inputs,
)
from description_adapter import (  # noqa: E402
    build_feature_spaces,
    discover_description_capabilities,
    run_description_capability,
)


SCHEMAS = PROJECT_ROOT / "CONDUCTOR_modules" / "schemas"


def _dataset_input(request: dict[str, Any]) -> Path:
    matches = [
        Path(item["path"]).resolve()
        for item in request["inputs"]
        if item["role"] in {"dataset", "compounds"}
    ]
    if len(matches) != 1:
        raise ValueError("Description node requires exactly one dataset or compounds input")
    return matches[0]


def _artifact(
    output: Path,
    role: str,
    relative: str,
    schema: str,
    rows: int | None = None,
) -> dict[str, Any]:
    path = output / relative
    suffix = path.suffix.lower()
    media_type = {
        ".json": "application/json",
        ".npy": "application/octet-stream",
        ".parquet": "application/vnd.apache.parquet",
    }.get(suffix, "text/csv")
    digest = file_sha256(path)
    return {
        "artifact_id": stable_id("ART", {"role": role, "sha256": digest}),
        "role": role,
        "path": relative,
        "media_type": media_type,
        "schema": schema,
        "rows": rows,
        "sha256": digest,
    }


def execute(request_path: Path, output_path: Path, overwrite: bool) -> dict[str, str]:
    request = json.loads(request_path.resolve().read_text(encoding="utf-8"))
    validate_instance(request, SCHEMAS / "execution_request.schema.json")
    verify_request_inputs(request)
    parameters = dict(request["parameters"])
    if parameters.get("operation") not in {None, "descriptions"}:
        raise ValueError("Description node operation must be 'descriptions'")
    program_name = str(parameters.get("program_name", "")).strip()
    if not program_name:
        raise ValueError("Description node requires parameters.program_name")
    id_column = str(parameters.get("id_column", "compound_id"))
    smiles_column = str(parameters.get("smiles_column", "canonical_smiles"))
    available_cpu_cores = int(request["resources"]["workers"])
    if available_cpu_cores < 1:
        raise ValueError(
            "Description node requires resources.workers >= 1 as the explicit CPU upper bound"
        )
    output = prepare_output_directory(output_path, overwrite)
    capabilities = discover_description_capabilities(
        PROJECT_ROOT / ".claude" / "skills"
    )
    overrides = parameters.get("description_parameters") or {}
    if not isinstance(overrides, dict):
        raise ValueError("description_parameters must be an object keyed by capability_id")
    unknown = set(overrides) - {str(item["capability_id"]) for item in capabilities}
    if unknown:
        raise ValueError(f"Unknown Description parameter overrides: {sorted(unknown)}")

    payloads: list[tuple[dict[str, Any], Path, dict[str, Any]]] = []
    plans: dict[str, dict[str, Any]] = {}
    dataset = _dataset_input(request)
    for capability in capabilities:
        capability_id = str(capability["capability_id"])
        capability_parameters = dict(overrides.get(capability_id) or {})
        payload, plan = run_description_capability(
            project_root=PROJECT_ROOT,
            program_name=program_name,
            dataset_path=dataset,
            id_column=id_column,
            smiles_column=smiles_column,
            capability=capability,
            parameters=capability_parameters,
            output_directory=output / "descriptions" / capability_id,
            identity=request["identity"],
            available_cpu_cores=available_cpu_cores,
        )
        payloads.append((capability, payload, capability_parameters))
        plans[capability_id] = plan

    spaces = build_feature_spaces(payloads, output)
    artifacts = [
        _artifact(
            output,
            "feature_spaces",
            "feature_spaces.json",
            "feature_spaces@0.2.1",
            len(spaces),
        )
    ]
    for capability, payload, _ in payloads:
        capability_id = str(capability["capability_id"])
        relative = payload.relative_to(output).as_posix()
        artifacts.append(
            _artifact(
                output,
                f"description_{capability_id}",
                relative,
                f"description_{capability_id}@{capability['calculation_version']}",
                int(plans[capability_id]["input_count"]),
            )
        )
        artifacts.append(
            _artifact(
                output,
                f"distance_{capability_id}",
                f"distance/{capability_id}.npy",
                "distance_matrix@0.2.1",
                int(plans[capability_id]["input_count"]),
            )
        )
        artifacts.append(
            _artifact(
                output,
                f"distance_metadata_{capability_id}",
                f"distance/{capability_id}.json",
                "distance_metadata@0.2.1",
                None,
            )
        )
    config_path = Path(request["config_path"]).resolve()
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
            "description_count": len(payloads),
            "distance_count": len(spaces),
            "available_cpu_cores": available_cpu_cores,
            "cache": {
                capability_id: {
                    "hit_count": int(plan["hit_count"]),
                    "miss_count": int(plan["miss_count"]),
                    "registered_count": int(plan.get("registered_count", 0)),
                    "registered_ok_count": int(
                        plan.get("registered_ok_count", 0)
                    ),
                    "registered_skip_count": int(
                        plan.get("registered_skip_count", 0)
                    ),
                    "registration_skipped_count": int(
                        plan.get("registration_skipped_count", 0)
                    ),
                    "cache_outcome_counts": dict(
                        plan.get("cache_outcome_counts") or {}
                    ),
                }
                for capability_id, plan in sorted(plans.items())
            },
        },
        "warnings": [],
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    atomic_write_json(output / "artifact_manifest.json", manifest)
    validate_instance(manifest, SCHEMAS / "artifact_manifest.schema.json")
    return {
        "status": "succeeded",
        "manifest": "artifact_manifest.json",
        "primary": "feature_spaces.json",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="CONDUCTOR Phase 1 Description node")
    parser.add_argument("--request", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        response = execute(
            Path(args.request), Path(args.output_dir), bool(args.overwrite)
        )
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}), file=sys.stderr)
        return 4
    print(json.dumps(response, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
