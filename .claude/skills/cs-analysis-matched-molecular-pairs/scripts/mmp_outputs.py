from __future__ import annotations

import html
import json
import math
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from rdkit import Chem
from rdkit.Chem.Draw import rdMolDraw2D

from mmp_engine import sha256_file, stable_id, robust_summary, utc_now


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        return _clean(value.item())
    return value


def load_database(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        details = pd.read_sql_query("SELECT * FROM mmp_pairs", connection)
        rows = connection.execute("SELECT key, value_json FROM metadata").fetchall()
    return details, {key: json.loads(value) for key, value in rows}


def load_membership(path: Path) -> tuple[pd.DataFrame, str, list[str]]:
    frame = pd.read_csv(path)
    cluster_columns = [column for column in frame.columns if str(column).startswith("C") and str(column)[1:].isdigit()]
    if not cluster_columns:
        raise ValueError("Cluster membership CSV has no Cnnnnnn Boolean columns")
    candidates = [column for column in frame.columns if column not in cluster_columns]
    if not candidates:
        raise ValueError("Cluster membership CSV has no compound ID column")
    id_column = next((column for column in candidates if str(column).lower() in {"compound_id", "id"}), candidates[0])
    frame[id_column] = frame[id_column].astype(str)
    for column in cluster_columns:
        values = frame[column]
        if values.dtype == bool:
            continue
        frame[column] = values.fillna(False).astype(str).str.lower().isin({"1", "true", "t", "yes", "y"})
    return frame, str(id_column), cluster_columns


def load_cluster_registry(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    if not path.is_file():
        raise FileNotFoundError(f"Cluster Registry does not exist: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    if text.startswith("["):
        rows = json.loads(text)
    else:
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    if not isinstance(rows, list):
        raise ValueError("Cluster Registry must be a JSON array or JSONL rows")
    return {str(row["cluster_id"]): row for row in rows if isinstance(row, dict) and row.get("cluster_id")}


def screen_clusters(database: Path, membership: Path, registry: Path | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    details, metadata = load_database(database)
    matrix, id_column, clusters = load_membership(membership)
    registry_rows = load_cluster_registry(registry)
    global_count = max(1, int(metadata.get("input_count") or len(matrix)))

    def unique_pair_count(frame: pd.DataFrame) -> int:
        if frame.empty:
            return 0
        return int(frame[["compound_id_from", "compound_id_to"]].drop_duplicates().shape[0])

    rows: list[dict[str, Any]] = []
    for cluster_id in clusters:
        members = set(matrix.loc[matrix[cluster_id], id_column])
        origin = registry_rows.get(cluster_id, {})
        clustering_capability = str(origin.get("clustering_capability_id", ""))
        clustering_input_kind = (
            "structure" if clustering_capability in {"C001", "C002", "C003", "C004"}
            else "vector" if clustering_capability in {"C005", "C006", "C007", "C008", "C009", "C010"}
            else "categorical" if clustering_capability == "C011"
            else "meta" if clustering_capability == "C012" else "unknown"
        )
        left = details["compound_id_from"].isin(members) if len(details) else pd.Series(dtype=bool)
        right = details["compound_id_to"].isin(members) if len(details) else pd.Series(dtype=bool)
        within = details[left & right] if len(details) else details
        boundary = details[left ^ right] if len(details) else details
        primary = within[within["core_class"].eq("primary")] if len(within) and "core_class" in within else within
        effects = (
            primary.assign(_effect=pd.to_numeric(primary["favorable_delta"], errors="coerce"))
            .groupby(["compound_id_from", "compound_id_to"], dropna=False)["_effect"].median().dropna()
            if len(primary) else pd.Series(dtype=float)
        )
        rows.append({
            "cluster_id": cluster_id,
            "clustering_node_id": origin.get("source_node_id", ""),
            "clustering_capability_id": clustering_capability,
            "clustering_input_kind": clustering_input_kind,
            "source_description_node_ids": "|".join(map(str, origin.get("source_description_node_ids", []))),
            "source_description_capability_ids": "|".join(map(str, origin.get("source_description_capability_ids", []))),
            "cluster_size": len(members), "global_fraction": len(members) / global_count,
            "within_mmp_instance_count": len(within),
            "within_pair_count": unique_pair_count(within),
            "primary_mmp_instance_count": len(primary),
            "primary_within_pair_count": unique_pair_count(primary),
            "extended_only_mmp_instance_count": len(within) - len(primary),
            "boundary_pair_count": unique_pair_count(boundary),
            "independent_transform_count": int(primary["transform_id"].nunique()) if len(primary) else 0,
            "independent_core_count": int(primary["core_id"].nunique()) if len(primary) else 0,
            "endpoint_pair_count": len(effects),
            "median_favorable_delta": float(effects.median()) if len(effects) else math.nan,
            "iqr_favorable_delta": float(effects.quantile(.75) - effects.quantile(.25)) if len(effects) else math.nan,
            "direction_consistency": float(max((effects > 0).mean(), (effects < 0).mean())) if len(effects) else math.nan,
            "screening_complete": True, "detail_complete": False,
            "negative_result": len(effects) == 0,
        })
    result = pd.DataFrame(rows).sort_values(["within_pair_count", "cluster_size"], ascending=False)
    return result, metadata


def detail_cluster(database: Path, membership: Path, cluster_id: str) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    details, metadata = load_database(database)
    matrix, id_column, clusters = load_membership(membership)
    if cluster_id not in clusters:
        raise ValueError(f"Unknown Cluster ID: {cluster_id}")
    members = set(matrix.loc[matrix[cluster_id], id_column])
    within = details[details["compound_id_from"].isin(members) & details["compound_id_to"].isin(members)].copy()
    global_primary = details[details["core_class"].eq("primary")].copy() if len(details) else details
    local_primary = within[within["core_class"].eq("primary")].copy() if len(within) else within
    global_summary = robust_summary(global_primary, ["transform_id", "transform_smirks"]).add_prefix("global_") if len(global_primary) else pd.DataFrame()
    local_summary = robust_summary(local_primary, ["transform_id", "transform_smirks"]).add_prefix("local_") if len(local_primary) else pd.DataFrame()
    if len(global_summary) and len(local_summary):
        comparison = local_summary.merge(
            global_summary,
            left_on=["local_transform_id", "local_transform_smirks"],
            right_on=["global_transform_id", "global_transform_smirks"],
            how="left",
        )
        comparison["median_shift_local_minus_global"] = comparison["local_median_favorable_delta"] - comparison["global_median_favorable_delta"]
        comparison["effect_comparable"] = comparison["local_median_favorable_delta"].notna() & comparison["global_median_favorable_delta"].notna()
        comparison["direction_reversal"] = comparison["effect_comparable"] & (np.sign(comparison["local_median_favorable_delta"]) != np.sign(comparison["global_median_favorable_delta"]))
    else:
        comparison = pd.DataFrame()
    metadata = dict(metadata)
    metadata.update({"cluster_id": cluster_id, "cluster_size": len(members)})
    return within, comparison, metadata


def make_reference_cards(
    details: pd.DataFrame,
    transforms: pd.DataFrame,
    transform_core: pd.DataFrame,
    *,
    scope: str,
    core_summary: pd.DataFrame | None = None,
    context_summary: pd.DataFrame | None = None,
    max_cards: int = 100,
) -> list[dict[str, Any]]:
    candidates: list[tuple[float, dict[str, Any]]] = []

    def add(category: str, score: float, headline: str, row: dict[str, Any], sources: list[str], flags: list[str]) -> None:
        identity = (category, scope, row.get("transform_id"), row.get("core_id"), sources[:5])
        candidates.append((float(score), {
            "schema_version": "1.0.0", "card_id": stable_id("MRC", *identity),
            "category": category, "scope": scope, "headline": headline,
            "support": {key: row.get(key) for key in ("mmp_instance_count", "pair_count", "endpoint_pair_count", "independent_compound_count", "independent_core_count")},
            "effect": {key: row.get(key) for key in ("favorable_delta", "median_favorable_delta", "iqr_favorable_delta", "direction_consistency", "core_weighted_median", "leave_one_core_out_sign_stability")},
            "transform_id": row.get("transform_id"), "core_id": row.get("core_id"),
            "structure": {key: row.get(key) for key in ("variable_from", "variable_to", "exact_core_smiles", "smiles_from", "smiles_to") if row.get(key)},
            "source_rows": sources[:20], "quality_flags": flags,
        }))

    if len(transforms):
        for row in transforms.to_dict(orient="records"):
            support = int(row.get("endpoint_pair_count") or 0)
            cores = int(row.get("independent_core_count") or 0)
            effect = row.get("median_favorable_delta")
            consistency = row.get("direction_consistency")
            if support >= 3 and cores >= 2 and pd.notna(effect) and pd.notna(consistency) and consistency >= .7:
                sources = details.loc[details["transform_id"] == row["transform_id"], "mmp_id"].tolist()
                add("portable_transform", support * cores * abs(float(effect)), "複数Coreで方向の揃った置換効果候補", row, sources, [])
            if support >= 3 and pd.notna(effect) and abs(float(effect)) <= .1:
                sources = details.loc[details["transform_id"] == row["transform_id"], "mmp_id"].tolist()
                add("flat_transform", support, "観測範囲で比較的平坦な置換候補", row, sources, [])
            if support >= 4 and pd.notna(consistency) and consistency < .6:
                sources = details.loc[details["transform_id"] == row["transform_id"], "mmp_id"].tolist()
                add("contradiction", support * (1 - float(consistency)), "同じ置換でEndpoint差の方向が揃わない候補", row, sources, ["direction_inconsistent"])
    if len(transform_core):
        for transform_id, group in transform_core.groupby("transform_id"):
            effects = group["median_favorable_delta"].dropna()
            if len(effects) >= 2 and effects.min() < 0 < effects.max():
                row = group.loc[effects.abs().idxmax()].to_dict()
                sources = details.loc[details["transform_id"] == transform_id, "mmp_id"].tolist()
                add("core_dependent", len(group) * float(effects.max() - effects.min()), "Exact Coreにより置換効果の方向が反転する候補", row, sources, ["core_sign_reversal"])
    if core_summary is not None and len(core_summary):
        for row in core_summary.sort_values(["endpoint_pair_count", "independent_core_count"], ascending=False).head(20).to_dict(orient="records"):
            sources = details.loc[details["core_id"] == row["core_id"], "mmp_id"].tolist()
            add("core_hotspot", max(1, int(row.get("endpoint_pair_count") or 0)) * abs(float(row.get("median_favorable_delta") or 0)), "複数MMPが集中するExact Core候補", row, sources, [])
    if context_summary is not None and len(context_summary):
        for (transform_id, radius), group in context_summary.groupby(["transform_id", "radius"]):
            effects = group["median_favorable_delta"].dropna()
            if len(effects) >= 2 and effects.min() < 0 < effects.max():
                row = group.loc[effects.abs().idxmax()].to_dict()
                row["transform_id"] = transform_id
                sources = details.loc[details["transform_id"] == transform_id, "mmp_id"].tolist()
                add("context_dependent", len(group) * float(effects.max() - effects.min()), f"Environment radius {radius}で周辺環境により方向が変わる候補", row, sources, ["context_sign_reversal"])
    if len(details):
        effect_rows = details.dropna(subset=["favorable_delta"]).copy()
        effect_rows["_absolute_effect"] = effect_rows["favorable_delta"].abs()
        for row in effect_rows.nlargest(min(20, len(effect_rows)), "_absolute_effect").to_dict(orient="records"):
            add("pair_cliff", abs(float(row["favorable_delta"])), "大きなEndpoint差を示す個別MMP", row, [row["mmp_id"]], ["single_pair"])
    candidates.sort(key=lambda item: (-item[0], item[1]["card_id"]))
    cards: list[dict[str, Any]] = []
    quota: dict[str, int] = {}
    for _, card in candidates:
        category = card["category"]
        if quota.get(category, 0) >= 20:
            continue
        cards.append(card)
        quota[category] = quota.get(category, 0) + 1
        if len(cards) >= max_cards:
            break
    if not cards:
        cards.append({
            "schema_version": "1.0.0", "card_id": stable_id("MRC", "coverage", scope),
            "category": "coverage", "scope": scope,
            "headline": "現条件では解釈候補となるMMP evidenceが得られなかった",
            "support": {"pair_count": int(len(details))}, "effect": {},
            "source_rows": [], "quality_flags": ["negative_result"],
        })
    return cards


def comparison_cards(comparison: pd.DataFrame, details: pd.DataFrame, scope: str, limit: int = 20) -> list[dict[str, Any]]:
    if comparison.empty or "effect_comparable" not in comparison:
        return []
    rows = comparison[comparison["effect_comparable"].fillna(False)].copy()
    if rows.empty:
        return []
    rows["_score"] = pd.to_numeric(rows.get("median_shift_local_minus_global"), errors="coerce").abs().fillna(0)
    rows = rows.sort_values(["direction_reversal", "_score"], ascending=False).head(limit)
    cards: list[dict[str, Any]] = []
    for row in rows.to_dict(orient="records"):
        transform_id = row.get("local_transform_id")
        sources = details.loc[details["transform_id"] == transform_id, "mmp_id"].head(20).tolist() if len(details) else []
        reversal = bool(row.get("direction_reversal"))
        cards.append({
            "schema_version": "1.0.0", "card_id": stable_id("MRC", "cluster", scope, transform_id),
            "category": "cluster_dependent", "scope": scope,
            "headline": "Cluster局所で置換効果の方向がGlobalから反転" if reversal else "Cluster局所で置換効果の大きさがGlobalから変化",
            "support": {"local_pair_count": row.get("local_pair_count"), "global_pair_count": row.get("global_pair_count"), "local_independent_core_count": row.get("local_independent_core_count")},
            "effect": {"local_median_favorable_delta": row.get("local_median_favorable_delta"), "global_median_favorable_delta": row.get("global_median_favorable_delta"), "local_minus_global": row.get("median_shift_local_minus_global")},
            "transform_id": transform_id, "source_rows": sources,
            "quality_flags": ["global_local_direction_reversal"] if reversal else [],
            "structure": {},
        })
    return cards


def _molecule_svg(smiles: str, legend: str) -> str:
    molecule = Chem.MolFromSmiles(str(smiles))
    if molecule is None:
        return ""
    drawer = rdMolDraw2D.MolDraw2DSVG(240, 150)
    drawer.drawOptions().legendFontSize = 14
    rdMolDraw2D.PrepareAndDrawMolecule(drawer, molecule, legend=legend)
    drawer.FinishDrawing()
    return drawer.GetDrawingText().replace("<?xml version='1.0' encoding='iso-8859-1'?>", "")


def write_cards(cards: list[dict[str, Any]], output_dir: Path) -> tuple[Path, Path]:
    cards = [_clean(card) for card in cards]
    jsonl = output_dir / "mmp_reference_cards.jsonl"
    jsonl.write_text("".join(json.dumps(card, ensure_ascii=False, allow_nan=False) + "\n" for card in cards), encoding="utf-8")
    csv = output_dir / "mmp_reference_cards.csv"
    flattened = []
    for card in cards:
        flattened.append({
            "card_id": card["card_id"], "category": card["category"], "scope": card["scope"],
            "headline": card["headline"], "transform_id": card.get("transform_id"), "core_id": card.get("core_id"),
            "support_json": json.dumps(card.get("support", {}), ensure_ascii=False),
            "effect_json": json.dumps(card.get("effect", {}), ensure_ascii=False),
            "source_rows_json": json.dumps(card.get("source_rows", []), ensure_ascii=False),
            "quality_flags_json": json.dumps(card.get("quality_flags", []), ensure_ascii=False),
        })
    pd.DataFrame(flattened).to_csv(csv, index=False)
    return jsonl, csv


def render_report(
    *,
    role: str,
    scope_label: str,
    endpoint: str,
    higher_is_better: bool,
    core_policy: dict[str, Any],
    counts: dict[str, Any],
    cards: list[dict[str, Any]],
    tables: list[tuple[str, pd.DataFrame]],
    artifact_names: list[str],
    limitations: list[str],
) -> str:
    palette = {"portable_transform": "#315b59", "core_dependent": "#8a5b3d", "pair_cliff": "#7a4651", "flat_transform": "#4d6174", "coverage": "#6b6b66"}
    cards_html: dict[str, list[str]] = {}
    for card in cards[:30]:
        color = palette.get(card["category"], "#59636a")
        structures = card.get("structure") or {}
        visual_parts = []
        for key, legend in (("exact_core_smiles", "Exact Core"), ("variable_from", "Before"), ("variable_to", "After"), ("smiles_from", "Compound 1"), ("smiles_to", "Compound 2")):
            if structures.get(key) and len(visual_parts) < 3:
                visual_parts.append(_molecule_svg(structures[key], legend))
        visual = f'<div class="structures">{"".join(visual_parts)}</div>' if visual_parts else ""
        cards_html.setdefault(card["category"], []).append(
            f'<article class="card" style="border-left-color:{color}"><div class="tag">{html.escape(card["category"])}</div>'
            f'<h3>{html.escape(card["headline"])}</h3><code>{html.escape(card["card_id"])}</code>'
            f'{visual}<p>Support: {html.escape(json.dumps(card.get("support", {}), ensure_ascii=False))}</p>'
            f'<p>Effect: {html.escape(json.dumps(card.get("effect", {}), ensure_ascii=False))}</p></article>'
        )
    category_sections = [
        ("portable_transform", "複数Coreで再現する置換効果", "異なるExact Coreでも方向が揃う候補です。Pair数と独立Core数を併記します。"),
        ("core_dependent", "Exact Core依存性と符号反転", "同じTransformでもExact Coreにより効果が変わる候補です。"),
        ("context_dependent", "Environment依存性", "結合点周辺の環境により傾向が変わる候補です。radiusは独立Pairとして数えません。"),
        ("cluster_dependent", "Global対Cluster-local", "Globalと対象ClusterでTransform効果が変わる候補です。"),
        ("pair_cliff", "大きな個別Pair変化", "Pair固有の大きなEndpoint差です。単独Pairを一般化しません。"),
        ("core_hotspot", "SAR hotspot Core", "多くのMMPとEndpoint変動が集中するExact Core候補です。"),
        ("flat_transform", "平坦・許容されるTransform", "観測範囲でEndpoint差が小さいTransform候補です。"),
        ("contradiction", "反証・矛盾", "同じTransformで方向が揃わないなど、仮説への反証候補です。"),
        ("coverage", "CoverageとNegative Result", "該当MMPがない場合を含む、解析可能範囲と不足情報です。"),
    ]
    category_html = []
    for category, title, description in category_sections:
        items = cards_html.get(category, [])
        content = f'<div class="cards">{"".join(items)}</div>' if items else '<p class="empty">この条件で該当候補はありません。</p>'
        category_html.append(f'<section><h2>{html.escape(title)}</h2><p>{html.escape(description)}</p>{content}</section>')
    table_html = []
    for title, frame in tables:
        display = frame.head(20).copy()
        table_html.append(f"<section><h2>{html.escape(title)}</h2><p>全{len(frame):,}行。先頭20行を表示。</p>{display.to_html(index=False, escape=True, border=0)}</section>")
    links = "".join(f'<li><a href="{html.escape(name)}">{html.escape(name)}</a></li>' for name in artifact_names)
    limitations_html = "".join(f"<li>{html.escape(item)}</li>" for item in limitations) or "<li>追加の制約事項なし</li>"
    core_policy_text = (
        f"heavy atoms ≥ {core_policy.get('min_heavy_atoms', '—')}; "
        f"Extended ≥ {core_policy.get('extended_fraction', '—')}; "
        f"Primary ≥ {core_policy.get('primary_fraction', '—')}"
    )
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><title>MMP解析レポート</title>
<style>
:root{{--ink:#26343c;--muted:#68747a;--paper:#f5f1e9;--panel:#fffdfa;--line:#c8c4bb;--accent:#315b59}}
body{{margin:0;background:var(--paper);color:var(--ink);font-family:"Yu Gothic",Meiryo,sans-serif;line-height:1.65}}
main{{max-width:1180px;margin:auto;padding:42px}} h1{{font-size:2rem;margin-bottom:.25rem}} h2{{border-bottom:2px solid var(--accent);padding-bottom:.35rem;margin-top:2.3rem}}
.lead{{color:var(--muted)}} .facts{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:24px 0}}
.fact,.card,section{{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:16px}} .fact strong{{display:block;font-size:1.35rem}} .empty{{color:var(--muted);font-style:italic}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}} .card{{border-left:7px solid}} .tag{{font-size:.8rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}}
.structures{{display:flex;gap:4px;overflow:auto;background:#f7f4ed;margin:10px 0}} .structures svg{{min-width:180px;height:130px}}
table{{border-collapse:collapse;width:100%;font-size:.82rem;display:block;overflow:auto}} th,td{{border-bottom:1px solid #ddd8cf;padding:7px 9px;text-align:left;white-space:nowrap}} th{{background:#e7e8e3;position:sticky;top:0}}
a{{color:#315b59}} code{{font-size:.8rem}}
</style></head><body><main><header><h1>Matched Molecular Pair解析</h1><p class="lead">作業記録ではなく、Exact CoreとContextを保持した解析結果の人間向け要約です。</p></header>
<section><h2>解析対象</h2><div class="facts"><div class="fact">Role<strong>{html.escape(role)}</strong></div><div class="fact">対象<strong>{html.escape(scope_label)}</strong></div><div class="fact">Endpoint<strong>{html.escape(endpoint)}</strong></div><div class="fact">良好方向<strong>{'高値' if higher_is_better else '低値'}</strong></div><div class="fact">Core条件<strong>{html.escape(core_policy_text)}</strong></div><div class="fact">Engine<strong>mmpdb 3.1.4</strong></div>{''.join(f'<div class="fact">{html.escape(str(k))}<strong>{html.escape(str(v))}</strong></div>' for k,v in counts.items())}</div><p>候補は決定論的な抽出結果であり、最終的な科学的結論ではありません。</p></section>
{''.join(category_html)}
{''.join(table_html)}
<section><h2>制約と反証確認</h2><ul>{limitations_html}</ul></section>
<section><h2>成果物</h2><ul>{links}</ul></section>
</main></body></html>"""


def database_hash(path: Path) -> str:
    return sha256_file(path)
