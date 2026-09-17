from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from conductor_stat_core import (
    TestRecord,
    SchemaValidationError,
    atomic_write_json,
    benjamini_hochberg,
    block_bootstrap_indices,
    content_hash,
    derive_seed,
    empirical_p_value,
    file_sha256,
    permute_within_blocks,
    stable_id,
    validate_instance,
)
from conductor_stat_core.contracts import prepare_output_directory, verify_request_inputs


SKILL_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SKILL_DIR.parents[2]
SCHEMA_DIR = PROJECT_ROOT / "CONDUCTOR_modules" / "schemas"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _input_for_role(request: dict[str, Any], role: str) -> Path:
    matches = [Path(item["path"]) for item in request["inputs"] if item["role"] == role]
    if len(matches) != 1:
        raise ValueError(f"Exactly one {role!r} input is required")
    return matches[0]


def _execute(plan: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    operation = request["parameters"].get("operation", plan.get("operation"))
    if operation == "permute_within_blocks":
        iteration = int(plan.get("iteration", 0))
        candidate_key = str(plan["candidate_key"])
        seed = derive_seed(int(request["random_seed"]), candidate_key, iteration)
        values, participation = permute_within_blocks(
            plan["values"], plan["block_labels"], np.random.default_rng(seed)
        )
        return {"operation": operation, "seed": seed, "values": values.tolist(), "participation": participation}
    if operation == "empirical_p_value":
        value = empirical_p_value(plan["observed"], plan["null_statistics"], plan["alternative"])
        return {"operation": operation, "p_value": value}
    if operation == "benjamini_hochberg":
        records = [TestRecord(**item) for item in plan["records"]]
        adjusted = benjamini_hochberg(records)
        return {"operation": operation, "records": [record.__dict__ for record in adjusted]}
    if operation == "block_bootstrap_indices":
        samples = block_bootstrap_indices(
            plan["block_labels"], int(plan["iterations"]), int(plan["seed"])
        )
        return {
            "operation": operation,
            "samples": [
                {"indices": sample.indices.tolist(), "instance_labels": list(sample.instance_labels)}
                for sample in samples
            ],
        }
    raise ValueError(f"Unsupported statistic operation: {operation!r}")


def _run(args: argparse.Namespace) -> dict[str, str]:
    request_path = Path(args.request).expanduser().resolve()
    request = json.loads(request_path.read_text(encoding="utf-8"))
    validate_instance(request, SCHEMA_DIR / "execution_request.schema.json")
    if request["identity"]["skill_name"] != "cs-stat-core":
        raise SchemaValidationError("Execution Request skill_name does not match cs-stat-core")
    verify_request_inputs(request)
    config_path = Path(request["config_path"]).expanduser().resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or config.get("schema_version") != "0.2.1":
        raise SchemaValidationError("Resolved configuration must use schema_version 0.2.1")
    output = prepare_output_directory(Path(args.output_dir), args.overwrite)
    plan_path = _input_for_role(request, "statistic_plan")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    result = _execute(plan, request)
    result_path = output / "tables" / "statistic_results.json"
    atomic_write_json(result_path, result)

    relative_result = result_path.relative_to(output).as_posix()
    artifact_id = stable_id("ART", {"role": "statistic_results", "sha256": file_sha256(result_path)})
    warnings = []
    participation = result.get("participation")
    if isinstance(participation, (int, float)) and participation < config["statistics"]["min_permutation_participation"]:
        warnings.append("permutation participation is below the configured minimum")
    manifest = {
        "schema_version": "0.2.1",
        "producer": {
            key: request["identity"][key]
            for key in ("run_id", "node_id", "attempt_id", "skill_name")
        },
        "status": "needs_design_review" if warnings else "succeeded",
        "config_sha256": file_sha256(config_path),
        "input_artifacts": [
            {"role": item["role"], "path": item["path"], "sha256": item["sha256"]}
            for item in request["inputs"]
        ],
        "artifacts": [{
            "artifact_id": artifact_id,
            "role": "statistic_results",
            "path": relative_result,
            "media_type": "application/json",
            "schema": "statistic_results@0.2.1",
            "rows": None,
            "sha256": file_sha256(result_path),
        }],
        "metrics": {"operation": result["operation"], "participation": participation},
        "warnings": warnings,
        "created_at": _utc_now(),
    }
    manifest_path = output / "artifact_manifest.json"
    atomic_write_json(manifest_path, manifest)
    validate_instance(manifest, SCHEMA_DIR / "artifact_manifest.schema.json")
    return {"status": manifest["status"], "manifest": manifest_path.name, "primary": relative_result}


def main() -> int:
    parser = argparse.ArgumentParser(description="CONDUCTOR 0.2.1 deterministic statistical core")
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
