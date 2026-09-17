from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from rdkit import Chem
from scipy import stats

from conductor_stat_core import TestRecord, benjamini_hochberg, stable_id, validate_instance


COMPOUND_COLUMNS = [
    "row_id",
    "compound_id",
    "input_smiles",
    "canonical_smiles",
    "structure_sha256",
    "mol_parse_ok",
]
ENDPOINT_COLUMNS = [
    "row_id",
    "compound_id",
    "endpoint_id",
    "raw_value",
    "value",
    "oriented_value",
    "is_measured",
]
MISSINGNESS_COLUMNS = [
    "row_id",
    "target_endpoint_id",
    "compared_endpoint_id",
    "n_measured_group",
    "n_unmeasured_group",
    "rank_biserial",
    "p_value",
    "q_value",
    "selection_biased",
    "status",
]


@dataclass(frozen=True)
class Phase1Result:
    compounds: pd.DataFrame
    endpoints: pd.DataFrame
    missingness: pd.DataFrame
    registry: dict[str, Any]
    warnings: tuple[str, ...]


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _csv_write(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        frame.to_csv(handle, index=False, lineterminator="\n")


def _canonicalize_compounds(
    frame: pd.DataFrame, id_column: str, smiles_column: str
) -> pd.DataFrame:
    missing = [column for column in (id_column, smiles_column) if column not in frame.columns]
    if missing:
        raise ValueError(f"Dataset is missing required columns: {missing}")
    ids = frame[id_column].fillna("").astype(str).str.strip()
    if ids.eq("").any():
        rows = frame.index[ids.eq("")].tolist()[:10]
        raise ValueError(f"compound_id must be non-empty; invalid rows: {rows}")

    rows: list[dict[str, Any]] = []
    structures_by_id: dict[str, set[str]] = {}
    for compound_id, raw_smiles in zip(ids, frame[smiles_column], strict=True):
        input_smiles = "" if pd.isna(raw_smiles) else str(raw_smiles).strip()
        molecule = Chem.MolFromSmiles(input_smiles) if input_smiles else None
        canonical = (
            Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True)
            if molecule is not None
            else ""
        )
        structures_by_id.setdefault(compound_id, set()).add(canonical or f"INVALID:{input_smiles}")
        rows.append(
            {
                "row_id": stable_id("CMPROW", {"compound_id": compound_id}),
                "compound_id": compound_id,
                "input_smiles": input_smiles,
                "canonical_smiles": canonical,
                "structure_sha256": _sha256_text(canonical) if canonical else "",
                "mol_parse_ok": molecule is not None,
            }
        )

    conflicts = sorted(key for key, values in structures_by_id.items() if len(values) > 1)
    if conflicts:
        raise ValueError(
            "The same compound ID maps to different structures: " + ", ".join(conflicts[:10])
        )
    duplicated = ids[ids.duplicated(keep=False)].unique().tolist()
    if duplicated:
        raise ValueError("compound_id must be unique: " + ", ".join(sorted(duplicated)[:10]))
    result = pd.DataFrame(rows, columns=COMPOUND_COLUMNS)
    if not bool(result["mol_parse_ok"].any()):
        raise ValueError("All input SMILES are invalid")
    return result


