from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


ATTENTION_JA = {"priority": "優先", "watch": "注視", "background": "背景情報"}
STATUS_JA = {"open": "未対応", "closed": "対応終了"}
ATTENTION_ORDER = {"priority": 0, "watch": 1, "background": 2}


def _refs(values: list[str]) -> str:
    return "、".join(f"`{value}`" for value in values) if values else "なし"


def _ordered(report: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(report["insights"], key=lambda item: (ATTENTION_ORDER.get(item["attention"], 9), item["insight_id"]))


def _clusters(item: dict[str, Any]) -> list[str]:
    scope = item.get("scope") or {}
    values = list(scope.get("cluster_ids") or [])
    if scope.get("target_cluster_id"): values.append(scope["target_cluster_id"])
    return list(dict.fromkeys(str(value) for value in values if value))


def _artifact_link(value: Any, label: str) -> str:
    if not value:return "-"
    path=Path(str(value))
    try:href=path.resolve().as_uri()
    except ValueError:return f"<code>{html.escape(str(value))}</code>"
    return f"<a href='{html.escape(href)}'>{html.escape(label)}</a>"


def render_markdown(report: dict[str, Any]) -> str:
    lines = [f"# {report['title']}", "", "## エグゼクティブサマリー", "", report["executive_summary"], "", "## 今回の解析範囲", "", report["coverage_note"], "", "## 注目すべき解釈", ""]
    if not report["insights"]:
        lines.extend(["今回の解析結果から、報告基準を満たすInsightは抽出されませんでした。これは解析失敗ではなく、保持すべき明確な変化・矛盾・例外が見つからなかったというnegative resultです。", ""])
    for item in _ordered(report):
        cluster_text="、".join(_clusters(item)) or "Global／Cluster未指定"
        lines += [f"### {item['insight_id']} — {item['title']}", "", f"- 注目度: {ATTENTION_JA[item['attention']]}", f"- 対象: {cluster_text}", f"- 支持結果: {_refs(item['supporting_results'])}", f"- 反証・不一致結果: {_refs(item['counter_results'])}", "", "**観察**", "", item["observation"], "", "**解釈**", "", item["interpretation"], ""]
    lines += ["## 矛盾・反証・限界", ""]
    if not report["insights"]:lines += ["保持したInsightがないため、個別の矛盾・限界はありません。解析coverageは上記を参照してください。", ""]
    for item in _ordered(report):lines += [f"- **{item['insight_id']}** — 反証・不一致: {_refs(item['counter_results'])}／限界: {'；'.join(item['limitations'])}"]
    lines += ["", "## Cluster別の見取り図", ""]
    local=[item for item in _ordered(report) if _clusters(item)]
    if not local:lines += ["Clusterを明示したInsightはありません。", ""]
    for item in local:lines += [f"- {', '.join(_clusters(item))}: **{item['insight_id']}** {item['title']}"]
    lines += [""]
    lines += ["## 次の解析候補", ""]
    if not report["next_actions"]: lines += ["現時点で提案するNext Actionはありません。", ""]
    for action in report["next_actions"]:
        lines += [f"### {action['action_id']} — {action['title']}", "", f"- 状態: {STATUS_JA[action['status']]}", f"- 関連Insight: {_refs(action['source_insights'])}", "", action["rationale"], ""]
    roles={}
    for item in report["insights"]:
        for ref in item["supporting_results"]:roles.setdefault(ref,set()).add(f"{item['insight_id']}の支持")
        for ref in item["counter_results"]:roles.setdefault(ref,set()).add(f"{item['insight_id']}の反証・不一致")
    lines += ["## Operator結果・Methods appendix", ""]
    catalog={item["result_ref"]:item for item in report.get("result_catalog",[])}
    for ref,values in sorted(roles.items()):
        item=catalog.get(ref,{}) ; scope=(item.get("scope") or {}).get("mode") or "-" ; lines += [f"### `{ref}`", "", f"- 役割: {'、'.join(sorted(values))}", f"- Operator / scope / N / metric: `{item.get('operator_id') or '-'}` / `{scope}` / `{item.get('sample_count') if item.get('sample_count') is not None else '-'}` / `{item.get('metric') or '-'}`", f"- 要約: {item.get('headline') or '-'}", f"- 数値artifact: `{item.get('artifact_path') or '-'}`", f"- 個別HTML: `{item.get('operator_report_path') or '-'}`", ""]
    lines += [f"- Run: `{report['run_id']}`", f"- Round: `{report['round_id']}`", f"- Interpretation Node: `{report['node_id']}@{report['attempt_id']}`", ""]
    return "\n".join(lines)


def render_html(report: dict[str, Any]) -> str:
    insight_cards=[]
    for item in _ordered(report):
        limits="".join(f"<li>{html.escape(value)}</li>" for value in item["limitations"]) or "<li>特記なし</li>"
        support=" ".join(f"<code>{html.escape(value)}</code>" for value in item["supporting_results"]) or "なし"
        counter=" ".join(f"<code>{html.escape(value)}</code>" for value in item["counter_results"]) or "なし"
        cluster_text="、".join(_clusters(item)) or "Global／Cluster未指定"
        insight_cards.append(f"<article class='insight {item['attention']}'><header><span>{html.escape(item['insight_id'])}</span><b>{html.escape(ATTENTION_JA[item['attention']])}</b></header><h3>{html.escape(item['title'])}</h3><p class='scope'>対象: {html.escape(cluster_text)}</p><h4>観察</h4><p>{html.escape(item['observation'])}</p><h4>解釈</h4><p>{html.escape(item['interpretation'])}</p><dl><dt>支持結果</dt><dd>{support}</dd><dt>反証・不一致</dt><dd>{counter}</dd></dl><details><summary>限界</summary><ul>{limits}</ul></details></article>")
    if not insight_cards: insight_cards=["<div class='empty'>報告基準を満たすInsightはありません。明確な変化・矛盾・例外が見つからなかったnegative resultとして保持します。</div>"]
    actions=[]
    for item in report["next_actions"]:
        refs=" ".join(f"<code>{html.escape(value)}</code>" for value in item["source_insights"]) or "なし"
        actions.append(f"<article class='action {item['status']}'><header><span>{html.escape(item['action_id'])}</span><b>{html.escape(STATUS_JA[item['status']])}</b></header><h3>{html.escape(item['title'])}</h3><p>{html.escape(item['rationale'])}</p><p>関連Insight: {refs}</p></article>")
    if not actions: actions=["<div class='empty'>現時点で提案するNext Actionはありません。</div>"]
    contradiction=[];local=[];roles={}
    for item in _ordered(report):
        contradiction.append(f"<li><b>{html.escape(item['insight_id'])}</b> — 反証・不一致: {html.escape(', '.join(item['counter_results']) or '明示的探索で未検出')}<br>限界: {html.escape('；'.join(item['limitations']))}</li>")
        if _clusters(item):local.append(f"<li><b>{html.escape('、'.join(_clusters(item)))}</b> — {html.escape(item['insight_id'])} {html.escape(item['title'])}</li>")
        for ref in item["supporting_results"]:roles.setdefault(ref,set()).add(f"{item['insight_id']}の支持")
        for ref in item["counter_results"]:roles.setdefault(ref,set()).add(f"{item['insight_id']}の反証・不一致")
    contradiction_html="<ul>"+"".join(contradiction)+"</ul>" if contradiction else "<div class='empty'>保持したInsightがないため、個別の矛盾・限界はありません。</div>"
    local_html="<ul>"+"".join(local)+"</ul>" if local else "<div class='empty'>Clusterを明示したInsightはありません。</div>"
    catalog={item["result_ref"]:item for item in report.get("result_catalog",[])}
    method_rows=[]
    for ref,values in sorted(roles.items()):
        item=catalog.get(ref,{}) ; scope=(item.get("scope") or {}).get("mode") or "-" ; context=item.get("scope_context") or {};clusters="、".join(context.get("cluster_ids") or []) or "-";descriptions="、".join(context.get("description_node_ids") or []) or "-"
        method_rows.append(f"<tr><th><code>{html.escape(ref)}</code><br>{html.escape('、'.join(sorted(values)))}</th><td><b>{html.escape(str(item.get('operator_id') or '-'))}</b> · scope {html.escape(str(scope))} · N={html.escape(str(item.get('sample_count') if item.get('sample_count') is not None else '-'))} · metric {html.escape(str(item.get('metric') or '-'))}<br>{html.escape(str(item.get('headline') or '-'))}<br>Description: {html.escape(descriptions)} · Cluster: {html.escape(clusters)}<br>{_artifact_link(item.get('artifact_path'),'数値artifact')} · {_artifact_link(item.get('operator_report_path'),'個別HTML report')} · {_artifact_link(item.get('summary_artifact_path'),'summary JSON')}</td></tr>")
    method_rows="".join(method_rows) or "<tr><td>参照Operator resultなし</td></tr>"
    css=":root{--ink:#273840;--navy:#304957;--paper:#eeece7;--line:#d8d4cc;--priority:#86584f;--watch:#887345;--background:#667a72}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.72 'Yu Gothic UI','Segoe UI',sans-serif}main{max-width:1120px;margin:28px auto;padding:48px 54px 64px;background:#fff;box-shadow:0 12px 34px #26364014}h1,h2{color:var(--navy)}h1{font-size:32px;margin:.2em 0}h2{margin-top:44px;border-bottom:2px solid var(--navy);padding-bottom:8px}.lead{font-size:17px;max-width:900px}.coverage,.empty{padding:18px 21px;background:#f5f4f0;border-left:5px solid #687f88}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.insight,.action{border:1px solid var(--line);border-top:5px solid var(--background);padding:18px 20px}.insight.priority{border-top-color:var(--priority)}.insight.watch{border-top-color:var(--watch)}article header{display:flex;justify-content:space-between;color:#667279}article h3{color:var(--navy);margin:.7em 0}article h4{margin:1em 0 .2em}dl{display:grid;grid-template-columns:130px 1fr}dt,dd{margin:0;padding:6px;border-top:1px solid var(--line)}code{background:#edf0ef;padding:2px 5px}table{width:100%;border-collapse:collapse}th,td{padding:10px;border:1px solid var(--line);text-align:left;vertical-align:top}th{width:28%;background:#f5f4f0}a{color:#405f73}footer{margin-top:48px;color:#737d81;font-size:12px}@media(max-width:800px){main{margin:0;padding:28px 18px}.grid{grid-template-columns:1fr}}"
    return f"<!doctype html><html lang='ja'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{html.escape(report['title'])}</title><style>{css}</style></head><body><main><p>CONDUCTOR Interpretation Report</p><h1>{html.escape(report['title'])}</h1><h2>エグゼクティブサマリー</h2><p class='lead'>{html.escape(report['executive_summary'])}</p><h2>今回の解析範囲</h2><div class='coverage'>{html.escape(report['coverage_note'])}</div><h2>主要Insight</h2><div class='grid'>{''.join(insight_cards)}</div><h2>矛盾・反証・限界</h2>{contradiction_html}<h2>Cluster別の見取り図</h2>{local_html}<h2>Next Action</h2><div class='grid'>{''.join(actions)}</div><h2>Operator結果・Methods appendix</h2><table>{method_rows}</table><footer>Run {html.escape(report['run_id'])} · Round {html.escape(report['round_id'])} · {html.escape(report['node_id'])}@{html.escape(report['attempt_id'])}</footer></main></body></html>"


def render_quality(report: dict[str, Any]) -> dict[str, Any]:
    issues=[]
    for item in report["insights"]:
        if not item["supporting_results"]: issues.append(f"{item['insight_id']}: supporting_results is empty")
        if not item["counter_results"] and not any(token in value.lower() for value in item["limitations"] for token in ("反証","不一致","counter")): issues.append(f"{item['insight_id']}: counter_results is empty; explicit unsuccessful counter-search must be described in limitations")
    catalog_refs={item["result_ref"] for item in report.get("result_catalog",[])};referenced={ref for item in report["insights"] for ref in [*item["supporting_results"],*item["counter_results"]]}
    if referenced-catalog_refs:issues.append(f"result_catalog is missing references: {sorted(referenced-catalog_refs)}")
    return {"schema_version":"1.0.0","status":"pass" if not issues else "warning","issue_count":len(issues),"issues":issues,"counts":{"insights":len(report["insights"]),"next_actions":len(report["next_actions"])}}
