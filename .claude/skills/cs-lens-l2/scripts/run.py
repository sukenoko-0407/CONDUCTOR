from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from conductor_lens_l2 import run_l2a, run_l2b
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


def _write_jsonl(rows: tuple[dict[str, Any], ...], path: Path) -> None:
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _artifact(output: Path, role: str, name: str, rows: int | None, media_type: str) -> dict[str, Any]:
    digest = file_sha256(output / name)
    return {
        "artifact_id": stable_id("ART", {"role": role, "sha256": digest}),
        "role": role,
        "path": name,
        "media_type": media_type,
        "schema": f"{role}@0.2.1",
        "rows": rows,
        "sha256": digest,
    }


def _database_metrics(path: Path) -> dict[str, Any]:
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
        complete_row = connection.execute("SELECT value_json FROM metadata WHERE key='complete'").fetchone()
        if complete_row is None or json.loads(complete_row[0]) is not True:
            raise ValueError("MMP database is not complete")
        pair_count = int(connection.execute("SELECT COUNT(*) FROM pairs").fetchone()[0])
        by_class = {
            str(name): int(count)
            for name, count in connection.execute('SELECT "class",COUNT(*) FROM pairs GROUP BY "class"')
        }
    return {"pair_count": pair_count, "pair_count_by_class": by_class}


def _database_pairs(path: Path) -> pd.DataFrame:
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
        return pd.read_sql_query('SELECT pair_id,"class",compound_from,compound_to,constant_key,variable_from,variable_to,transformation_id FROM pairs ORDER BY pair_id', connection)


