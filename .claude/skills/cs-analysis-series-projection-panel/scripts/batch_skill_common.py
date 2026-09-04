from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


CONDUCTOR_VERSION = "0.1.10"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(clean_json(value), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def parse_request() -> tuple[dict[str, Any], Path, dict[str, Any]]:
    parser = argparse.ArgumentParser(description="CONDUCTOR 0.1.10 batch Skill")
    parser.add_argument("--request", required=True, help="Execution Request JSON")
    args = parser.parse_args()
    request_path = Path(args.request).resolve()
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if request.get("schema_version") != "1.0.0":
        raise ValueError(f"Unsupported Execution Request schema_version: {request.get('schema_version')!r}; expected '1.0.0'")
    output = Path(request.get("output", {}).get("directory", "")).resolve()
    if not str(request.get("output", {}).get("directory", "")).strip():
        raise ValueError("Execution Request output.directory is required")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Output directory must be empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    capability = json.loads((Path(__file__).resolve().parents[1] / "capability.json").read_text(encoding="utf-8"))
    expected = capability["capability_id"]
    actual = request.get("identity", {}).get("capability_id")
    if actual != expected:
        raise ValueError(f"Execution Request capability_id={actual!r} does not match this Skill ({expected})")
    return request, output, capability


def inputs(request: dict[str, Any], role: str) -> list[dict[str, Any]]:
    return [item for item in request.get("inputs", []) if item.get("role") == role]


def one_input(request: dict[str, Any], role: str, required: bool = True) -> dict[str, Any] | None:
    values = inputs(request, role)
    if not values:
        if required:
            available = sorted({str(item.get("role")) for item in request.get("inputs", [])})
            raise ValueError(f"Execution Request input role {role!r} is required; available roles: {available}")
        return None
    if len(values) != 1:
        raise ValueError(f"Execution Request input role {role!r} must occur exactly once; received {len(values)}")
    return values[0]


def input_path(request: dict[str, Any], role: str, required: bool = True) -> Path | None:
    item = one_input(request, role, required=required)
    if item is None:
        return None
    path = Path(str(item.get("path", ""))).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Input role {role!r} does not exist: {path}")
    return path


def read_table(path: Path, string_columns: Iterable[str] = ()) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        frame = pd.read_parquet(path)
        for column in string_columns:
            if column in frame.columns:
                frame[column] = frame[column].astype("string")
        return frame
    header = pd.read_csv(path, nrows=0)
    dtypes = {str(column): "string" for column in string_columns if str(column) in header.columns}
    return pd.read_csv(path, dtype=dtypes or None)


def dataset(request: dict[str, Any]) -> tuple[pd.DataFrame, str, str, str]:
    columns = request.get("columns", {})
    cid = str(columns.get("compound_id", "")); smiles = str(columns.get("smiles", "")); endpoint = str(columns.get("endpoint", ""))
    frame = read_table(input_path(request, "dataset"), [cid] if cid else [])
    missing = [column for column in (cid, smiles, endpoint) if not column or column not in frame.columns]
    if missing:
        raise ValueError(f"Dataset is missing configured columns {missing}; available columns: {list(frame.columns)}")
    if frame[cid].isna().any() or frame[cid].astype(str).duplicated().any():
        raise ValueError("Dataset compound IDs must be non-null and unique")
    frame[cid] = frame[cid].astype(str)
    frame[endpoint] = pd.to_numeric(frame[endpoint], errors="coerce").replace([np.inf, -np.inf], np.nan)
    return frame, cid, smiles, endpoint


def favorable_definition(frame: pd.DataFrame, endpoint: str, higher_is_better: bool, quantile: float = 0.8) -> tuple[float, pd.Series]:
    valid = frame[endpoint].dropna()
    if valid.empty:
        raise ValueError("Endpoint has no finite numeric values")
    threshold = float(valid.quantile(quantile if higher_is_better else 1.0 - quantile))
    favorable = frame[endpoint].ge(threshold) if higher_is_better else frame[endpoint].le(threshold)
    return threshold, favorable.fillna(False)


def membership_sets(path: Path) -> tuple[list[str], dict[str, set[str]]]:
    frame = read_table(path, ["compound_id", "cluster_id"])
    if "compound_id" not in frame.columns:
        raise ValueError(f"Membership table requires compound_id: {path}")
    frame["compound_id"] = frame["compound_id"].astype(str)
    if {"cluster_id", "membership_value"}.issubset(frame.columns):
        active = frame["membership_value"].astype(str).str.lower().isin({"true", "1", "1.0", "yes"}) | pd.to_numeric(frame["membership_value"], errors="coerce").fillna(0).gt(0)
        selected = frame.loc[active, ["compound_id", "cluster_id"]]
        sets = {str(key): set(part["compound_id"]) for key, part in selected.groupby("cluster_id", sort=True)}
        return sorted(set(frame["compound_id"])), sets
    columns = [str(column) for column in frame.columns if column != "compound_id"]
    sets: dict[str, set[str]] = {}
    for column in columns:
        active = frame[column].astype(str).str.lower().isin({"true", "1", "1.0", "yes"}) | pd.to_numeric(frame[column], errors="coerce").fillna(0).gt(0)
        sets[column] = set(frame.loc[active, "compound_id"])
    return list(frame["compound_id"]), sets


def analysis_units(request: dict[str, Any], include_global: bool = True) -> dict[str, set[str]]:
    path = input_path(request, "analysis_unit_membership")
    frame = read_table(path, ["compound_id", "analysis_unit_id"])
    if "compound_id" not in frame.columns:
        raise ValueError(f"Analysis-unit membership requires compound_id: {path}")
    frame["compound_id"] = frame["compound_id"].astype(str)
    all_ids = sorted(set(frame["compound_id"]))
    if "analysis_unit_id" in frame.columns:
        frame["analysis_unit_id"] = frame["analysis_unit_id"].astype(str)
        if "membership_value" in frame.columns:
            active = frame["membership_value"].astype(str).str.lower().isin({"true", "1", "1.0", "yes"}) | pd.to_numeric(frame["membership_value"], errors="coerce").fillna(0).gt(0)
            frame = frame.loc[active]
        values = {
            str(unit_id): set(part["compound_id"])
            for unit_id, part in frame.groupby("analysis_unit_id", sort=True)
            if str(unit_id) != "GLOBAL"
        }
    else:
        all_ids, values = membership_sets(path)
        values.pop("GLOBAL", None)
    if include_global:
        values = {"GLOBAL": set(all_ids), **values}
    return values


def bh_qvalues(pvalues: Iterable[float]) -> np.ndarray:
    values = np.asarray(list(pvalues), dtype=float)
    result = np.full(len(values), np.nan)
    valid = np.flatnonzero(np.isfinite(values))
    if not len(valid):
        return result
    order = valid[np.argsort(values[valid])]
    ranked = values[order] * len(order) / np.arange(1, len(order) + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    result[order] = np.minimum(ranked, 1.0)
    return result


def numeric_features(frame: pd.DataFrame, excluded: Iterable[str]) -> tuple[pd.DataFrame, list[str]]:
    excluded_set = set(excluded) | {
        "input_smiles", "canonical_smiles", "mol_parse_ok",
        "description_error", "descriptor_error",
    }
    columns: list[str] = []
    converted: dict[str, pd.Series] = {}
    for column in frame.columns:
        source = frame[column]
        if column in excluded_set or pd.api.types.is_bool_dtype(source.dtype):
            continue
        values = pd.to_numeric(source, errors="coerce")
        if pd.api.types.is_bool_dtype(values.dtype):
            continue
        values = values.astype(float).replace([np.inf, -np.inf], np.nan)
        if values.notna().sum() >= 3:
            columns.append(str(column)); converted[str(column)] = values
    return pd.DataFrame(converted, index=frame.index), columns


def description_table(request: dict[str, Any], capability_id: str | None = None) -> tuple[pd.DataFrame, str]:
    candidates = inputs(request, "description")
    if capability_id:
        candidates = [item for item in candidates if item.get("source_capability_id") == capability_id]
    if not candidates:
        raise ValueError(f"No Description input matched capability {capability_id or '*'}")
    item = candidates[0]
    path = Path(item["path"])
    frame = read_table(path, ["compound_id", "id", "molecule_id"])
    id_candidates = [column for column in frame.columns if str(column).lower() in {"compound_id", "id", "molecule_id"}]
    if not id_candidates:
        raise ValueError(f"Description artifact has no compound ID column: {item['path']}")
    cid = str(id_candidates[0]); frame[cid] = frame[cid].astype(str)
    return frame, cid


def image_uri(path: Path) -> str:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/svg+xml"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def html_page(title: str, body: str) -> str:
    styles = """
*{box-sizing:border-box}body{margin:0;background:#f3f1ec;color:#243039;font-family:system-ui,-apple-system,'Segoe UI',sans-serif;line-height:1.6}main{max-width:1180px;min-width:0;margin:auto;padding:32px}h1,h2,h3{color:#263b45}.card{min-width:0;overflow:hidden;background:#fff;border:1px solid #d8d4ca;border-radius:10px;padding:20px;margin:16px 0;box-shadow:0 3px 12px #1d2d3520}.table-wrap{max-width:100%;overflow-x:auto;overscroll-behavior-inline:contain;border:1px solid #e2ded6;border-radius:7px}table{border-collapse:collapse;width:max-content;min-width:100%;max-width:none;font-size:.9rem}th,td{border-bottom:1px solid #dedbd3;padding:7px;text-align:left;vertical-align:top;white-space:nowrap}th{background:#e8eceb;position:sticky;top:0;z-index:1}table.sortable th{cursor:pointer;user-select:none;padding-right:20px}table.sortable th[data-sort-direction='asc']::after{content:' ▲';font-size:.72em}table.sortable th[data-sort-direction='desc']::after{content:' ▼';font-size:.72em}.metric-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}.metric{background:#f5f6f3;border-radius:7px;padding:10px 12px}.metric b{display:block;font-size:1.08rem}.link-grid{columns:3 220px}.good{color:#7b3f26;font-weight:700}.warning{color:#8a5b24;font-weight:700}.muted{color:#69767c}img{max-width:100%;height:auto}code{background:#eef0ed;padding:2px 5px}a{color:#315f70}details.report-table{margin:10px 0}details.report-table>summary,details.column-help>summary,details.neighbor-structure-gallery>summary{cursor:pointer;color:#315f70;font-weight:650}details.report-table>.table-wrap{margin-top:8px}details.column-help,details.neighbor-structure-gallery{margin:8px 2px 2px}details.column-help dl{display:grid;grid-template-columns:minmax(130px,220px) 1fr;gap:4px 12px;margin:8px 0}details.column-help dt{font-weight:650}details.column-help dd{margin:0}.report-figure{width:100%;max-width:100%;height:auto}.summary-distribution-figure{display:block;width:min(860px,88%);max-width:100%;height:auto;margin:14px auto 24px}.single-target-structure img{width:min(420px,100%)}.neighbor-structure-gallery figure{margin:12px 0}.core-summary-layout{display:grid;grid-template-columns:minmax(220px,360px) minmax(160px,240px);gap:20px;align-items:center}.core-structure-image{width:100%;max-width:340px}.metric-stack{display:grid;gap:10px}@media(max-width:700px){main{padding:16px}.card{padding:14px}.link-grid{columns:1}.summary-distribution-figure{width:100%}.core-summary-layout{grid-template-columns:1fr}details.column-help dl{grid-template-columns:1fr}details.column-help dd{margin:0 0 6px}}
"""
    script = r"""
<script>
document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('table.sortable').forEach(function (table) {
    var body = table.tBodies[0];
    if (!body) return;
    table.querySelectorAll('thead th').forEach(function (header, columnIndex) {
      header.tabIndex = 0;
      header.setAttribute('role', 'button');
      header.setAttribute('title', 'クリックして並べ替え');
      var sortColumn = function () {
        var ascending = header.dataset.sortDirection !== 'asc';
        table.querySelectorAll('thead th').forEach(function (item) {
          delete item.dataset.sortDirection;
          item.removeAttribute('aria-sort');
        });
        header.dataset.sortDirection = ascending ? 'asc' : 'desc';
        header.setAttribute('aria-sort', ascending ? 'ascending' : 'descending');
        var rows = Array.from(body.rows).map(function (row, position) {
          return {row: row, position: position};
        });
        var value = function (row) {
          var text = (row.cells[columnIndex]?.textContent || '').trim();
          var normalized = text.replace(/,/g, '');
          var numeric = /^-?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(normalized);
          return {text: text.toLocaleLowerCase('ja'), number: numeric ? Number(normalized) : null};
        };
        rows.sort(function (left, right) {
          var a = value(left.row), b = value(right.row), comparison = 0;
          if (a.number !== null && b.number !== null) comparison = a.number - b.number;
          else comparison = a.text.localeCompare(b.text, 'ja', {numeric: true});
          if (comparison === 0) comparison = left.position - right.position;
          return ascending ? comparison : -comparison;
        });
        rows.forEach(function (item) { body.appendChild(item.row); });
      };
      header.addEventListener('click', sortColumn);
      header.addEventListener('keydown', function (event) {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          sortColumn();
        }
      });
    });
  });
});
</script>
"""
    return (
        '<!doctype html><html lang="ja"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{styles}</style></head>"
        f"<body><main>{body}</main>{script}</body></html>"
    )


def frame_html(frame: pd.DataFrame, limit: int = 200) -> str:
    if frame.empty:
        return "<p class='muted'>該当結果なし</p>"
    table = frame.head(limit).to_html(
        index=False, escape=True, border=0, na_rep="", classes=["sortable"]
    )
    return f"<div class='table-wrap' role='region' aria-label='表（横スクロール可能）' tabindex='0'>{table}</div>"


def finish(
    request: dict[str, Any], output: Path, capability: dict[str, Any],
    *, primary: Path, summary: dict[str, Any], report: Path | None = None,
    extra_artifacts: Iterable[Path] = (), warnings: Iterable[str] = (),
) -> None:
    identity = request["identity"]
    artifacts = [primary, *extra_artifacts]
    if report is not None and report not in artifacts:
        artifacts.append(report)
    artifact_rows = [{"type": "primary" if path == primary else "supporting", "path": str(path.relative_to(output)), "sha256": sha256(path)} for path in artifacts if path.is_file()]
    summary_path = output / "operator_summary.json"
    write_json(summary_path, {"schema_version": "1.0.0", "conductor_version": CONDUCTOR_VERSION, "capability_id": capability["capability_id"], "status": "succeeded", **summary, "warnings": list(warnings)})
    artifact_rows.append({"type": "operator_summary", "path": summary_path.name, "sha256": sha256(summary_path)})
    manifest_path = output / ("clustering_manifest.json" if capability.get("stage") == "clustering" else "analysis_manifest.json")
    write_json(manifest_path, {"schema_version": "1.0.0", "conductor_version": CONDUCTOR_VERSION, "identity": identity, "capability": capability["capability_id"], "parameters": request.get("parameters", {}), "inputs": request.get("inputs", []), "artifacts": artifact_rows, "created_at": utc_now()})
    artifact_rows.append({"type": "manifest", "path": manifest_path.name, "sha256": sha256(manifest_path)})
    write_json(output / "execution_event.json", {"schema_version": "1.0.0", "conductor_version": CONDUCTOR_VERSION, **identity, "status": "succeeded", "artifacts": artifact_rows, "warnings": list(warnings), "finished_at": utc_now()})
