from __future__ import annotations

import re
from pathlib import Path
from typing import Any


ID_COLUMN_CANDIDATES = [
    "compound_id",
    "Compound_ID",
    "ID",
    "id",
    "mol_id",
    "molecule_id",
    "Molecule_ID",
]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def find_column(columns: list[str], candidates: list[str]) -> str | None:
    normalized = {normalize_name(column): column for column in columns}
    for candidate in candidates:
        hit = normalized.get(normalize_name(candidate))
        if hit is not None:
            return hit
    return None


def detect_id_column(columns: list[str], explicit: str | None = None) -> str:
    if explicit:
        if explicit not in columns:
            raise ValueError(f"Specified ID column not found: {explicit}")
        return explicit
    detected = find_column(columns, ID_COLUMN_CANDIDATES)
    if detected is None:
        raise ValueError("Compound ID column could not be detected. Specify --id-column.")
    return detected


def detect_property_column(columns: list[str], config: dict[str, Any], explicit: str | None = None) -> str:
    if explicit:
        if explicit not in columns:
            raise ValueError(f"Specified property column not found: {explicit}")
        return explicit

    property_cfg = config.get("property", {}) or {}
    configured = property_cfg.get("column")
    if configured:
        if configured not in columns:
            raise ValueError(f"Configured property column not found: {configured}")
        return str(configured)

    if not bool(property_cfg.get("auto_detect", True)):
        raise ValueError("Property column is not configured and auto_detect is false.")

    preferred = [str(value) for value in property_cfg.get("preferred_names", [])]
    hits: list[str] = []
    normalized_columns = {normalize_name(column): column for column in columns}
    for name in preferred:
        hit = normalized_columns.get(normalize_name(name))
        if hit is not None and hit not in hits:
            hits.append(hit)

    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise ValueError(f"Multiple property column candidates found: {hits}. Specify --property-column.")
    raise ValueError("Property column could not be detected. Specify --property-column.")


def group_dir(input_path: str | Path, config: dict[str, Any], explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit)
    group_cfg = config.get("group_inputs", {}) or {}
    base_dir = Path(str(group_cfg.get("base_dir", "groups")))
    if not base_dir.is_absolute():
        base_dir = repo_root() / base_dir
    subdir = group_cfg.get("subdir")
    if subdir:
        return base_dir / str(subdir)
    return base_dir / Path(input_path).stem


def descriptions_dir(input_path: str | Path, config: dict[str, Any], explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit)
    div_cfg = config.get("structural_diversity", {}) or {}
    base_dir = Path(str(div_cfg.get("descriptor_base_dir", "descriptions")))
    if not base_dir.is_absolute():
        base_dir = repo_root() / base_dir
    subdir = div_cfg.get("descriptor_subdir")
    if subdir:
        return base_dir / str(subdir)
    return base_dir / Path(input_path).stem


def default_outdir(input_path: str | Path, config: dict[str, Any], explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit)
    outputs = config.get("outputs", {}) or {}
    base_dir = Path(str(outputs.get("base_dir", "analysis")))
    if not base_dir.is_absolute():
        base_dir = repo_root() / base_dir
    subdir = outputs.get("subdir")
    if subdir:
        return base_dir / str(subdir)
    return base_dir / Path(input_path).stem / "group_insight"