def _run(args: argparse.Namespace) -> dict[str, str]:
    request = json.loads(Path(args.request).resolve().read_text(encoding="utf-8"))
    validate_instance(request, SCHEMA_DIR / "execution_request.schema.json")
    if request["identity"]["skill_name"] != "cs-lens-l2":
        raise SchemaValidationError("Execution Request skill_name does not match cs-lens-l2")
    operation = request["parameters"].get("operation")
    if operation not in {"l2a", "l2b"}:
        raise SchemaValidationError("parameters.operation must be 'l2a' or 'l2b'")
    verify_request_inputs(request)
    config_path = Path(request["config_path"]).resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or config.get("schema_version") != "0.2.1":
        raise SchemaValidationError("Resolved configuration must use schema_version 0.2.1")
    output = prepare_output_directory(Path(args.output_dir), args.overwrite)
    statistics = config["statistics"]
    if operation == "l2a":
        lens = config["lenses"]["l2a"]
        result = run_l2a(
            _database_pairs(_one_input(request, "mmp_database")),
            pd.read_csv(_one_input(request, "endpoint_table"), dtype={"compound_id": "string"}),
            pd.read_csv(_one_input(request, "context_catalog")),
            pd.read_csv(_one_input(request, "context_membership"), dtype={"compound_id": "string"}),
            request["endpoint_id"], run_seed=int(request["random_seed"]),
            min_transform_pairs=int(lens["min_transform_pairs"]), min_pairs_in=int(lens["min_pairs_in"]), min_pairs_out=int(lens["min_pairs_out"]),
            neutral_abs_delta_max=float(config["measurement"]["neutral_abs_delta_max"]), tolerance_variance_max=float(config["measurement"]["tolerance_variance_max"]),
            screen_permutations=int(statistics["screen_permutations"]), final_permutations=int(statistics["final_permutations"]),
            screen_p_max=float(statistics["screen_p_max"]), report_q_max=float(statistics["report_q_max"]),
        )
        for finding in result.findings:
            validate_instance(finding, SCHEMA_DIR / "finding.schema.json")
        _write_csv(result.evidence, output / "l2a_evidence.csv")
        _write_csv(result.tests, output / "l2a_tests.csv")
        _write_csv(result.score_observations, output / "score_observations.csv")
        _write_jsonl(result.findings, output / "findings.jsonl")
        names = [("l2a_evidence","l2a_evidence.csv",len(result.evidence),"text/csv"),("l2a_tests","l2a_tests.csv",len(result.tests),"text/csv"),("score_observations","score_observations.csv",len(result.score_observations),"text/csv"),("findings","findings.jsonl",len(result.findings),"application/x-ndjson")]
        manifest = {
            "schema_version":"0.2.1","producer":{key:request["identity"][key] for key in ("run_id","node_id","attempt_id","skill_name")},"status":"succeeded",
            "config_sha256":file_sha256(config_path),"input_artifacts":[{"role":item["role"],"path":item["path"],"sha256":item["sha256"]} for item in request["inputs"]],
            "artifacts":[_artifact(output,*item) for item in names],"metrics":result.metrics,"warnings":[],"created_at":_utc_now(),
        }
        atomic_write_json(output / "artifact_manifest.json", manifest); validate_instance(manifest, SCHEMA_DIR / "artifact_manifest.schema.json")
        return {"status":"succeeded","manifest":"artifact_manifest.json","primary":"findings.jsonl"}
    lens = config["lenses"]["l2b"]
    result = run_l2b(
        pd.read_csv(_one_input(request, "fragment_observations"), dtype={"compound_id": "string"}),
        pd.read_csv(_one_input(request, "endpoint_table"), dtype={"compound_id": "string"}),
        request["endpoint_id"],
        run_seed=int(request["random_seed"]),
        screen_permutations=int(statistics["screen_permutations"]),
        final_permutations=int(statistics["final_permutations"]),
        screen_p_max=float(statistics["screen_p_max"]),
        report_q_max=float(statistics["report_q_max"]),
        calibration_permutations=int(statistics["calibration_permutations"]),
        enrichment_thresholds=lens["enrichment_thresholds"],
    )
    for finding in result.findings:
        validate_instance(finding, SCHEMA_DIR / "finding.schema.json")
    _write_csv(result.evidence, output / "l2b_evidence.csv")
    _write_csv(result.tests, output / "l2b_tests.csv")
    _write_csv(result.score_observations, output / "score_observations.csv")
    _write_jsonl(result.findings, output / "findings.jsonl")
    context_catalog = pd.read_csv(_one_input(request, "context_catalog"))
    database_metrics = _database_metrics(_one_input(request, "mmp_database"))
    checkpoint = {
        "schema_version": "0.2.1",
        "endpoint_id": request["endpoint_id"],
        **result.calibration,
        **database_metrics,
        "series_count": result.metrics["series_count"],
        "context_count": len(context_catalog),
        "calibration_scope_context_count": int(context_catalog.get("calibration_scope", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()),
        "participation_rate": result.metrics["participation_rate"],
        "final_candidate_count": result.metrics["final_candidate_count"],
        "finding_count": result.metrics["finding_count"],
    }
    atomic_write_json(output / "l2b_calibration.json", checkpoint)
    artifacts = [
        _artifact(output, "l2b_evidence", "l2b_evidence.csv", len(result.evidence), "text/csv"),
        _artifact(output, "l2b_tests", "l2b_tests.csv", len(result.tests), "text/csv"),
        _artifact(output, "score_observations", "score_observations.csv", len(result.score_observations), "text/csv"),
        _artifact(output, "findings", "findings.jsonl", len(result.findings), "application/x-ndjson"),
        _artifact(output, "l2b_calibration", "l2b_calibration.json", None, "application/json"),
    ]
    status = "succeeded" if result.calibration["acceptance_gt_1_5"] else "needs_design_review"
    warnings = [] if status == "succeeded" else ["L2b enrichment checkpoint did not exceed 1.5 at every finite threshold"]
    manifest = {
        "schema_version": "0.2.1",
        "producer": {key: request["identity"][key] for key in ("run_id", "node_id", "attempt_id", "skill_name")},
        "status": status,
        "config_sha256": file_sha256(config_path),
        "input_artifacts": [{"role": item["role"], "path": item["path"], "sha256": item["sha256"]} for item in request["inputs"]],
        "artifacts": artifacts,
        "metrics": {**result.metrics, **database_metrics, "context_count": len(context_catalog)},
        "warnings": warnings,
        "created_at": _utc_now(),
    }
    manifest_path = output / "artifact_manifest.json"
    atomic_write_json(manifest_path, manifest)
    validate_instance(manifest, SCHEMA_DIR / "artifact_manifest.schema.json")
    return {"status": status, "manifest": manifest_path.name, "primary": "findings.jsonl"}


def main() -> int:
    parser = argparse.ArgumentParser(description="CONDUCTOR 0.2.1 L2 lens")
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
