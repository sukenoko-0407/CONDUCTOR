from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


def read_csv(path: str | Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path)
    except Exception as exc:
        raise RuntimeError(f"CSV parse failed for {path}: {exc}") from exc


def write_json(path: str | Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def write_csv(path: str | Path, rows: list[dict[str, Any]] | pd.DataFrame, columns: list[str] | None = None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    if columns is not None:
        for column in columns:
            if column not in df.columns:
                df[column] = "" if len(df) else []
        df = df[columns]
    df.to_csv(path, index=False)


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(config_path: str | Path | None, default_path: str | Path | None = None) -> dict[str, Any]:
    config: dict[str, Any] = {}
    if default_path and Path(default_path).exists():
        config = load_json(default_path)
    if config_path:
        supplied = load_json(config_path)
        config = deep_merge(config, supplied)
    return config


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def validate_json_artifact(data: Any, schema_path: str | Path) -> list[str]:
    try:
        import jsonschema  # type: ignore
    except Exception:
        return [f"jsonschema is not installed; skipped validation for {Path(schema_path).name}."]

    try:
        schema = load_json(schema_path)
        jsonschema.validate(instance=data, schema=schema)
    except Exception as exc:
        return [f"Schema validation failed for {Path(schema_path).name}: {exc}"]
    return []


def write_context_aliases(outdir: str | Path) -> None:
    outdir = Path(outdir)
    aliases = {
        "group_registry.json": "context_registry.json",
        "group_membership.csv": "context_membership.csv",
        "group_relations.json": "context_relations.json",
        "selected_groups.json": "selected_contexts.json",
    }
    for source, target in aliases.items():
        src = outdir / source
        if src.exists():
            (outdir / target).write_bytes(src.read_bytes())
