from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd


GUIDANCE = {
    "group_profile": (
        "Groupごとの活性中心、ばらつき、高活性・低活性比率を比較する。",
        "Groupサイズと全体に占める割合を確認し、小さいGroupの極端値を過度に一般化しない。",
    ),
    "activity_distribution": (
        "endpointの中心、範囲、四分位範囲をscope間で比較する。",
        "分布差はassay条件、欠測、外れ値の影響を受けるため、化学的機序を直接意味しない。",
    ),
    "pairwise_structure_similarity": (
        "対象scopeの構造類似度分布と、近縁・遠縁ペアの活性差を確認する。",
        "Morgan/Tanimoto空間に限定した関係であり、別表現での再確認が必要である。",
    ),
    "descriptor_activity_correlation": (
        "個別Description featureとendpointの単変量関係を順位付けする。",
        "相関は因果ではなく、feature間共線性と多重探索を考慮する。",
    ),
    "knn_activity_consistency": (
        "選択したDescription空間で近傍化合物の活性がどの程度整合するかを調べる。",
        "結果はDescriptionとmetricに依存し、局所例外も同時に確認する。",
    ),
    "sali": (
        "SALIの中心とupper tailからlandscapeの平滑性と局所Cliffを同時に評価する。",
        "raw SALIはendpoint scaleとmetricに依存する。高SALI pairはassay誤差と化学的差分を確認する。",
    ),
    "activity_cliff": (
        "構造類似度が高い一方でendpoint差が大きいペアを確認する。",
        "Cliffは閾値とMorgan表現に依存し、測定条件や立体・3D差を別途確認する。",
    ),
    "group_enrichment": (
        "各Groupに高活性化合物が濃縮されるかをeffect sizeと検定値から確認する。",
        "小Group、多重比較、全体と重なる大Groupでは見かけの濃縮に注意する。",
    ),
    "group_overlap": (
        "異なるGrouping由来Groupの重複をJaccardと交差数で比較する。",
        "重複はGroupの独立性を示す情報であり、活性差や機序を単独では説明しない。",
    ),
    "group_structural_diversity": (
        "Group内部のMorgan/Tanimoto類似度から構造的な凝集度と多様性を確認する。",
        "構造凝集度はGroupingの有用性の一面であり、活性の均一性とは別に評価する。",
    ),
}

METRICS = {
    "group_profile": ["property_median", "high_activity_fraction", "property_iqr"],
    "activity_distribution": ["median", "std"],
    "pairwise_structure_similarity": ["similarity", "abs_delta_property"],
    "descriptor_activity_correlation": ["max_abs_association", "spearman_rho"],
    "knn_activity_consistency": ["abs_delta_property", "distance"],
    "sali": ["sali", "abs_delta_property"],
    "activity_cliff": ["cliff_score", "abs_delta_property"],
    "group_enrichment": ["odds_ratio", "median_shift_vs_global"],
    "group_overlap": ["jaccard", "intersection_count"],
    "group_structural_diversity": ["structural_diversity_score", "mean_tanimoto"],
}

RANKING = {
    "group_profile": ("high_activity_fraction", False),
    "pairwise_structure_similarity": ("similarity", False),
    "descriptor_activity_correlation": ("max_abs_association", False),
    "knn_activity_consistency": ("abs_delta_property", False),
    "sali": ("sali", False),
    "activity_cliff": ("cliff_score", False),
    "group_enrichment": ("fisher_pvalue", True),
    "group_overlap": ("jaccard", False),
    "group_structural_diversity": ("structural_diversity_score", False),
}


def serializable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serializable(item) for item in value]
    if hasattr(value, "item"):
        try:
            return serializable(value.item())
        except (TypeError, ValueError):
            pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def display(value: Any) -> str:
    value = serializable(value)
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        if value == 0:
            return "0"
        if abs(value) < 0.001 or abs(value) >= 10000:
            return f"{value:.3e}"
        return f"{value:.4g}"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    text = str(value)
    return text if len(text) <= 140 else text[:137] + "…"


def file_link(path_text: Any, label: str | None = None) -> str:
    if not path_text:
        return "-"
    path = Path(str(path_text))
    try:
        href = path.resolve().as_uri()
    except ValueError:
        return html.escape(str(path))
    return f"<a href='{html.escape(href, quote=True)}'>{html.escape(label or str(path))}</a>"


def ranked_rows(result: pd.DataFrame, operator: str) -> pd.DataFrame:
    column, ascending = RANKING.get(operator, ("", True))
    if column and column in result.columns:
        return result.sort_values(column, ascending=ascending, na_position="last")
    return result


def result_table(result: pd.DataFrame, operator: str, limit: int = 100) -> str:
    if result.empty:
        return "<p class='empty'>該当する結果行はありません。</p>"
    frame = ranked_rows(result, operator).head(limit)
    headers = "".join(f"<th>{html.escape(str(column))}</th>" for column in frame.columns)
    rows = []
    for row in frame.itertuples(index=False, name=None):
        rows.append("<tr>" + "".join(f"<td>{html.escape(display(value))}</td>" for value in row) + "</tr>")
    return f"<div class='table-wrap'><table><thead><tr>{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