def _transform(values: pd.Series, transform: str, compound_ids: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    raw = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    supplied = values.notna().to_numpy() & values.astype(str).str.strip().ne("").to_numpy()
    nonnumeric = supplied & ~np.isfinite(raw)
    if nonnumeric.any():
        bad = compound_ids[nonnumeric].astype(str).tolist()[:10]
        raise ValueError(f"Endpoint contains non-numeric values for compounds: {bad}")
    if transform == "none":
        return raw, raw.copy()
    invalid_domain = np.isfinite(raw) & (raw <= 0)
    if invalid_domain.any():
        bad = compound_ids[invalid_domain].astype(str).tolist()[:10]
        raise ValueError(f"Endpoint transform domain violation for compounds: {bad}")
    with np.errstate(divide="raise", invalid="raise"):
        if transform == "neg_log10":
            transformed = np.where(np.isfinite(raw), -np.log10(raw * 1e-9), np.nan)
        elif transform == "log10":
            transformed = np.where(np.isfinite(raw), np.log10(raw), np.nan)
        else:
            raise ValueError(f"Unknown Endpoint transform: {transform}")
    return raw, transformed


def _endpoint_table(
    source: pd.DataFrame,
    compounds: pd.DataFrame,
    registry: dict[str, Any],
    id_column: str,
) -> pd.DataFrame:
    ids = source[id_column].astype(str).str.strip()
    records: list[dict[str, Any]] = []
    for spec in registry["endpoints"]:
        column = spec["source_column"]
        if column not in source.columns:
            raise ValueError(f"Endpoint source column is missing: {column}")
        raw, transformed = _transform(source[column], spec["transform"], ids)
        oriented = transformed if spec["higher_is_better"] else -transformed
        for compound_id, raw_value, value, oriented_value in zip(
            ids, raw, transformed, oriented, strict=True
        ):
            measured = bool(math.isfinite(value))
            records.append(
                {
                    "row_id": stable_id(
                        "EPROW", {"compound_id": compound_id, "endpoint_id": spec["endpoint_id"]}
                    ),
                    "compound_id": compound_id,
                    "endpoint_id": spec["endpoint_id"],
                    "raw_value": raw_value if math.isfinite(raw_value) else "",
                    "value": value if measured else "",
                    "oriented_value": oriented_value if measured else "",
                    "is_measured": measured,
                }
            )
    return pd.DataFrame(records, columns=ENDPOINT_COLUMNS)


def _rank_biserial(u_statistic: float, n_left: int, n_right: int) -> float:
    return 2.0 * float(u_statistic) / (n_left * n_right) - 1.0


def _missingness_table(endpoint_table: pd.DataFrame, endpoint_ids: list[str]) -> pd.DataFrame:
    values = {
        endpoint_id: pd.to_numeric(
            endpoint_table.loc[endpoint_table["endpoint_id"] == endpoint_id, "oriented_value"],
            errors="coerce",
        ).to_numpy(dtype=float)
        for endpoint_id in endpoint_ids
    }
    records: list[dict[str, Any]] = []
    tests: list[TestRecord] = []
    for target in endpoint_ids:
        target_measured = np.isfinite(values[target])
        for compared in endpoint_ids:
            if compared == target:
                continue
            other = values[compared]
            measured = other[target_measured & np.isfinite(other)]
            unmeasured = other[~target_measured & np.isfinite(other)]
            row_id = stable_id("MISS", {"target": target, "compared": compared})
            if measured.size < 5 or unmeasured.size < 5:
                records.append(
                    {
                        "row_id": row_id,
                        "target_endpoint_id": target,
                        "compared_endpoint_id": compared,
                        "n_measured_group": int(measured.size),
                        "n_unmeasured_group": int(unmeasured.size),
                        "rank_biserial": "",
                        "p_value": "",
                        "q_value": "",
                        "selection_biased": False,
                        "status": "not_testable",
                    }
                )
                continue
            result = stats.mannwhitneyu(measured, unmeasured, alternative="two-sided")
            record = {
                "row_id": row_id,
                "target_endpoint_id": target,
                "compared_endpoint_id": compared,
                "n_measured_group": int(measured.size),
                "n_unmeasured_group": int(unmeasured.size),
                "rank_biserial": _rank_biserial(result.statistic, measured.size, unmeasured.size),
                "p_value": float(result.pvalue),
                "q_value": "",
                "selection_biased": False,
                "status": "tested",
            }
            records.append(record)
            tests.append(
                TestRecord(
                    candidate_key=row_id,
                    test_id=stable_id("TEST", {"row_id": row_id, "method": "mannwhitneyu"}),
                    family_key=f"missingness|{target}",
                    statistic=float(result.statistic),
                    alternative="two_sided_abs",
                    p_value=float(result.pvalue),
                )
            )
    q_by_row = {
        test.candidate_key: test.q_value for test in benjamini_hochberg(tests)
    }
    biased_targets = {
        record["target_endpoint_id"]
        for record in records
        if (q_value := q_by_row.get(record["row_id"])) is not None and q_value <= 0.05
    }
    for record in records:
        q_value = q_by_row.get(record["row_id"])
        if q_value is not None:
            record["q_value"] = q_value
        record["selection_biased"] = record["target_endpoint_id"] in biased_targets
    return pd.DataFrame(records, columns=MISSINGNESS_COLUMNS)


def prepare_phase1(
    *,
    dataset_path: Path,
    registry_path: Path,
    selected_endpoint_id: str,
    output_directory: Path,
    schema_directory: Path,
    id_column: str = "compound_id",
    smiles_column: str = "smiles",
) -> Phase1Result:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    validate_instance(registry, schema_directory / "endpoint_registry.schema.json")
    if registry["selected_endpoint_id"] != selected_endpoint_id:
        raise ValueError("Execution Request endpoint_id does not match endpoint registry")
    endpoint_ids = [spec["endpoint_id"] for spec in registry["endpoints"]]
    if selected_endpoint_id not in endpoint_ids:
        raise ValueError(f"Selected Endpoint is not registered: {selected_endpoint_id}")
    source = pd.read_csv(dataset_path)
    compounds = _canonicalize_compounds(source, id_column, smiles_column)
    endpoints = _endpoint_table(source, compounds, registry, id_column)
    missingness = _missingness_table(endpoints, endpoint_ids)
    warnings = [
        f"{int((~compounds['mol_parse_ok']).sum())} invalid SMILES were excluded from structure calculations"
    ] if (~compounds["mol_parse_ok"]).any() else []
    warnings.append("measurement.sigma is project-specific; confirm diagnosis before production use")
    output_directory.mkdir(parents=True, exist_ok=True)
    _csv_write(compounds, output_directory / "compounds.csv")
    _csv_write(endpoints, output_directory / "endpoints.csv")
    _csv_write(missingness, output_directory / "endpoint_missingness.csv")
    (output_directory / "endpoint_registry.json").write_text(
        json.dumps(registry, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return Phase1Result(compounds, endpoints, missingness, registry, tuple(warnings))
