from __future__ import annotations

import hashlib
import html
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


STANDALONE_VERSION = "0.1.11-standalone.1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(item) for item in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(clean_json(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def load_dataset(config: dict[str, Any]) -> tuple[pd.DataFrame, str, str, str]:
    path = Path(str(config["dataset_path"])).resolve()
    columns = config["columns"]
    compound_id = str(columns["compound_id"])
    smiles = str(columns["smiles"])
    endpoint = str(columns["endpoint"])
    header = pd.read_csv(path, nrows=0)
    frame = pd.read_csv(
        path,
        dtype={compound_id: "string"} if compound_id in header.columns else None,
    )
    missing = [
        column for column in (compound_id, smiles, endpoint)
        if column not in frame.columns
    ]
    if missing:
        raise ValueError(
            f"Dataset is missing configured columns {missing}; "
            f"available columns: {list(frame.columns)}"
        )
    if frame[compound_id].isna().any():
        raise ValueError("Dataset compound IDs must be non-null")
    frame[compound_id] = frame[compound_id].astype(str)
    duplicates = frame[compound_id].duplicated(keep=False)
    if duplicates.any():
        values = frame.loc[duplicates, compound_id].unique().tolist()
        raise ValueError(f"Dataset compound IDs must be unique: {values[:10]}")
    frame[endpoint] = pd.to_numeric(frame[endpoint], errors="coerce").replace(
        [np.inf, -np.inf], np.nan
    )
    return frame, compound_id, smiles, endpoint


def html_page(title: str, body: str) -> str:
    styles = """
*{box-sizing:border-box}body{margin:0;background:#f3f1ec;color:#243039;font-family:system-ui,-apple-system,'Segoe UI',sans-serif;line-height:1.6}main{max-width:1180px;min-width:0;margin:auto;padding:32px}h1,h2,h3{color:#263b45}.card{min-width:0;overflow:hidden;background:#fff;border:1px solid #d8d4ca;border-radius:10px;padding:20px;margin:16px 0;box-shadow:0 3px 12px #1d2d3520}.table-wrap{max-width:100%;overflow-x:auto;border:1px solid #e2ded6;border-radius:7px}table{border-collapse:collapse;width:max-content;min-width:100%;font-size:.9rem}th,td{border-bottom:1px solid #dedbd3;padding:7px;text-align:left;vertical-align:top;white-space:nowrap}th{background:#e8eceb;position:sticky;top:0;z-index:1}.metric-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}.metric{background:#f5f6f3;border-radius:7px;padding:10px 12px}.metric b{display:block;font-size:1.08rem}.pill{display:inline-block;border-radius:999px;padding:4px 9px;background:#eef1f2}.source{background:#edf6f0;color:#17643a}.muted{color:#69767c}img{max-width:100%;height:auto}a{color:#315f70}
"""
    return (
        '<!doctype html><html lang="ja"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{styles}</style></head>"
        f"<body><main>{body}</main></body></html>"
    )


def frame_html(frame: pd.DataFrame, limit: int = 200) -> str:
    if frame.empty:
        return "<p class='muted'>該当結果なし</p>"
    table = frame.head(limit).to_html(
        index=False, escape=True, border=0, na_rep="", classes=["sortable"]
    )
    return (
        "<div class='table-wrap' role='region' aria-label='表（横スクロール可能）' "
        f"tabindex='0'>{table}</div>"
    )


def finish_standalone(
    config: dict[str, Any],
    output: Path,
    *,
    primary: Path,
    summary: dict[str, Any],
    report: Path | None = None,
    extra_artifacts: Iterable[Path] = (),
    warnings: Iterable[str] = (),
) -> None:
    artifacts = [primary, *extra_artifacts]
    if report is not None and report not in artifacts:
        artifacts.append(report)
    rows = []
    seen: set[Path] = set()
    for candidate in artifacts:
        path = Path(candidate).resolve()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        try:
            relative = path.relative_to(output.resolve()).as_posix()
        except ValueError:
            # External inputs such as a reused database are recorded under
            # inputs, never misrepresented as newly generated artifacts.
            continue
        rows.append({
            "type": "primary" if path == primary.resolve() else "supporting",
            "path": relative,
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
        })
    input_rows = []
    for role, raw_path in (
        ("dataset", config.get("source_dataset_path")),
        ("mmp_database", config.get("database_path")),
    ):
        if not raw_path:
            continue
        path = Path(str(raw_path)).resolve()
        if path.is_file():
            input_rows.append({
                "role": role,
                "path": str(path),
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
            })
    summary_path = output / "standalone_run_summary.json"
    write_json(summary_path, {
        "schema_version": "1.0.0",
        "standalone_version": STANDALONE_VERSION,
        "status": "succeeded",
        **summary,
        "warnings": list(warnings),
    })
    rows.append({
        "type": "run_summary",
        "path": summary_path.name,
        "sha256": sha256(summary_path),
        "bytes": summary_path.stat().st_size,
    })
    write_json(output / "standalone_artifact_manifest.json", {
        "schema_version": "1.0.0",
        "standalone_version": STANDALONE_VERSION,
        "mode": config["parameters"]["mode"],
        "parameters": config["parameters"],
        "columns": config["columns"],
        "higher_is_better": bool(config["higher_is_better"]),
        "inputs": input_rows,
        "artifacts": rows,
        "created_at": utc_now(),
    })
