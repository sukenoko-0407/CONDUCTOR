from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from sal_config import detect_id_column
from sal_io import read_csv


NON_FEATURE_COLUMNS = {
    "compound_id",
    "canonical_smiles",
    "input_smiles",
    "original_smiles",
    "mol_parse_ok",
    "descriptor_error",
    "mol_error",
    "source_row_index",
    "row_index",
    "exclusion_reason",
}


def valid_property_table(df: pd.DataFrame, id_column: str, property_column: str) -> tuple[pd.DataFrame, list[str]]:
    warnings: list[str] = []
    work = df[[id_column, property_column]].copy()
    work[id_column] = work[id_column].astype(str).str.strip()
    missing_id = work[id_column].eq("") | work[id_column].isna()
    if bool(missing_id.any()):
        raise ValueError(f"Input ID column has missing values: {id_column}")
    duplicate_ids = work[id_column].duplicated(keep=False)
    if bool(duplicate_ids.any()):
        examples = sorted(work.loc[duplicate_ids, id_column].unique().tolist())[:10]
        raise ValueError(f"Input ID column has duplicated values: {examples}")

    numeric_property = pd.to_numeric(work[property_column], errors="coerce")
    invalid_property = numeric_property.isna()
    if bool(invalid_property.any()):
        warnings.append(f"Excluded {int(invalid_property.sum())} rows with missing or non-numeric property values.")
    work = work.loc[~invalid_property].copy()
    work["compound_id"] = work[id_column].astype(str)
    work["property"] = numeric_property.loc[~invalid_property].astype(float)
    return work[["compound_id", "property"]], warnings


def _scale_matrix(matrix: np.ndarray, scaling: str) -> np.ndarray:
    if scaling == "none":
        return matrix
    if scaling == "standard":
        means = matrix.mean(axis=0)
        stds = matrix.std(axis=0)
        stds[stds == 0] = 1.0
        return (matrix - means) / stds
    if scaling == "robust":
        med = np.median(matrix, axis=0)
        q75 = np.percentile(matrix, 75, axis=0)
        q25 = np.percentile(matrix, 25, axis=0)
        iqr = q75 - q25
        iqr[iqr == 0] = 1.0
        return (matrix - med) / iqr
    if scaling == "l2":
        norms = np.linalg.norm(matrix, axis=1)
        norms[norms == 0] = 1.0
        return matrix / norms[:, None]
    raise ValueError(f"Unsupported scaling: {scaling}")


def load_representation_matrix(
    descriptor_path: Path,
    property_table: pd.DataFrame,
    rep_config: dict[str, Any],
    feature_config: dict[str, Any],
) -> tuple[list[str], np.ndarray, np.ndarray, int, list[str]]:
    warnings: list[str] = []
    df = read_csv(descriptor_path)
    id_column = detect_id_column(list(df.columns), None)
    df[id_column] = df[id_column].astype(str).str.strip()
    if bool(df[id_column].duplicated().any()):
        duplicate_count = int(df[id_column].duplicated().sum())
        warnings.append(f"{descriptor_path.name}: dropped {duplicate_count} duplicate descriptor ID rows, keeping first occurrence.")
        df = df.drop_duplicates(subset=[id_column], keep="first")

    work = property_table.merge(df, left_on="compound_id", right_on=id_column, how="inner")
    if len(work) < len(property_table):
        warnings.append(f"{descriptor_path.name}: matched {len(work)} of {len(property_table)} property-valid compounds.")

    excluded = {col.lower() for col in NON_FEATURE_COLUMNS}
    numeric_features: list[pd.Series] = []
    feature_names: list[str] = []
    for col in work.columns:
        if str(col).lower() in excluded or col in {id_column, "compound_id", "property"}:
            continue
        numeric = pd.to_numeric(work[col], errors="coerce")
        if numeric.notna().any():
            numeric_features.append(numeric)
            feature_names.append(str(col))

    if not numeric_features:
        raise ValueError(f"{descriptor_path.name}: no numeric feature columns found.")

    features = pd.concat(numeric_features, axis=1)
    features.columns = feature_names
    if bool(feature_config.get("drop_constant_features", True)):
        keep = [col for col in features.columns if features[col].nunique(dropna=True) > 1]
        features = features[keep]
    if features.shape[1] == 0:
        raise ValueError(f"{descriptor_path.name}: all numeric features were constant.")

    if str(feature_config.get("missing_value_strategy", "median_impute")) == "median_impute":
        features = features.fillna(features.median(numeric_only=True)).fillna(0.0)
    else:
        features = features.fillna(0.0)

    matrix = features.to_numpy(dtype=float)
    matrix = _scale_matrix(matrix, str(rep_config.get("scaling", "none")))
    ids = work["compound_id"].astype(str).tolist()
    properties = work["property"].astype(float).to_numpy()
    return ids, properties, matrix, int(features.shape[1]), warnings

