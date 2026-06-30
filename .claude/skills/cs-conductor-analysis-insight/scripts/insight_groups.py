from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from insight_config import detect_id_column, detect_property_column
from insight_io import load_json, read_csv


def valid_property_table(
    df: pd.DataFrame,
    config: dict[str, Any],
    id_column: str | None,
    property_column: str | None,
) -> tuple[pd.DataFrame, str, str, list[str]]:
    warnings: list[str] = []
    id_col = detect_id_column(list(df.columns), id_column)
    prop_col = detect_property_column(list(df.columns), config, property_column)

    work = df[[id_col, prop_col]].copy()
    work[id_col] = work[id_col].astype(str).str.strip()
    missing_id = work[id_col].eq("") | work[id_col].isna()
    if bool(missing_id.any()):
        raise ValueError(f"Input ID column has missing values: {id_col}")
    duplicate_ids = work[id_col].duplicated(keep=False)
    if bool(duplicate_ids.any()):
        examples = sorted(work.loc[duplicate_ids, id_col].unique().tolist())[:10]
        raise ValueError(f"Input ID column has duplicated values: {examples}")

    numeric_property = pd.to_numeric(work[prop_col], errors="coerce")
    invalid_property = numeric_property.isna()
    if bool(invalid_property.any()):
        warnings.append(f"Excluded {int(invalid_property.sum())} rows with missing or non-numeric property values.")
    work = work.loc[~invalid_property].copy()
    work["compound_id"] = work[id_col].astype(str)
    work["property"] = numeric_property.loc[~invalid_property].astype(float)
    return work[["compound_id", "property"]], id_col, prop_col, warnings


def load_membership_matrix(path: Path) -> tuple[pd.DataFrame, str, list[str], list[str]]:
    warnings: list[str] = []
    df = read_csv(path)
    id_col = detect_id_column(list(df.columns), None)
    df[id_col] = df[id_col].astype(str).str.strip()
    if bool(df[id_col].duplicated().any()):
        examples = sorted(df.loc[df[id_col].duplicated(keep=False), id_col].unique().tolist())[:10]
        raise ValueError(f"Membership matrix has duplicated IDs: {examples}")
    group_columns = [column for column in df.columns if column != id_col]
    if not group_columns:
        raise ValueError("Membership matrix contains no group columns.")
    for column in group_columns:
        values = pd.to_numeric(df[column], errors="coerce")
        bad = ~values.isin([0, 1])
        if bool(bad.any()):
            raise ValueError(f"Membership column is not binary 0/1: {column}")
        df[column] = values.astype(np.int8)
    if id_col != "compound_id":
        df = df.rename(columns={id_col: "compound_id"})
        id_col = "compound_id"
    return df, id_col, group_columns, warnings


def load_registry(path: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    warnings: list[str] = []
    data = load_json(path)
    if isinstance(data, dict) and "groups" in data:
        entries = data["groups"]
    elif isinstance(data, list):
        entries = data
    else:
        raise ValueError("group_registry.json must be a list or contain a 'groups' list.")
    registry: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("group_id"):
            warnings.append("Skipped malformed group registry entry.")
            continue
        registry[str(entry["group_id"])] = entry
    return registry, warnings


def registry_fields(group_id: str, registry: dict[str, dict[str, Any]]) -> dict[str, Any]:
    entry = registry.get(group_id, {})
    definition = entry.get("definition", {}) if isinstance(entry.get("definition", {}), dict) else {}
    group_type = str(entry.get("group_type", ""))
    group_source = str(entry.get("group_source", ""))
    source_class = source_interpretability_class(group_type, group_source)
    tier, reason = interpretability(source_class, definition)
    return {
        "group_id": group_id,
        "group_label": entry.get("group_label", group_id),
        "group_type": group_type or "unknown",
        "group_source": group_source or "unknown",
        "registry_compound_count": entry.get("compound_count", np.nan),
        "source_column": entry.get("source_column"),
        "definition_method": definition.get("method"),
        "definition_source_descriptor_file": definition.get("source_descriptor_file"),
        "definition_parameter_set_id": definition.get("parameter_set_id"),
        "definition_fragment_smiles": definition.get("fragment_smiles"),
        "definition_scaffold_smiles": definition.get("scaffold_smiles"),
        "definition_mcs_smarts": definition.get("mcs_smarts"),
        "source_interpretability_class": source_class,
        "interpretability_tier": tier,
        "interpretability_reason": reason,
        "has_structure_motif": bool(
            definition.get("mcs_smarts") or definition.get("scaffold_smiles") or definition.get("fragment_smiles")
        ),
        "has_fragment_smiles": bool(definition.get("fragment_smiles")),
        "has_mcs_smarts": bool(definition.get("mcs_smarts")),
    }


def source_interpretability_class(group_type: str, group_source: str) -> str:
    text = f"{group_type} {group_source}".lower()
    if "fragment" in text or "brics" in text or "recap" in text:
        return "fragment_motif"
    if "mcs" in text or "murcko" in text or "scaffold" in text:
        return "direct_structure_motif"
    if "human" in text or "user" in text:
        return "human_defined"
    if "descriptor" in text:
        return "descriptor_cluster"
    if "similarity" in text:
        return "similarity_cluster"
    if "meta" in text:
        return "meta_group"
    return "unknown"


def interpretability(source_class: str, definition: dict[str, Any]) -> tuple[int, str]:
    if source_class in {"direct_structure_motif", "fragment_motif"}:
        return 1, "Direct structural motif or fragment evidence is available."
    if source_class == "human_defined":
        return 1, "Human-defined group source."
    if source_class in {"descriptor_cluster", "similarity_cluster"}:
        return 2, "Cluster-derived group; interpretation should use representatives and property trends."
    if source_class == "meta_group":
        return 3, "Meta group; inspect source groups for interpretation."
    return 4, "No direct interpretability annotation available."
