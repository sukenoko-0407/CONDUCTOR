from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from grouping_io import read_csv, write_json

try:
    from rdkit import Chem  # type: ignore
    from rdkit import RDLogger  # type: ignore

    RDLogger.DisableLog("rdApp.error")
    RDLogger.DisableLog("rdApp.warning")
    RDKIT_AVAILABLE = True
except Exception:
    Chem = None
    RDKIT_AVAILABLE = False


ID_NAMES = {
    "compoundid",
    "compound id",
    "compound_id",
    "moleculeid",
    "molecule id",
    "molecule_id",
    "molid",
    "mol id",
    "mol_id",
    "cid",
    "id",
    "name",
    "compound",
    "molecule",
    "code",
}

SMILES_NAMES = {
    "smiles",
    "canonicalsmiles",
    "canonical smiles",
    "canonical_smiles",
    "isomericsmiles",
    "isomeric smiles",
    "isomeric_smiles",
    "structure",
    "structurestring",
    "structure string",
    "molsmiles",
    "mol_smiles",
    "moleculesmiles",
    "molecule_smiles",
}

GROUP_NAMES = {
    "group",
    "grouping",
    "series",
    "subseries",
    "scaffold",
    "chemotype",
    "core",
    "coreid",
    "core_id",
    "cluster",
    "class",
    "family",
    "humanseries",
    "human_series",
    "humanscaffold",
    "human_scaffold",
    "projectgroup",
    "project_group",
    "campaign",
}

VIRTUAL_NAMES = {"isvirtual", "is_virtual", "virtual", "wetvirtual", "wet_virtual", "source_type", "compound_type"}
ACTIVITY_NAMES = {"pic50", "ic50", "activity", "activityvalue", "activity_value"}
ACTIVITY_UNIT_NAMES = {"activityunit", "activity_unit", "unit", "units", "ic50unit", "ic50_unit"}
ACTIVITY_TYPE_NAMES = {"activitytype", "activity_type", "assaytype", "assay_type", "endpoint"}


def normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name).strip().lower())


def spaced_name(name: str) -> str:
    return re.sub(r"[_\-]+", " ", str(name).strip().lower())


def name_score(column: str, candidates: set[str]) -> float:
    norm = normalize_name(column)
    spaced = spaced_name(column)
    candidate_norms = {normalize_name(item) for item in candidates}
    if norm in candidate_norms:
        return 1.0
    if any(norm.endswith(candidate) or candidate.endswith(norm) for candidate in candidate_norms if len(candidate) >= 3):
        return 0.7
    tokens = set(re.split(r"[^a-z0-9]+", spaced))
    candidate_tokens = {token for item in candidates for token in re.split(r"[^a-z0-9]+", item) if token}
    if tokens & candidate_tokens:
        return 0.45
    return 0.0


def non_missing_values(series: pd.Series, limit: int = 300) -> list[str]:
    values = series.dropna().astype(str).map(str.strip)
    values = values[values != ""]
    return values.head(limit).tolist()


