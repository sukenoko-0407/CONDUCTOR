from __future__ import annotations

import html
import json
import math
from typing import Any


def display(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return "—"
        return f"{value:.4g}"
    return str(value)


def markdown_table(rows: list[dict[str, Any]], columns: list[str]) -> list[str]:
    if not rows:
        return ["該当候補はありません。"]
    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join("---" for _ in columns) + "|"]
    for row in rows:
        values = [display(row.get(column)).replace("|", "\\|").replace("\n", " ") for column in columns]
        lines.append("| " + " | ".join(values) + " |")
    return lines


def html_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    if not rows:
        return '<p class="empty">該当候補はありません。</p>'
    head = "".join(f"<th>{html.escape(column)}</th>" for column in columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(display(row.get(column)))}</td>" for column in columns) + "</tr>"
        for row in rows
    )
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


TABLE_VIEWS = [
    (
        "Transform効果の分散縮小候補",
        "variance_collapse",
        ["clustering_node_id", "clustering_capability_id", "transform_id", "eligible_cluster_count", "global_iqr", "weighted_local_iqr", "dispersion_reduction", "pair_coverage"],
    ),
    (
        "Cluster固有Transform候補",
        "cluster_specific",
        ["clustering_node_id", "cluster_id", "transform_id", "local_endpoint_pair_count", "outside_endpoint_pair_count", "local_median", "outside_median", "local_minus_outside", "local_iqr", "shared_core_count"],
    ),
    (
        "効果方向の反転候補",
        "direction_reversal",
        ["clustering_node_id", "cluster_id", "transform_id", "local_endpoint_pair_count", "outside_endpoint_pair_count", "local_median", "outside_median", "local_minus_outside", "shared_core_count"],
    ),
    (
        "Clustering別MMP coverage",
        "clustering_overview",
        ["clustering_node_id", "clustering_capability_id", "cluster_count", "overlap_detected", "clusters_with_mmp", "eligible_transform_comparisons"],
    ),
]


def render_markdown(report: dict[str, Any]) -> str:
    source = report["source"]
    summary = report["summary"]
    draft = report["draft"]
    lines = [
        f"# {draft['title']}", "",
        f"- Run / target Round: `{source['run_id']}` / `{source['round_id']}`",
        f"- Global A014 Node: `{source['mmp_node_id']}`",
        f"- Endpoint: `{source['endpoint']}` (`higher_is_better={str(source['higher_is_better']).lower()}`)",
        f"- Clustering Node / Cluster: {summary['clustering_node_count']} / {summary['cluster_count']}",
        f"- Global MMP / Transform: {summary['global_mmp_count']} / {summary['global_transform_count']}",
        "- このレポートはread-only補助成果物であり、DAG、State、正式Insightを変更しない。", "",
        "## エグゼクティブサマリー", "", draft["executive_summary"], "",
        "## 評価方法", "",
        "- Local: MMP pairの両化合物が対象Clusterに所属する。",
        "- Outside: MMP pairの両化合物が対象Clusterに所属しない。境界pairは別集計する。",
        "- 効果量には`favorable_delta`を使い、正値を常に良好方向とする。",
        "- 分散縮小はGlobal IQRと、同一Clustering内のeligible Clusterをpair数で重み付けしたLocal IQRを比較する。",
        "- 重複Clusterは独立な分散分解として扱わず、探索的なCluster固有比較だけに使う。", "",
        "## 解釈", "",
    ]
    if not draft["observations"]:
        lines.extend(["今回の条件では、記載基準を満たすGlobal–Local MMP候補は得られませんでした。", ""])
    for index, item in enumerate(draft["observations"], 1):
        lines.extend([
            f"### MMP View {index:02d} — {item['title']}", "",
            f"- 種別: `{item['category']}`",
            f"- Evidence: {', '.join(item.get('evidence') or []) or '—'}", "",
            "**観察**", "", item["observation"], "",
            "**解釈**", "", item["interpretation"], "",
            "**限界**", "",
        ])
        lines.extend(f"- {value}" for value in item["limitations"])
        lines.append("")
    lines.extend(["## 候補Table", ""])
    for title, key, columns in TABLE_VIEWS:
        lines.extend([f"### {title}", "", f"完全な表: [`{report['artifacts'][key]}`]({report['artifacts'][key]})", ""])
        lines.extend(markdown_table(report["previews"].get(key, []), columns))
        lines.append("")
    lines.extend(["## 人間が次に指定できる視点", ""])
    lines.extend(f"- **{item['title']}**  \n  `{item['prompt']}`" for item in draft["human_guidance"])
    lines.extend(["", "## 共通の限界", ""])
    lines.extend([
        "- 小標本のClusterではIQR、MAD、中央値差が不安定になる。",
        "- LocalとOutsideでExact Core構成が異なる場合、Cluster差はCore／Environment差を反映する可能性がある。",
        "- 複数Clusteringまたは重複Clusterで同じMMP pairが反復して現れても、独立な再現とはみなさない。",
        "- 記述統計による候補抽出であり、因果関係や統計的有意性を確定しない。",
    ])
    return "\n".join(lines) + "\n"


