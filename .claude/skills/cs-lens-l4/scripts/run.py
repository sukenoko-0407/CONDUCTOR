from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[4]
TOOLS = ROOT / "CONDUCTOR_modules" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from conductor_lens_l4 import (  # noqa: E402
    L4ScaleGuardError,
    generate_l4_candidates,
    score_l4_candidates,
    select_l4_candidates,
)
from conductor_stat_core import (  # noqa: E402
    SchemaValidationError,
    atomic_write_json,
    file_sha256,
    stable_id,
    validate_instance,
)
from conductor_stat_core.contracts import (  # noqa: E402
    prepare_output_directory,
    verify_request_inputs,
)
from identity_bridge import bridge_legacy_identity  # noqa: E402
from lens_work_estimators import estimate_work  # noqa: E402
from work_contract import ProgressReporter, WorkEstimate  # noqa: E402


SCHEMAS = ROOT / "CONDUCTOR_modules" / "schemas"


def _input(request: dict[str, Any], role: str) -> Path:
    values = [
        Path(item["path"]).resolve()
        for item in request["inputs"]
        if item["role"] == role
    ]
    if len(values) != 1:
        raise ValueError(f"Exactly one {role!r} input is required")
    return values[0]


def _csv(frame: pd.DataFrame, path: Path) -> None:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(descriptor)
    temporary = Path(name)
    try:
        frame.to_csv(temporary, index=False, lineterminator="\n")
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _jsonl(rows: tuple[dict[str, Any], ...], path: Path) -> None:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(descriptor)
    temporary = Path(name)
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(
                    json.dumps(
                        row,
                        ensure_ascii=False,
                        allow_nan=False,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _artifact(
    output: Path, role: str, name: str, rows: int | None
) -> dict[str, Any]:
    digest = file_sha256(output / name)
    suffix = Path(name).suffix.lower()
    media = {
        ".jsonl": "application/x-ndjson",
        ".json": "application/json",
        ".parquet": "application/vnd.apache.parquet",
    }.get(suffix, "text/csv")
    return {
        "artifact_id": stable_id("ART", {"role": role, "sha256": digest}),
        "role": role,
        "path": name,
        "media_type": media,
        "schema": f"{role}@0.2.1",
        "rows": rows,
        "sha256": digest,
    }


def _parameter_arguments(parameters: dict[str, Any]) -> list[str]:
    arguments: list[str] = []
    for key, value in sorted(parameters.items()):
        option = f"--{key.replace('_', '-')}"
        if isinstance(value, bool):
            arguments.append(option if value else f"--no-{key.replace('_', '-')}")
        elif isinstance(value, list):
            for item in value:
                arguments.extend((option, str(item)))
        elif value is not None:
            arguments.extend((option, str(value)))
    return arguments


def _available_cpu_cores(request: dict[str, Any], cli_workers: int) -> int:
    declared = int(request["resources"]["workers"])
    if declared > 0:
        return declared
    if cli_workers > 0:
        return cli_workers
    local = (
        len(os.sched_getaffinity(0))
        if hasattr(os, "sched_getaffinity")
        else (os.cpu_count() or 1)
    )
    return max(1, local - 1)


def _description_parameters(
    space: dict[str, Any], available_cpu_cores: int
) -> dict[str, Any]:
    parameters = dict(space.get("parameters") or {})
    space_id = str(space["space_id"])
    if space_id == "D016":
        parameters["compound_workers"] = min(
            int(parameters.get("compound_workers", 8)), available_cpu_cores
        )
        parameters["available_cpu_cores"] = available_cpu_cores
    if space_id == "D019":
        cores_per_compound = int(parameters.get("cores_per_compound", 4))
        parameters["cores_per_compound"] = cores_per_compound
        parameters.setdefault(
            "compound_workers", max(1, available_cpu_cores // cores_per_compound)
        )
        parameters["available_cpu_cores"] = available_cpu_cores
    return parameters


def _description_cost_class(space: dict[str, Any]) -> str:
    declared = str(space.get("cost_class", "")).strip()
    if declared:
        return declared
    capability_path = (
        ROOT
        / ".claude"
        / "skills"
        / str(space["skill_name"])
        / "capability.json"
    )
    capability = json.loads(capability_path.read_text(encoding="utf-8"))
    return str((capability.get("cost") or {}).get("class", ""))


def _describe_candidates(
    candidates: pd.DataFrame,
    spaces: list[dict[str, Any]],
    output: Path,
    identity: dict[str, Any],
    available_cpu_cores: int,
    progress_callback: Any | None = None,
) -> tuple[list[dict[str, Any]], list[tuple[str, str, int]]]:
    candidate_file = output / "l4_candidate_compounds.csv"
    _csv(candidates, candidate_file)
    described: list[dict[str, Any]] = []
    artifacts: list[tuple[str, str, int]] = []
    environment = os.environ.copy()
    environment["CONDUCTOR_AVAILABLE_CPU_CORES"] = str(available_cpu_cores)
    environment["CONDUCTOR_NODE_CPU_CORES"] = str(available_cpu_cores)
    selected_spaces = sorted(
        (item for item in spaces if int(item["tier"]) <= 2),
        key=lambda item: str(item["space_id"]),
    )
    for completed_spaces, space in enumerate(selected_spaces, start=1):
        space_id = str(space["space_id"])
        skill_name = str(space["skill_name"])
        skill_directory = ROOT / ".claude" / "skills" / skill_name
        launcher = skill_directory / "scripts" / "launch.py"
        if not launcher.is_file():
            raise FileNotFoundError(
                f"Description launcher not found for {space_id}: {launcher}"
            )
        description_output = output / "candidate_descriptions" / space_id
        legacy = bridge_legacy_identity(
            identity,
            capability_id=space_id,
            skill_name=skill_name,
            discriminator=f"l4-candidate-{space_id}",
        )
        command = [
            sys.executable,
            str(launcher),
            "--input",
            str(candidate_file),
            "--id-column",
            "compound_id",
            "--smiles-column",
            "canonical_smiles",
            "--output-dir",
            str(description_output),
            "--format",
            "csv",
            "--conductor",
            "--project",
            legacy["project"],
            "--run-id",
            legacy["run_id"],
            "--round-id",
            legacy["round_id"],
            "--node-id",
            legacy["node_id"],
            "--attempt-id",
            legacy["attempt_id"],
            "--overwrite",
            *_parameter_arguments(
                _description_parameters(space, available_cpu_cores)
            ),
        ]
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            check=False,
            text=True,
            capture_output=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"Candidate Description {skill_name} failed with code "
                f"{completed.returncode}: {completed.stderr[-2000:]}"
            )
        manifest_path = description_output / "description_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload = description_output / str(manifest["output"])
        described_frame = (
            pd.read_parquet(payload)
            if payload.suffix.lower() == ".parquet"
            else pd.read_csv(payload, dtype={"compound_id": "string"})
        )
        if len(described_frame) != len(candidates) or set(
            described_frame["compound_id"].astype(str)
        ) != set(candidates["compound_id"].astype(str)):
            raise ValueError(
                f"Candidate Description output is incomplete: {space_id}"
            )
        failed = described_frame.loc[
            ~described_frame["mol_parse_ok"].astype(bool)
            | described_frame["description_error"].fillna("").astype(str).ne("")
        ]
        if not failed.empty:
            raise ValueError(
                f"Candidate Description contains {len(failed)} failed rows: {space_id}"
            )
        relative = payload.relative_to(output).as_posix()
        artifacts.append(
            (f"l4_candidate_description_{space_id}", relative, len(described_frame))
        )
        described.append(
            {
                **space,
                "candidate_path": str(payload.resolve()),
                "candidate_manifest_path": str(manifest_path.resolve()),
            }
        )
        if progress_callback is not None:
            progress_callback(completed_spaces, len(selected_spaces))
    return described, artifacts


def _base_manifest(
    request: dict[str, Any], config_path: Path, status: str
) -> dict[str, Any]:
    return {
        "schema_version": "0.2.1",
        "producer": {
            key: request["identity"][key]
            for key in ("run_id", "node_id", "attempt_id", "skill_name")
        },
        "status": status,
        "config_sha256": file_sha256(config_path),
        "input_artifacts": [
            {
                "role": item["role"],
                "path": item["path"],
                "sha256": item["sha256"],
            }
            for item in request["inputs"]
        ],
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def execute(args: argparse.Namespace) -> dict[str, str]:
    request = json.loads(Path(args.request).resolve().read_text(encoding="utf-8"))
    validate_instance(request, SCHEMAS / "execution_request.schema.json")
    if (
        request["identity"]["skill_name"] != "cs-lens-l4"
        or request["parameters"].get("operation") != "l4"
    ):
        raise SchemaValidationError(
            "Request must target cs-lens-l4 operation l4"
        )
    verify_request_inputs(request)
    config_path = Path(request["config_path"]).resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    database = _input(request, "mmp_database")
    output = prepare_output_directory(Path(args.output_dir), args.overwrite)
    with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
        fragmentations = pd.read_sql_query(
            'SELECT fragmentation_id,compound_id,"class",constant_key,'
            "variable_smiles,status FROM fragmentations ORDER BY fragmentation_id",
            connection,
        )
        transformations = pd.read_sql_query(
            'SELECT transformation_id,"class",variable_from,variable_to,'
            "pair_count FROM transformations ORDER BY transformation_id",
            connection,
        )
    registry = json.loads(_input(request, "feature_spaces").read_text(encoding="utf-8"))
    compounds = pd.read_csv(_input(request, "compounds"), dtype={"compound_id": "string"})
    endpoints = pd.read_csv(
        _input(request, "endpoint_table"), dtype={"compound_id": "string"}
    )
    raw_generation = generate_l4_candidates(
        compounds, fragmentations, transformations
    )
    tier_spaces = [item for item in registry["spaces"] if int(item["tier"]) <= 2]
    l4_config = dict((config.get("lenses") or {}).get("l4") or {})
    candidate_cap = int(l4_config.get("candidate_cap", 100))
    max_rows = int(l4_config.get("max_candidate_description_rows", 900))
    max_cost_units = int(
        l4_config.get("max_candidate_description_cost_units", 10000)
    )
    try:
        generation, scale_plan = select_l4_candidates(
            raw_generation,
            candidate_cap=candidate_cap,
            description_space_count=len(tier_spaces),
            max_candidate_description_rows=max_rows,
            description_cost_classes=[
                _description_cost_class(space) for space in tier_spaces
            ],
            max_candidate_description_cost_units=max_cost_units,
        )
    except L4ScaleGuardError as exc:
        _csv(raw_generation.candidates, output / "l4_candidate_compounds.csv")
        _csv(raw_generation.audit, output / "l4_generation_audit.csv")
        atomic_write_json(
            output / "candidate_feature_spaces.json",
            {"schema_version": "0.2.1", "spaces": []},
        )
        artifacts = [
            _artifact(
                output,
                "l4_candidates",
                "l4_candidate_compounds.csv",
                len(raw_generation.candidates),
            ),
            _artifact(
                output,
                "l4_generation_audit",
                "l4_generation_audit.csv",
                len(raw_generation.audit),
            ),
            _artifact(
                output,
                "l4_candidate_feature_spaces",
                "candidate_feature_spaces.json",
                0,
            ),
        ]
        manifest = {
            **_base_manifest(request, config_path, "needs_design_review"),
            "artifacts": artifacts,
            "metrics": {**asdict(exc.plan), "progress_granularity": "loop"},
            "warnings": [str(exc)],
        }
        atomic_write_json(output / "artifact_manifest.json", manifest)
        validate_instance(manifest, SCHEMAS / "artifact_manifest.schema.json")
        return {
            "status": "needs_design_review",
            "manifest": "artifact_manifest.json",
            "primary": "l4_candidate_compounds.csv",
        }

    available_cpu_cores = _available_cpu_cores(request, args.workers)
    progress_space_count = len(tier_spaces) if not generation.candidates.empty else 0
    progress_total = progress_space_count + len(generation.candidates)
    progress = ProgressReporter.from_environment(
        progress_total,
        min_seconds=float(((config.get("runtime") or {}).get("progress") or {}).get("min_seconds", 5)),
        min_fraction=float(((config.get("runtime") or {}).get("progress") or {}).get("min_fraction", 0.01)),
    )
    candidate_artifacts: list[tuple[str, str, int]] = []
    candidate_file = output / "l4_candidate_compounds.csv"
    if generation.candidates.empty:
        _csv(generation.candidates, candidate_file)
        candidate_spaces: list[dict[str, Any]] = []
    else:
        candidate_spaces, candidate_artifacts = _describe_candidates(
            generation.candidates,
            registry["spaces"],
            output,
            request["identity"],
            available_cpu_cores,
            progress_callback=lambda completed, total: progress.update(completed),
        )
    atomic_write_json(
        output / "candidate_feature_spaces.json",
        {"schema_version": "0.2.1", "spaces": candidate_spaces},
    )
    result = score_l4_candidates(
        endpoints,
        generation,
        candidate_spaces,
        request["endpoint_id"],
        neighbor_k=int(config["contexts"]["neighbor_k"]),
        min_context_size=int(config["contexts"]["min_endpoint_n"]),
        report_q_max=float(config["statistics"]["report_q_max"]),
        progress_callback=lambda completed, total: progress.update(progress_space_count + completed),
    )
    progress.finish()
    result.metrics.update(asdict(scale_plan))
    result.metrics["available_cpu_cores"] = available_cpu_cores
    result.metrics["progress_granularity"] = "loop"
    files = [
        ("l4_evidence", "l4_evidence.csv", result.evidence),
        ("l4_tests", "l4_tests.csv", result.tests),
        ("l4_generation_audit", "l4_generation_audit.csv", result.generation_audit),
        ("score_observations", "score_observations.csv", result.score_observations),
    ]
    for _, name, frame in files:
        _csv(frame, output / name)
    _jsonl(result.findings, output / "findings.jsonl")
    for finding in result.findings:
        validate_instance(finding, SCHEMAS / "finding.schema.json")
    artifacts = [
        _artifact(output, role, name, len(frame)) for role, name, frame in files
    ] + [
        _artifact(output, "findings", "findings.jsonl", len(result.findings)),
        _artifact(
            output,
            "l4_candidates",
            "l4_candidate_compounds.csv",
            len(generation.candidates),
        ),
        _artifact(
            output,
            "l4_candidate_feature_spaces",
            "candidate_feature_spaces.json",
            len(candidate_spaces),
        ),
    ] + [
        _artifact(output, role, name, rows)
        for role, name, rows in candidate_artifacts
    ]
    manifest = {
        **_base_manifest(request, config_path, "succeeded"),
        "artifacts": artifacts,
        "metrics": result.metrics,
        "warnings": [],
    }
    atomic_write_json(output / "artifact_manifest.json", manifest)
    validate_instance(manifest, SCHEMAS / "artifact_manifest.schema.json")
    return {
        "status": "succeeded",
        "manifest": "artifact_manifest.json",
        "primary": "findings.jsonl",
    }


def estimate(args: argparse.Namespace) -> WorkEstimate:
    request = json.loads(Path(args.request).resolve().read_text(encoding="utf-8"))
    validate_instance(request, SCHEMAS / "execution_request.schema.json")
    if request["identity"]["skill_name"] != "cs-lens-l4" or request["parameters"].get("operation") != "l4":
        raise SchemaValidationError("Request must target cs-lens-l4 operation l4")
    verify_request_inputs(request)
    config = yaml.safe_load(Path(request["config_path"]).resolve().read_text(encoding="utf-8"))
    return estimate_work(request, config, workers=max(1, int(args.workers)))


def main() -> int:
    parser = argparse.ArgumentParser(description="CONDUCTOR 0.2.1 L4 lens")
    parser.add_argument("--request", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--estimate-work", action="store_true")
    args = parser.parse_args()
    try:
        response = estimate(args).to_dict() if args.estimate_work else execute(args)
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