def histogram_svg(series: pd.Series, label: str) -> str:
    values = []
    for value in pd.to_numeric(series, errors="coerce").dropna().tolist():
        number = float(value)
        if math.isfinite(number):
            values.append(number)
    if len(values) < 2:
        return ""
    low, high = min(values), max(values)
    bins = min(12, max(4, int(math.sqrt(len(values)))))
    counts = [0] * bins
    if low == high:
        counts[0] = len(values)
    else:
        for value in values:
            index = min(bins - 1, int((value - low) / (high - low) * bins))
            counts[index] += 1
    width, height = 520, 190
    plot_left, plot_top, plot_width, plot_height = 48, 30, 440, 112
    maximum = max(counts) or 1
    bar_width = plot_width / bins
    bars = []
    for index, count in enumerate(counts):
        bar_height = plot_height * count / maximum
        x = plot_left + index * bar_width + 2
        y = plot_top + plot_height - bar_height
        bars.append(f"<rect x='{x:.1f}' y='{y:.1f}' width='{max(1, bar_width - 4):.1f}' height='{bar_height:.1f}' rx='2'><title>N={count}</title></rect>")
    return f"""<figure><figcaption>{html.escape(label)} distribution · N={len(values)}</figcaption><svg role='img' aria-label='{html.escape(label)} distribution' viewBox='0 0 {width} {height}'><line x1='{plot_left}' y1='{plot_top + plot_height}' x2='{plot_left + plot_width}' y2='{plot_top + plot_height}'/><g>{''.join(bars)}</g><text x='{plot_left}' y='170'>{html.escape(display(low))}</text><text text-anchor='end' x='{plot_left + plot_width}' y='170'>{html.escape(display(high))}</text></svg></figure>"""


def summary_cards(summary: dict[str, Any]) -> tuple[str, str]:
    scalars = [(key, value) for key, value in summary.items() if not isinstance(value, (dict, list, tuple))]
    cards = "".join(
        f"<div class='metric'><span>{html.escape(str(key))}</span><strong>{html.escape(display(value))}</strong></div>"
        for key, value in scalars[:12]
    ) or "<p class='empty'>要約指標はありません。</p>"
    nested = {key: serializable(value) for key, value in summary.items() if isinstance(value, (dict, list, tuple))}
    detail = ""
    if nested:
        detail = f"<details><summary>構造化された追加要約</summary><pre>{html.escape(json.dumps(nested, ensure_ascii=False, indent=2))}</pre></details>"
    return cards, detail