def render_html(report: dict[str, Any]) -> str:
    source = report["source"]
    summary = report["summary"]
    draft = report["draft"]
    observations = []
    for index, item in enumerate(draft["observations"], 1):
        evidence = ", ".join(item.get("evidence") or []) or "—"
        limitations = "".join(f"<li>{html.escape(value)}</li>" for value in item["limitations"])
        observations.append(
            f'<article class="observation"><div class="eyebrow">MMP VIEW {index:02d} · {html.escape(item["category"])}</div>'
            f'<h3>{html.escape(item["title"])}</h3><p class="evidence">Evidence: {html.escape(evidence)}</p>'
            f'<h4>観察</h4><p>{html.escape(item["observation"])}</p>'
            f'<h4>解釈</h4><p>{html.escape(item["interpretation"])}</p>'
            f'<h4>限界</h4><ul>{limitations}</ul></article>'
        )
    if not observations:
        observations.append('<p class="empty">今回の条件では、記載基準を満たすGlobal–Local MMP候補は得られませんでした。</p>')
    tables = []
    for title, key, columns in TABLE_VIEWS:
        tables.append(
            f'<section><div class="section-heading"><h2>{html.escape(title)}</h2>'
            f'<a href="{html.escape(report["artifacts"][key])}">完全なCSV</a></div>'
            f'{html_table(report["previews"].get(key, []), columns)}</section>'
        )
    guidance = "".join(
        f'<article class="prompt"><h3>{html.escape(item["title"])}</h3><code>{html.escape(item["prompt"])}</code></article>'
        for item in draft["human_guidance"]
    )
    css = """
:root{--ink:#21313a;--muted:#64747c;--paper:#f6f3ec;--panel:#fffdf8;--line:#d4d1c8;--accent:#9a5738;--blue:#526d78;--green:#657868}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:"Noto Sans JP","Yu Gothic",sans-serif;line-height:1.72}
main{max-width:1200px;margin:auto;padding:48px 34px 80px}header{border-top:7px solid var(--ink);border-bottom:1px solid var(--line);padding:26px 0 28px}.eyebrow{font-size:.78rem;letter-spacing:.14em;color:var(--accent);font-weight:700;text-transform:uppercase}
h1{font-family:Georgia,"Yu Mincho",serif;font-size:2.25rem;line-height:1.25;margin:.4rem 0}.meta{color:var(--muted)}h2{font-family:Georgia,"Yu Mincho",serif;margin:2.5rem 0 1rem}h3{margin:.35rem 0 1rem}h4{margin:1.1rem 0 .25rem;color:var(--blue)}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:24px 0}.metric,.observation,.prompt{background:var(--panel);border:1px solid var(--line);padding:18px}.metric b{display:block;font-size:1.65rem}.metric span{color:var(--muted);font-size:.86rem}
.summary{background:#ece8df;border-left:6px solid var(--accent);padding:22px 26px;margin:26px 0}.observation{margin:16px 0;border-left:5px solid var(--blue)}.evidence{font-family:monospace;color:var(--muted);font-size:.85rem}.section-heading{display:flex;align-items:baseline;justify-content:space-between;gap:20px}.section-heading a{color:var(--accent)}
.table-wrap{overflow:auto;border:1px solid var(--line);background:var(--panel)}table{border-collapse:collapse;width:100%;font-size:.86rem}th,td{padding:9px 11px;border-bottom:1px solid #e5e1d8;text-align:left;white-space:nowrap}th{position:sticky;top:0;background:#e7e3da;color:#334750}.prompts{display:grid;gap:12px}.prompt code{display:block;white-space:pre-wrap;color:#344d58}.empty{color:var(--muted);font-style:italic}
@media(max-width:700px){main{padding:26px 16px}h1{font-size:1.7rem}.section-heading{display:block}}
"""
    metrics = [
        (summary["clustering_node_count"], "Clustering Nodes"),
        (summary["cluster_count"], "Clusters"),
        (summary["global_mmp_count"], "Global MMPs"),
        (summary["global_transform_count"], "Transforms"),
        (summary["variance_candidate_count"], "Variance candidates"),
        (summary["cluster_specific_candidate_count"], "Cluster-specific candidates"),
    ]
    metric_html = "".join(f'<div class="metric"><b>{display(value)}</b><span>{html.escape(label)}</span></div>' for value, label in metrics)
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(draft['title'])}</title><style>{css}</style></head><body><main>
<header><div class="eyebrow">READ-ONLY MMP GLOBAL–LOCAL INTERPRETATION</div><h1>{html.escape(draft['title'])}</h1><p class="meta">Run {html.escape(source['run_id'])} · Round {html.escape(source['round_id'])} · Global A014 {html.escape(source['mmp_node_id'])}<br>Endpoint {html.escape(source['endpoint'])} · higher_is_better={str(source['higher_is_better']).lower()}</p></header>
<div class="metrics">{metric_html}</div><section class="summary"><h2>エグゼクティブサマリー</h2><p>{html.escape(draft['executive_summary'])}</p></section>
<section><h2>評価方法</h2><p>Localは両化合物が対象Cluster内、Outsideは両化合物が対象Cluster外のMMPです。境界pairは分離しました。効果量は良好方向を正に統一した favorable_delta です。分散縮小はGlobal IQRとpair数加重Local IQRを比較し、重複Clusterでは探索的所見として扱います。</p></section>
<section><h2>解釈</h2>{''.join(observations)}</section>{''.join(tables)}
<section><h2>人間が次に指定できる視点</h2><div class="prompts">{guidance}</div></section>
<section><h2>共通の限界</h2><ul><li>小標本では中央値差と分散が不安定です。</li><li>Exact Core／Environment構成差がCluster差を説明する可能性があります。</li><li>重複Clusterと複数Clusteringで反復するpairは独立な再現ではありません。</li><li>本レポートは記述的候補抽出であり、因果関係や統計的有意性を確定しません。</li></ul></section>
</main></body></html>"""


def clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(item) for item in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def report_json(report: dict[str, Any]) -> str:
    return json.dumps(clean_json(report), ensure_ascii=False, indent=2) + "\n"
