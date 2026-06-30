from __future__ import annotations

import math
import re
from typing import Any

import pandas as pd

try:
    from rdkit import Chem, rdBase
except ImportError:  # pragma: no cover - exercised in environments without RDKit
    Chem = None
    rdBase = None


SMILES_HIGH = {"smiles", "smi", "canonical_smiles", "structure", "mol_smiles"}
SMILES_MED = {"mol", "molecule", "compound", "structure_string"}
ID_HIGH = {"id", "compound_id", "cmpd_id", "mol_id", "molecule_id", "name", "compound_name"}
ID_MED = {"code", "registry", "sample_id"}


def _norm(name: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def _is_numeric_series(series: pd.Series) -> bool:
    non_null = series.dropna()
    if non_null.empty:
        return False
    converted = pd.to_numeric(non_null, errors="coerce")
    return converted.notna().mean() > 0.95


def _looks_like_id_value(value: Any) -> bool:
    if pd.isna(value):
        return False
    text = str(value).strip()
    if not text:
        return False
    if len(text) > 80:
        return False
    return bool(re.fullmatch(r"[A-Za-z]{0,12}[-_ ]?\d+[A-Za-z0-9_.-]*|[A-Za-z0-9_.-]{3,40}", text))


def _rdkit_smiles_ok(value: Any) -> bool:
    if pd.isna(value):
        return False
    text = str(value).strip()
    if len(text) < 2:
        return False
    if Chem is None:
        return bool(re.search(r"[CNOSPFIBrcnos=#@\[\]\(\)\\/]", text)) and " " not in text
    try:
        with rdBase.BlockLogs():
            return Chem.MolFromSmiles(text) is not None
    except Exception:
        return False


def _sample_values(series: pd.Series, limit: int = 200) -> pd.Series:
    values = series.dropna()
    if values.empty:
        return values
    return values.astype(str).head(limit)


def _score_smiles_column(series: pd.Series, name: str) -> tuple[float, dict[str, float]]:
    norm = _norm(name)
    values = _sample_values(series)
    if values.empty or series.isna().mean() > 0.95 or _is_numeric_series(series):
        return 0.0, {"name": 0.0, "valid_ratio": 0.0}

    name_score = 0.0
    if norm in SMILES_HIGH:
        name_score = 0.45
    elif norm in SMILES_MED or any(token in norm for token in ("smiles", "smi")):
        name_score = 0.28

    valid_ratio = sum(_rdkit_smiles_ok(v) for v in values) / max(len(values), 1)
    median_len = values.map(len).median()
    length_penalty = 0.12 if median_len < 2 else 0.0
    id_penalty = 0.18 if values.map(_looks_like_id_value).mean() > 0.9 and valid_ratio < 0.7 else 0.0
    score = max(0.0, name_score + 0.70 * valid_ratio - length_penalty - id_penalty)
    return min(score, 1.0), {"name": name_score, "valid_ratio": valid_ratio}


def _score_id_column(series: pd.Series, name: str, smiles_col: str | None) -> tuple[float, dict[str, float]]:
    if name == smiles_col:
        return 0.0, {"name": 0.0, "unique_ratio": 0.0, "non_smiles_ratio": 0.0}

    norm = _norm(name)
    values = _sample_values(series)
    if values.empty or series.isna().mean() > 0.95:
        return 0.0, {"name": 0.0, "unique_ratio": 0.0, "non_smiles_ratio": 0.0}

    name_score = 0.0
    if norm in ID_HIGH or norm.endswith("_id") or norm == "id":
        name_score = 0.45
    elif norm in ID_MED or "id" in norm or "name" in norm:
        name_score = 0.28

    unique_ratio = series.dropna().astype(str).nunique() / max(series.dropna().shape[0], 1)
    non_missing_ratio = 1.0 - float(series.isna().mean())
    smiles_ratio = sum(_rdkit_smiles_ok(v) for v in values) / max(len(values), 1)
    id_like_ratio = values.map(_looks_like_id_value).mean()
    score = name_score + 0.25 * unique_ratio + 0.20 * non_missing_ratio + 0.18 * id_like_ratio + 0.15 * (1.0 - smiles_ratio)
    if _is_numeric_series(series):
        score -= 0.05
    return max(0.0, min(score, 1.0)), {
        "name": name_score,
        "unique_ratio": unique_ratio,
        "non_smiles_ratio": 1.0 - smiles_ratio,
    }


def infer_columns(df: pd.DataFrame) -> dict[str, Any]:
    """Infer compound ID and SMILES columns from names and sampled values."""
    if df.empty and len(df.columns) == 0:
        return {
            "id_col": None,
            "smiles_col": None,
            "confidence": {"id_col": 0.0, "smiles_col": 0.0},
            "messages": ["Input table has no columns."],
        }

    messages: list[str] = []
    smiles_scores = [(col, *_score_smiles_column(df[col], col)) for col in df.columns]
    smiles_scores.sort(key=lambda item: item[1], reverse=True)
    smiles_col = smiles_scores[0][0] if smiles_scores and smiles_scores[0][1] >= 0.50 else None
    smiles_conf = smiles_scores[0][1] if smiles_scores else 0.0

    if smiles_col is None:
        messages.append("Could not infer SMILES column with confidence >= 0.50.")
    elif len(smiles_scores) > 1 and math.isclose(smiles_scores[0][1], smiles_scores[1][1], abs_tol=0.05):
        messages.append(f"SMILES column candidates are close: {smiles_scores[0][0]} and {smiles_scores[1][0]}.")

    id_scores = [(col, *_score_id_column(df[col], col, smiles_col)) for col in df.columns]
    id_scores.sort(key=lambda item: item[1], reverse=True)
    id_col = id_scores[0][0] if id_scores and id_scores[0][1] >= 0.45 else None
    id_conf = id_scores[0][1] if id_scores else 0.0

    if id_col is None:
        messages.append("Could not infer ID column; row_000001 style fallback IDs will be generated.")
    elif len(id_scores) > 1 and math.isclose(id_scores[0][1], id_scores[1][1], abs_tol=0.05):
        messages.append(f"ID column candidates are close: {id_scores[0][0]} and {id_scores[1][0]}.")

    return {
        "id_col": id_col,
        "smiles_col": smiles_col,
        "confidence": {"id_col": round(id_conf, 3), "smiles_col": round(smiles_conf, 3)},
        "messages": messages,
    }