def fallback_smiles_like(value: str) -> bool:
    text = str(value).strip()
    if not text or len(text) > 500:
        return False
    allowed = set("0123456789@+-#%=()[]/\\.:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
    if any(char not in allowed for char in text):
        return False
    atom_tokens = ["Cl", "Br", "Si", "Se", "Na", "Li", "Mg", "Ca", "Al", "B", "C", "N", "O", "P", "S", "F", "I", "H", "K", "b", "c", "n", "o", "p", "s"]
    atom_count = 0
    i = 0
    while i < len(text):
        char = text[i]
        if char.isalpha():
            matched = next((token for token in atom_tokens if text.startswith(token, i)), None)
            if matched is None:
                return False
            atom_count += 1
            i += len(matched)
            continue
        i += 1
    return atom_count > 0


def smiles_valid_ratio(series: pd.Series) -> tuple[float, int, int, str]:
    values = non_missing_values(series)
    if not values:
        return 0.0, 0, 0, "rdkit" if RDKIT_AVAILABLE else "heuristic"
    valid = 0
    if RDKIT_AVAILABLE:
        for value in values:
            try:
                valid += int(Chem.MolFromSmiles(value) is not None)
            except Exception:
                pass
        method = "rdkit"
    else:
        valid = sum(1 for value in values if fallback_smiles_like(value))
        method = "heuristic"
    return valid / len(values), valid, len(values), method


def missing_ratio(series: pd.Series) -> float:
    if len(series) == 0:
        return 1.0
    empty = series.isna() | (series.astype(str).str.strip() == "")
    return float(empty.sum() / len(series))


def unique_ratio(series: pd.Series) -> float:
    values = non_missing_values(series, limit=len(series))
    if not values:
        return 0.0
    return len(set(values)) / len(values)


def numeric_sequence_penalty(series: pd.Series) -> float:
    values = non_missing_values(series, limit=len(series))
    if len(values) < 2:
        return 0.0
    try:
        numbers = [float(value) for value in values]
    except Exception:
        return 0.0
    diffs = [round(numbers[i + 1] - numbers[i], 8) for i in range(len(numbers) - 1)]
    if len(set(diffs)) == 1:
        return 0.25
    return 0.0


def string_likeness(series: pd.Series) -> float:
    values = non_missing_values(series)
    if not values:
        return 0.0
    non_numeric = 0
    for value in values:
        try:
            float(value)
        except Exception:
            non_numeric += 1
    return non_numeric / len(values)


def confidence_from_ratio(ratio: float) -> str:
    if ratio >= 0.85:
        return "high"
    if ratio >= 0.50:
        return "medium"
    return "low"


def score_smiles_candidates(df: pd.DataFrame) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for column in df.columns:
        ratio, valid_count, sample_count, method = smiles_valid_ratio(df[column])
        miss = missing_ratio(df[column])
        nscore = name_score(column, SMILES_NAMES)
        score = (2.8 * ratio) + (1.6 * nscore) + (0.4 * (1 - miss))
        candidates.append(
            {
                "column": column,
                "score": round(score, 6),
                "name_score": round(nscore, 6),
                "valid_smiles_ratio": round(ratio, 6),
                "valid_count": valid_count,
                "sample_count": sample_count,
                "missing_ratio": round(miss, 6),
                "confidence": confidence_from_ratio(ratio),
                "validation_method": method,
            }
        )
    return sorted(candidates, key=lambda item: (-item["score"], item["column"]))


def score_id_candidates(df: pd.DataFrame, smiles_column: str | None) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for column in df.columns:
        if column == smiles_column:
            continue
        miss = missing_ratio(df[column])
        uniq = unique_ratio(df[column])
        str_like = string_likeness(df[column])
        smiles_ratio, _, _, _ = smiles_valid_ratio(df[column])
        nscore = name_score(column, ID_NAMES)
        score = (1.8 * nscore) + (1.2 * (1 - miss)) + (1.0 * uniq) + (0.3 * str_like)
        score -= 1.3 * smiles_ratio
        score -= numeric_sequence_penalty(df[column])
        candidates.append(
            {
                "column": column,
                "score": round(score, 6),
                "name_score": round(nscore, 6),
                "missing_ratio": round(miss, 6),
                "unique_ratio": round(uniq, 6),
                "string_likeness": round(str_like, 6),
                "smiles_like_ratio": round(smiles_ratio, 6),
            }
        )
    return sorted(candidates, key=lambda item: (-item["score"], item["column"]))


def detect_grouping_candidates(df: pd.DataFrame, excluded: set[str]) -> list[dict[str, Any]]:
    n_rows = len(df)
    max_unique = max(50, int(math.ceil(0.5 * n_rows)))
    candidates: list[dict[str, Any]] = []
    for column in df.columns:
        if column in excluded:
            continue
        values = non_missing_values(df[column], limit=len(df))
        if not values:
            continue
        unique_count = len(set(values))
        if unique_count < 2 or unique_count > max_unique:
            continue
        if unique_count / max(1, len(values)) >= 0.9:
            continue
        nscore = name_score(column, GROUP_NAMES)
        if nscore <= 0 and unique_count > max(20, int(0.25 * n_rows)):
            continue
        candidates.append(
            {
                "column": column,
                "score": round(nscore + (1 - missing_ratio(df[column])) + min(0.5, unique_count / max(n_rows, 1)), 6),
                "name_score": round(nscore, 6),
                "unique_value_count": unique_count,
                "missing_ratio": round(missing_ratio(df[column]), 6),
            }
        )
    return sorted(candidates, key=lambda item: (-item["score"], item["column"]))


def detect_named_column(df: pd.DataFrame, names: set[str], excluded: set[str]) -> str | None:
    scored = [
        (name_score(column, names), column)
        for column in df.columns
        if column not in excluded and name_score(column, names) > 0
    ]
    if not scored:
        return None
    return sorted(scored, key=lambda item: (-item[0], item[1]))[0][1]


def detect_columns(df: pd.DataFrame, supplied: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    supplied = supplied or {}
    warnings: list[str] = []
    if not RDKIT_AVAILABLE:
        warnings.append("RDKit is not installed; SMILES detection used a conservative heuristic.")

    smiles_candidates = score_smiles_candidates(df)
    supplied_smiles = supplied.get("smiles_column")
    smiles_column = supplied_smiles if supplied_smiles in df.columns else None
    if supplied_smiles and supplied_smiles not in df.columns:
        warnings.append(f"Supplied SMILES column not found: {supplied_smiles}")
    if smiles_column is None and smiles_candidates:
        top = smiles_candidates[0]
        smiles_column = top["column"] if top["valid_smiles_ratio"] >= 0.5 or top["name_score"] >= 0.7 else None

    id_candidates = score_id_candidates(df, smiles_column)
    supplied_id = supplied.get("id_column")
    id_column = supplied_id if supplied_id in df.columns else None
    if supplied_id and supplied_id not in df.columns:
        warnings.append(f"Supplied ID column not found: {supplied_id}")
    if id_column is None and id_candidates:
        id_column = id_candidates[0]["column"]

    excluded = {column for column in [id_column, smiles_column] if column}
    is_virtual_column = supplied.get("is_virtual_column") if supplied.get("is_virtual_column") in df.columns else None
    if is_virtual_column is None:
        is_virtual_column = detect_named_column(df, VIRTUAL_NAMES, excluded)
    if is_virtual_column:
        excluded.add(is_virtual_column)

    activity_column = supplied.get("activity_column") if supplied.get("activity_column") in df.columns else None
    if activity_column is None:
        activity_column = detect_named_column(df, ACTIVITY_NAMES, excluded)
    if activity_column:
        excluded.add(activity_column)
    activity_unit_column = detect_named_column(df, ACTIVITY_UNIT_NAMES, excluded)
    if activity_unit_column:
        excluded.add(activity_unit_column)
    activity_type_column = detect_named_column(df, ACTIVITY_TYPE_NAMES, excluded)
    if activity_type_column:
        excluded.add(activity_type_column)

    grouping_columns = [column for column in supplied.get("grouping_columns", []) if column in df.columns]
    missing_grouping = [column for column in supplied.get("grouping_columns", []) if column not in df.columns]
    for column in missing_grouping:
        warnings.append(f"Supplied grouping column not found: {column}")
    grouping_candidates = detect_grouping_candidates(df, excluded)
    if not grouping_columns:
        grouping_columns = [item["column"] for item in grouping_candidates if item["name_score"] > 0 or item["score"] >= 1.2]

    ambiguous: list[dict[str, Any]] = []
    if len(smiles_candidates) >= 2:
        first, second = smiles_candidates[0], smiles_candidates[1]
        if (
            first["confidence"] == "high"
            and second["confidence"] == "high"
            and abs(first["score"] - second["score"]) <= 0.15
        ):
            ambiguous.append({"type": "smiles_column", "candidates": [first["column"], second["column"]]})
    if len(id_candidates) >= 2:
        first, second = id_candidates[0], id_candidates[1]
        if abs(first["score"] - second["score"]) <= 0.15 and first["score"] >= 1.8 and second["score"] >= 1.8:
            ambiguous.append({"type": "id_column", "candidates": [first["column"], second["column"]]})

    if smiles_column is None:
        warnings.append("SMILES column could not be confidently detected.")
    elif smiles_candidates and smiles_candidates[0]["column"] == smiles_column and smiles_candidates[0]["valid_smiles_ratio"] < 0.5:
        warnings.append(f"Detected SMILES column has low valid ratio: {smiles_column}")

    if id_column is None:
        warnings.append("Molecule ID column could not be detected.")
    elif id_candidates and id_candidates[0]["column"] == id_column and id_candidates[0]["unique_ratio"] < 0.9:
        warnings.append(f"Detected ID column is not mostly unique: {id_column}")

    if not is_virtual_column:
        warnings.append("is_virtual column not found. All compounds are treated as Wet for grouping.")

    schema = {
        "id_column": id_column,
        "smiles_column": smiles_column,
        "is_virtual_column": is_virtual_column,
        "activity_column": activity_column,
        "activity_unit_column": activity_unit_column,
        "activity_type_column": activity_type_column,
        "grouping_columns": grouping_columns,
        "ambiguous": ambiguous,
        "rdkit_available": RDKIT_AVAILABLE,
    }
    report = {
        "row_count": int(len(df)),
        "columns": list(df.columns),
        "smiles_candidates": smiles_candidates,
        "id_candidates": id_candidates,
        "grouping_candidates": grouping_candidates,
    }
    return schema, report, warnings


def parse_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect Grouping input CSV columns.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--outdir", default=None)
    parser.add_argument("--id-column")
    parser.add_argument("--smiles-column")
    parser.add_argument("--grouping-columns")
    parser.add_argument("--is-virtual-column")
    args = parser.parse_args()

    outdir = Path(args.outdir) if args.outdir else SCRIPT_DIR.parents[3] / "groups" / Path(args.input).stem
    df = read_csv(args.input)
    supplied = {
        "id_column": args.id_column,
        "smiles_column": args.smiles_column,
        "grouping_columns": parse_list(args.grouping_columns),
        "is_virtual_column": args.is_virtual_column,
    }
    schema, report, warnings = detect_columns(df, supplied)
    write_json(outdir / "detected_schema.json", schema)
    write_json(outdir / "column_detection_report.json", report)
    write_json(outdir / "column_detection_warnings.json", warnings)
    print(f"Detected ID column: {schema.get('id_column')}")
    print(f"Detected SMILES column: {schema.get('smiles_column')}")
    if warnings:
        print(f"Warnings: {len(warnings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