def render_operator_report(
    capability: dict[str, Any],
    args: Any,
    result: pd.DataFrame,
    summary: dict[str, Any],
    evidence: dict[str, Any],
    manifest: dict[str, Any],
    result_path: Path,
) -> str:
    operator = str(capability["implementation"]["operator"])
    purpose, caution = GUIDANCE.get(operator, ("解析結果を確認する。", "単独解析から機序や因果を断定しない。"))
    scope = evidence.get("scope") or {}
    direction = "高い値が良好" if getattr(args, "higher_is_better", None) else "低い値が良好"
    description_context = evidence.get("evaluation_representation") or ("未指定（artifactあり）" if getattr(args, "description", None) else "未使用")
    grouping_context = evidence.get("grouping_representation") or ("未指定（artifactあり）" if getattr(args, "membership", None) else "未使用")
    description_node = getattr(args, "description_node_id", None) or "未記録"
    grouping_node = getattr(args, "grouping_node_id", None) or "未記録"
    target = evidence.get("target_group_id") or "GLOBAL"
    comparison = scope.get("comparison_group_id") or "-"
    contexts = [
        ("Operator", f"{capability['operator_id']} · {capability['display_name']}"),
        ("Execution Node", getattr(args, "node_id", None) or "-"),
        ("Endpoint", f"{getattr(args, 'property_column', '-')}（{direction}）"),
        ("Scope", f"{scope.get('mode', 'global')} · N={scope.get('sample_count', evidence.get('sample_count', 0))}"),
        ("Description source", f"{description_context} · Node {description_node}" if getattr(args, "description", None) else str(description_context)),
        ("Grouping source", f"{grouping_context} · Node {grouping_node}" if getattr(args, "membership", None) else str(grouping_context)),
        ("Target / comparison", f"{target} / {comparison}"),
        ("Description artifact", str(getattr(args, "description", None) or "-")),
        ("Grouping artifact", str(getattr(args, "membership", None) or "-")),
    ]
    context_html = "".join(f"<dt>{html.escape(label)}</dt><dd>{html.escape(value)}</dd>" for label, value in contexts)
    cards, nested = summary_cards(summary)
    chart_html = "".join(histogram_svg(result[column], column) for column in METRICS.get(operator, []) if column in result.columns)
    chart_html = chart_html or "<p class='empty'>この結果形式に対する分布図はありません。表と要約値を確認してください。</p>"
    warning_items = list(evidence.get("warnings") or [])
    warning_html = "".join(f"<li>{html.escape(str(item))}</li>" for item in warning_items) or "<li>実行時警告はありません。</li>"
    parameter_rows = "".join(
        f"<tr><th>{html.escape(str(key))}</th><td>{html.escape(display(value))}</td></tr>"
        for key, value in sorted((manifest.get("configuration") or vars(args)).items())
        if key not in {"overwrite"}
    )
    css = """:root{--ink:#293840;--navy:#304957;--muted:#6c777d;--paper:#f2f0eb;--surface:#fff;--line:#d9d5cc;--teal:#5f7d73;--teal-soft:#e6eeea;--blue:#668196;--blue-soft:#e7edf0;--ochre:#8d7446;--ochre-soft:#f1ecdf;--brick:#95645c;--brick-soft:#f1e6e3}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:14px/1.68 "Yu Gothic UI","Segoe UI",sans-serif}main{max-width:1180px;margin:26px auto;padding:42px 50px 62px;background:var(--surface);box-shadow:0 12px 34px #26364018}h1,h2{color:var(--navy)}h1{font-size:31px;margin:3px 0 6px}h2{margin-top:42px;padding-bottom:7px;border-bottom:2px solid var(--navy)}.meta,.empty{color:var(--muted)}.context{display:grid;grid-template-columns:190px 1fr;margin:22px 0;border:1px solid var(--line)}dt,dd{margin:0;padding:8px 12px;border-bottom:1px solid var(--line)}dt{font-weight:700;background:#f2f3f0;color:var(--navy)}.guidance{display:grid;grid-template-columns:1fr 1fr;gap:16px}.guidance>div{padding:16px 19px;border-left:5px solid var(--teal);background:var(--teal-soft)}.guidance .caution{border-color:var(--ochre);background:var(--ochre-soft)}.metrics{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:11px}.metric{padding:12px 14px;border:1px solid var(--line);background:#f7f7f4}.metric span{display:block;color:var(--muted);font-size:11px;word-break:break-word}.metric strong{display:block;color:var(--navy);font-size:18px;word-break:break-word}figure{display:inline-block;width:49%;min-width:420px;margin:8px 0;padding:12px;border:1px solid var(--line)}figcaption{font-weight:700;color:var(--navy)}figure svg{width:100%;height:auto}figure rect{fill:var(--blue)}figure line{stroke:#869198}figure text{font:11px "Segoe UI",sans-serif;fill:var(--muted)}table{border-collapse:collapse;width:100%;font-size:12px}th,td{border:1px solid var(--line);padding:7px;text-align:left;vertical-align:top}thead th{background:#eceeec;position:sticky;top:0}.table-wrap{max-height:620px;overflow:auto;border:1px solid var(--line)}.table-wrap table{border:0}.warning{padding:13px 18px;border-left:5px solid var(--brick);background:var(--brick-soft)}details{margin-top:18px}summary{cursor:pointer;color:var(--navy);font-weight:700}pre{white-space:pre-wrap;word-break:break-word;background:#f5f5f2;padding:14px;max-height:460px;overflow:auto}a{color:#405f73}.trace{font-size:12px;color:var(--muted);word-break:break-all}@media(max-width:800px){main{margin:0;padding:26px 18px}.metrics{grid-template-columns:repeat(2,1fr)}.guidance{grid-template-columns:1fr}.context{grid-template-columns:1fr}figure{width:100%;min-width:0}}@media print{body{background:#fff}main{margin:0;box-shadow:none;max-width:none}.table-wrap{max-height:none;overflow:visible}}"""
    return f"""<!doctype html><html lang='ja'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{html.escape(capability['display_name'])} · CONDUCTOR Operator Report</title><style>{css}</style></head><body><main><header><p class='meta'>CONDUCTOR Operator evidence report</p><h1>{html.escape(capability['display_name'])}</h1><p class='meta'>Run {html.escape(str(evidence.get('run_id') or '-'))} · Node {html.escape(str(getattr(args, 'node_id', None) or '-'))} · {html.escape(str(evidence.get('created_at') or '-'))}</p></header><h2>解析対象と由来</h2><dl class='context'>{context_html}</dl><div class='guidance'><div><b>この解析で確認すること</b><br>{html.escape(purpose)}</div><div class='caution'><b>解釈上の注意</b><br>{html.escape(caution)}</div></div><h2>主要結果</h2><p>{html.escape(str(evidence.get('human_readable_summary') or ''))}</p><div class='metrics'>{cards}</div>{nested}<h2>結果分布</h2>{chart_html}<h2>個別結果</h2><p>解釈上確認しやすい順に最大100行を表示しています。完全な結果は<a href='{html.escape(result_path.name)}'>{html.escape(result_path.name)}</a>を参照してください。</p>{result_table(result, operator)}<h2>警告・制約</h2><div class='warning'><ul>{warning_html}</ul><p>{html.escape(caution)}</p></div><details><summary>実行parameterとprovenance</summary><table><tbody>{parameter_rows}</tbody></table><p class='trace'>Evidence ID: {html.escape(str(evidence.get('evidence_id') or '-'))}<br>Input: {file_link(manifest.get('input'))}<br>Input hash: {html.escape(str(manifest.get('input_hash') or '-'))}</p></details></main></body></html>"""
