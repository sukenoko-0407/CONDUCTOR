"""Phase 1 adapter for the retained CONDUCTOR Description Skills.

The Description Skills keep their 0.1.10 payload contracts.  This adapter owns
0.2.1 cache planning, miss-only execution, merged payloads, feature-space
metadata, and reusable distance artifacts.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy.spatial.distance import pdist, squareform

from conductor_stat_core import atomic_write_json, file_sha256

from description_database import (
    finalize_cached_output,
    prepare_cache_plan,
    register_misses,
)
from identity_bridge import bridge_legacy_identity


DESCRIPTION_IDS = tuple([f"D{number:03d}" for number in range(1, 17)] + ["D019", "D020"])
TIER_1 = frozenset({"D001", "D006"})
TIER_2 = frozenset({"D003", "D012", "D013", "D014", "D015", "D016", "D019"})
STRUCTURAL = frozenset({"D002", "D003", "D004", "D005", "D007", "D008", "D009", "D010"})
COMMON_COLUMNS = frozenset({"compound_id", "input_smiles", "mol_parse_ok", "description_error"})


def discover_description_capabilities(skills_root: Path) -> list[dict[str, Any]]:
    capabilities: list[dict[str, Any]] = []
    for directory in sorted(skills_root.glob("cs-compute-description-*")):
        capability_path = directory / "capability.json"
        if not capability_path.is_file():
            continue
        capability = json.loads(capability_path.read_text(encoding="utf-8"))
        capability["_skill_path"] = str(directory.resolve())
        capability["_skill_dir"] = str(directory.resolve())
        capabilities.append(capability)
    by_id = {str(item["capability_id"]): item for item in capabilities}
    if set(by_id) != set(DESCRIPTION_IDS):
        missing = sorted(set(DESCRIPTION_IDS) - set(by_id))
        extra = sorted(set(by_id) - set(DESCRIPTION_IDS))
        raise ValueError(f"Description capability set mismatch; missing={missing}, extra={extra}")
    if len(capabilities) != len(by_id):
        raise ValueError("Duplicate Description capability_id")
    return [by_id[identifier] for identifier in DESCRIPTION_IDS]


def feature_space_metadata(
    capability: dict[str, Any],
    payload_path: Path,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    identifier = str(capability["capability_id"])
    tier = 1 if identifier in TIER_1 else 2 if identifier in TIER_2 else 3
    structurality = "structural" if identifier in STRUCTURAL else "non_structural"
    semantics = str(capability.get("value_semantics", "dense_continuous"))
    metric = "tanimoto" if structurality == "structural" else "euclidean"
    effective_parameters = dict(capability.get("default_parameters") or {})
    effective_parameters.update(parameters or {})
    return {
        "space_id": identifier,
        "capability_id": identifier,
        "skill_name": capability["skill_name"],
        "cost_class": str((capability.get("cost") or {}).get("class", "unknown")),
        "tier": tier,
        "structurality": structurality,
        "metric": metric,
        "value_semantics": semantics,
        "calculation_version": capability["calculation_version"],
        "path": str(payload_path.resolve()),
        "parameters": effective_parameters,
    }


def _load_payload(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    header = pd.read_csv(path, nrows=0)
    dtypes = {"compound_id": "string"} if "compound_id" in header.columns else None
    return pd.read_csv(path, dtype=dtypes)


def _numeric_features(frame: pd.DataFrame) -> tuple[list[str], np.ndarray]:
    columns = [column for column in frame.columns if column not in COMMON_COLUMNS]
    if not columns:
        raise ValueError("Description payload has no feature columns")
    numeric = frame[columns].apply(pd.to_numeric, errors="coerce")
    return columns, numeric.to_numpy(dtype=float)


def _description_row_eligibility(
    frame: pd.DataFrame,
) -> tuple[np.ndarray, list[dict[str, str]]]:
    if "mol_parse_ok" in frame:
        parse_ok = frame["mol_parse_ok"].map(
            lambda value: value is True
            or str(value).strip().lower() in {"true", "1", "yes"}
        ).to_numpy(dtype=bool)
    else:
        parse_ok = np.ones(len(frame), dtype=bool)
    errors = (
        frame["description_error"].fillna("").astype(str)
        if "description_error" in frame
        else pd.Series("", index=frame.index, dtype=str)
    )
    eligible = parse_ok & errors.eq("").to_numpy(dtype=bool)
    ineligible: list[dict[str, str]] = []
    identifiers = frame["compound_id"].astype(str).tolist()
    for index in np.flatnonzero(~eligible):
        message = str(errors.iloc[index])
        reason = "invalid_smiles" if not parse_ok[index] else (
            "conformer_generation_failed"
            if message.strip() == "RDKit conformer generation failed"
            else "description_error"
        )
        ineligible.append(
            {
                "compound_id": identifiers[index],
                "reason": reason,
                "description_error": message,
            }
        )
    return eligible, ineligible


def compute_distance_matrix(payload_path: Path, space: dict[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    frame = _load_payload(payload_path)
    if "compound_id" not in frame.columns or frame["compound_id"].astype(str).duplicated().any():
        raise ValueError("Description payload requires unique compound_id values")
    columns, matrix = _numeric_features(frame)
    eligible, ineligible = _description_row_eligibility(frame)
    if not bool(eligible.any()):
        raise ValueError(f"No eligible compounds in {space['space_id']}")
    if space["metric"] == "tanimoto":
        matrix = np.nan_to_num(matrix, nan=0.0, posinf=0.0, neginf=0.0)
        dot = matrix @ matrix.T
        norm = np.einsum("ij,ij->i", matrix, matrix)
        denominator = norm[:, None] + norm[None, :] - dot
        similarity = np.divide(dot, denominator, out=np.zeros_like(dot), where=denominator > 0)
        distance = 1.0 - similarity
    else:
        finite_any = np.isfinite(matrix[eligible]).any(axis=0)
        matrix = matrix[:, finite_any]
        retained = [column for column, keep in zip(columns, finite_any, strict=True) if keep]
        if matrix.shape[1] == 0:
            raise ValueError(f"All features are missing in {space['space_id']}")
        row_has_finite = np.isfinite(matrix).any(axis=1)
        newly_ineligible = eligible & ~row_has_finite
        if bool(newly_ineligible.any()):
            identifiers = frame["compound_id"].astype(str).tolist()
            for index in np.flatnonzero(newly_ineligible):
                ineligible.append(
                    {
                        "compound_id": identifiers[index],
                        "reason": "no_finite_features",
                        "description_error": "",
                    }
                )
            eligible = eligible & row_has_finite
        if not bool(eligible.any()):
            raise ValueError(f"No eligible compounds in {space['space_id']}")
        medians = np.nanmedian(matrix[eligible], axis=0)
        missing = np.where(~np.isfinite(matrix))
        matrix[missing] = medians[missing[1]]
        standard_deviation = np.std(matrix[eligible], axis=0, ddof=0)
        keep = standard_deviation > 0
        matrix = matrix[:, keep]
        retained = [column for column, value in zip(retained, keep, strict=True) if value]
        if matrix.shape[1] == 0:
            raise ValueError(f"All features are constant in {space['space_id']}")
        matrix = (
            matrix - np.mean(matrix[eligible], axis=0)
        ) / np.std(matrix[eligible], axis=0, ddof=0)
        distance = squareform(pdist(matrix, metric="euclidean"))
        columns = retained
    distance = np.asarray(distance, dtype=np.float32)
    distance = (distance + distance.T) / np.float32(2.0)
    np.fill_diagonal(distance, 0.0)
    distance[~eligible, :] = np.nan
    distance[:, ~eligible] = np.nan
    compound_ids = frame["compound_id"].astype(str).tolist()
    metadata = {
        "schema_version": "0.2.1",
        "space_id": space["space_id"],
        "metric": space["metric"],
        "compound_ids": compound_ids,
        "eligible_compound_ids": [
            compound_id
            for compound_id, keep in zip(compound_ids, eligible, strict=True)
            if keep
        ],
        "ineligible_compounds": sorted(
            ineligible, key=lambda item: item["compound_id"]
        ),
        "eligible_count": int(eligible.sum()),
        "ineligible_count": int((~eligible).sum()),
        "feature_columns": columns,
        "shape": list(distance.shape),
        "dtype": "float32",
        "payload_sha256": file_sha256(payload_path),
    }
    return distance, metadata


def write_distance_artifact(payload_path: Path, space: dict[str, Any], output_directory: Path) -> dict[str, Any]:
    distance, metadata = compute_distance_matrix(payload_path, space)
    output_directory.mkdir(parents=True, exist_ok=True)
    matrix_path = output_directory / f"{space['space_id']}.npy"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{matrix_path.name}.", suffix=".tmp", dir=output_directory)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with temporary.open("wb") as handle:
            np.save(handle, distance, allow_pickle=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, matrix_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    metadata["matrix_path"] = str(matrix_path.resolve())
    metadata["matrix_sha256"] = file_sha256(matrix_path)
    metadata_path = output_directory / f"{space['space_id']}.json"
    atomic_write_json(metadata_path, metadata)
    return {**space, "distance_path": str(matrix_path.resolve()), "distance_metadata_path": str(metadata_path.resolve())}


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


def run_description_capability(
    *,
    project_root: Path,
    program_name: str,
    dataset_path: Path,
    id_column: str,
    smiles_column: str,
    capability: dict[str, Any],
    parameters: dict[str, Any],
    output_directory: Path,
    identity: dict[str, str],
    available_cpu_cores: int,
) -> tuple[Path, dict[str, Any]]:
    if available_cpu_cores < 1:
        raise ValueError("available_cpu_cores must be explicitly set to >= 1")
    skill_directory = Path(capability["_skill_path"])
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    legacy_identity = bridge_legacy_identity(
        identity,
        capability_id=str(capability["capability_id"]),
        skill_name=str(capability["skill_name"]),
    )
    command_parameters = dict(parameters)
    if str(capability["capability_id"]) == "D016":
        requested = int(
            command_parameters.get(
                "compound_workers",
                (capability.get("default_parameters") or {}).get("compound_workers", 8),
            )
        )
        command_parameters["compound_workers"] = min(requested, available_cpu_cores)
        command_parameters["available_cpu_cores"] = available_cpu_cores
    if str(capability["capability_id"]) == "D019":
        cores_per_compound = int(
            command_parameters.get(
                "cores_per_compound",
                (capability.get("implementation") or {}).get(
                    "default_cores_per_compound", 4
                ),
            )
        )
        command_parameters["cores_per_compound"] = cores_per_compound
        command_parameters.setdefault(
            "compound_workers", max(1, available_cpu_cores // cores_per_compound)
        )
        command_parameters["available_cpu_cores"] = available_cpu_cores
    environment = os.environ.copy()
    environment["CONDUCTOR_AVAILABLE_CPU_CORES"] = str(available_cpu_cores)
    environment["CONDUCTOR_NODE_CPU_CORES"] = str(available_cpu_cores)
    with tempfile.TemporaryDirectory(
        prefix=".conductor-description-cache-plan-",
        dir=output_directory.parent,
    ) as temporary_directory:
        plan = prepare_cache_plan(
            project_root=project_root,
            program_name=program_name,
            dataset_path=dataset_path,
            id_column=id_column,
            smiles_column=smiles_column,
            capability=capability,
            parameters=parameters,
            scratch=Path(temporary_directory),
            source_run_id=identity["run_id"],
        )
        plan["parameters"] = {
            **dict(capability.get("default_parameters") or {}),
            **parameters,
        }
        if plan["miss_count"]:
            command = [
                sys.executable,
                str(skill_directory / "scripts" / "launch.py"),
                "--input",
                str(plan["subset_path"]),
                "--id-column",
                id_column,
                "--smiles-column",
                smiles_column,
                "--output-dir",
                str(output_directory),
                "--format",
                "csv",
                "--conductor",
                "--project",
                legacy_identity["project"],
                "--run-id",
                legacy_identity["run_id"],
                "--round-id",
                legacy_identity["round_id"],
                "--node-id",
                legacy_identity["node_id"],
                "--attempt-id",
                legacy_identity["attempt_id"],
                *_parameter_arguments(command_parameters),
            ]
            completed = subprocess.run(
                command,
                cwd=project_root,
                env=environment,
                check=False,
                text=True,
                capture_output=True,
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    f"Description Skill {capability['skill_name']} failed with code {completed.returncode}: "
                    + completed.stderr[-2000:]
                )
            manifest = json.loads(
                (output_directory / "description_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            payload_name = str(manifest["output"])
            register_misses(
                plan=plan,
                payload_path=output_directory / payload_name,
                manifest=manifest,
                identity=legacy_identity,
            )
        request = {"identity": legacy_identity, "conductor_version": "0.2.1"}
        payload = finalize_cached_output(
            plan=plan,
            output=output_directory,
            request=request,
            capability=capability,
        )
        plan["subset_was_materialized"] = bool(plan["subset_path"])
        plan["subset_path"] = None
    return payload, plan


def build_feature_spaces(
    capabilities_and_payloads: Iterable[
        tuple[dict[str, Any], Path] | tuple[dict[str, Any], Path, dict[str, Any]]
    ],
    output_directory: Path,
) -> list[dict[str, Any]]:
    spaces: list[dict[str, Any]] = []
    distance_directory = output_directory / "distance"
    for item in capabilities_and_payloads:
        capability, payload = item[0], item[1]
        parameters = item[2] if len(item) == 3 else {}
        space = feature_space_metadata(capability, payload, parameters)
        spaces.append(write_distance_artifact(payload, space, distance_directory))
    spaces.sort(key=lambda item: item["space_id"])
    atomic_write_json(output_directory / "feature_spaces.json", {"schema_version": "0.2.1", "spaces": spaces})
    return spaces
