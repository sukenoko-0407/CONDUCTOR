from __future__ import annotations

import html
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any


ATTENTION_JA = {"pinned": "人間固定", "active": "重点", "watch": "経過観察", "background": "背景"}
CLAIM_JA = {"single_scope_observation": "単一範囲の観察", "difference": "差異", "agreement": "一致", "contradiction": "矛盾", "negative_result": "明確な傾向なし", "coverage_gap": "未確認領域"}
SCOPE_JA = {"global": "Global", "single_cluster": "Cluster-local", "global_vs_cluster": "Global対Cluster", "cluster_vs_cluster": "Cluster間比較", "multi_scope": "複数scope横断", "projection": "次元削減表示"}


def _scope(subject: dict[str, Any]) -> str:
    clusters = ", ".join(subject.get("cluster_ids") or [])
    label = SCOPE_JA.get(subject.get("scope_mode"), str(subject.get("scope_mode")))
    return f"{label} ({clusters})" if clusters else label


def _refs(values: list[str]) -> str:
    return ", ".join(values) if values else "—"


def _result_samples(value: dict[str, Any]) -> str:
    samples = value.get("result_samples") or {}
    return ", ".join(f"{key}: n={number}" for key, number in samples.items()) if samples else "—"


def _display_title(item: dict[str, Any]) -> str:
    return str(item.get("title") or "").strip() or f"{item.get('insight_id', 'Insight')}の解析知見"


def _display_limitations(value: Any) -> list[str]:
    if isinstance(value, str):
        candidates: list[Any] = value.splitlines() or [value]
    elif isinstance(value, (list, tuple)):
        candidates = list(value)
        nonblank = [str(item).strip() for item in candidates if str(item).strip()]
        if len(nonblank) >= 2 and all(len(item) == 1 for item in nonblank):
            candidates = ["".join(str(item) for item in candidates)]
    else:
        candidates = []
    result: list[str] = []
    for candidate in candidates:
        text = str(candidate).strip().lstrip("-*・• \t").strip()
        if text and text not in result:
            result.append(text)
    return result or ["利用可能なOperator Resultと今回確認した解析範囲に依存する。"]


def render_markdown(report: dict[str, Any], report_dir: Path | None = None, run_root: Path | None = None) -> str:
    header = report["report_header"]
    review = report["review_manifest"]
    lines = [f"# {report['title']}", "", f"- Run / Round: `{report['run_id']}` / `{report['round_id']}`", f"- Endpoint: `{header['endpoint']}` (`higher_is_better={str(header['higher_is_better']).lower()}`)", f"- 単位 / 変換: {header.get('endpoint_unit') or '未指定'} / {header.get('endpoint_transform') or 'なし'}", f"- Round Outcome: `{header['completion']}`", "", "## エグゼクティブサマリー", "", report["executive_summary"], "", "## 解析範囲", "", report["coverage_summary"], "", f"- 選択Review Bundle: {len(review['selected_bundle_ids'])}", f"- 詳細確認Result: {len(review['detailed_result_refs'])}", f"- 未選択Bundle: {len(review['unselected_bundles'])}", f"- Bundle種別: {json.dumps(review['bundle_type_counts'], ensure_ascii=False)}", f"- Candidate class別: {json.dumps(review['candidate_class_counts'], ensure_ascii=False)}", f"- Operator別: {json.dumps(review['operator_counts'], ensure_ascii=False)}", "", "## Insight", ""]
    if not report["insights"]:
        lines += ["今回の確認範囲では、報告基準を満たすInsightは抽出されませんでした。これは解析失敗ではなく、保持すべき差異・一致・矛盾を確認できなかったnegative resultです。", ""]
    for item in report["insights"]:
        subject = item["analysis_subject"]
        facts = item["fact_panel"]
        lines += [f"### {item['insight_id']} — {_display_title(item)}", "", f"- 注目度: {ATTENTION_JA[item['attention']]}", f"- 種別: {CLAIM_JA[item['claim_kind']]}", f"- 対象: {_scope(subject)}", f"- Cluster生成: {facts.get('clustering_method') or '該当なし'} / 入力種別 `{subject['clustering_input_kind']}`", f"- Cluster生成Description: {_refs(facts.get('cluster_source_descriptions') or [])}", f"- 解析Description: {_refs(facts.get('analysis_descriptions') or [])}", f"- Operator / Metric: {_refs(facts.get('operators') or [])} / {_refs(facts.get('metrics') or [])}", f"- 母集団 / endpoint有効 / 実解析 / 除外: {subject['population_count']} / {subject['endpoint_valid_count']} / {subject['analyzed_count']} / {subject['excluded_count']}", f"- Result別sample数: {_result_samples(facts)}", f"- 支持Result: {_refs(item['supporting_results'])}", f"- 比較Result: {_refs(item['comparison_results'])}", f"- 反証Result: {_refs(item['counter_results'])}", "", "**観察**", "", item["observation"], "", "**解釈**", "", item["interpretation"], "", "**限界**", ""]
        lines += [f"- {value}" for value in _display_limitations(item.get("limitations"))] + [""]
        if item["recommended_followups"]:
            lines += ["**次Roundで検討可能な方向**", ""] + [f"- {value['title']}: {value['rationale']}" for value in item["recommended_followups"]] + [""]
    lines += ["## 参照Operator結果", "", "| Result | Operator | 対象 | n | Metric | Report |", "|---|---|---|---:|---|---|"]
    for card in report["result_catalog"]:
        link = card["artifact_links"].get("report") or ""
        if link and report_dir and run_root:
            link = Path(os.path.relpath(run_root / link, report_dir)).as_posix()
        linked = f"[個別report]({link})" if link else "—"
        lines.append(f"| `{card['result_ref']}` | {card['capability_id']} | {_scope(card['analysis_subject'])} | {card['analysis_subject']['analyzed_count']} | {card.get('metric') or '—'} | {linked} |")
    lines += ["", "## 未選択Review Bundle", ""]
    lines += [f"- {item.get('bundle_id')}: {item.get('candidate_class')} / {item.get('reason')}" for item in review["unselected_bundles"]] or ["- なし"]
    return "\n".join(lines) + "\n"


def render_html(report: dict[str, Any], report_dir: Path | None = None, run_root: Path | None = None) -> str:
    header = report["report_header"]
    review = report["review_manifest"]
    cards = []
    for item in report["insights"]:
        subject = item["analysis_subject"]
        facts = item["fact_panel"]
        limitations = "".join(f"<li>{html.escape(value)}</li>" for value in _display_limitations(item.get("limitations")))
        followups = "".join(f"<li><b>{html.escape(value['title'])}</b>: {html.escape(value['rationale'])}</li>" for value in item["recommended_followups"])
        overlap = subject.get("cluster_overlap")
        overlap_html = f"<div><span>Cluster重複</span><b>{overlap['count']}件 / Jaccard {overlap['jaccard']:.3f}</b></div>" if overlap else ""
        cards.append(f"<article class='insight {item['attention']}'><header><div><span class='id'>{html.escape(item['insight_id'])}</span><span class='badge'>{ATTENTION_JA[item['attention']]}</span><span class='badge muted'>{CLAIM_JA[item['claim_kind']]}</span></div><h3>{html.escape(_display_title(item))}</h3></header><div class='scope'>{html.escape(_scope(subject))}</div><div class='facts'><div><span>Cluster生成</span><b>{html.escape(str(facts.get('clustering_method') or '該当なし'))}</b></div><div><span>生成入力</span><b>{html.escape(subject['clustering_input_kind'])}</b></div><div><span>生成Description</span><b>{html.escape(_refs(facts.get('cluster_source_descriptions') or []))}</b></div><div><span>解析Description</span><b>{html.escape(_refs(facts.get('analysis_descriptions') or []))}</b></div><div><span>Operator</span><b>{html.escape(_refs(facts.get('operators') or []))}</b></div><div><span>Metric</span><b>{html.escape(_refs(facts.get('metrics') or []))}</b></div><div><span>母集団 / endpoint有効</span><b>{subject['population_count']} / {subject['endpoint_valid_count']}</b></div><div><span>実解析 / 除外</span><b>{subject['analyzed_count']} / {subject['excluded_count']}</b></div><div><span>Result別sample数</span><b>{html.escape(_result_samples(facts))}</b></div>{overlap_html}</div><section><h4>観察</h4><p>{html.escape(item['observation'])}</p><h4>解釈</h4><p>{html.escape(item['interpretation'])}</p><h4>支持・比較・反証</h4><p>支持: {html.escape(_refs(item['supporting_results']))}<br>比較: {html.escape(_refs(item['comparison_results']))}<br>反証: {html.escape(_refs(item['counter_results']))}</p><h4>限界</h4><ul>{limitations}</ul>{f'<h4>次Roundで検討可能な方向</h4><ul>{followups}</ul>' if followups else ''}</section></article>")
    if not cards:
        cards.append("<div class='empty'>報告基準を満たすInsightはありません。確認範囲で明確な差異・一致・矛盾を認めなかったnegative resultです。</div>")
    rows = []
    for card in report["result_catalog"]:
        link = card["artifact_links"].get("report")
        if link and report_dir and run_root:
            link = Path(os.path.relpath(run_root / link, report_dir)).as_posix()
        linked = f"<a href='{html.escape(link)}'>個別report</a>" if link else "—"
        rows.append(f"<tr><td>{html.escape(card['result_ref'])}</td><td>{html.escape(card['capability_id'])}</td><td>{html.escape(_scope(card['analysis_subject']))}</td><td>{card['analysis_subject']['analyzed_count']}</td><td>{html.escape(str(card.get('metric') or '—'))}</td><td>{linked}</td></tr>")
    unselected = "".join(f"<li><code>{html.escape(str(item.get('bundle_id')))}</code>: {html.escape(str(item.get('candidate_class')))} / {html.escape(str(item.get('reason')))}</li>" for item in review["unselected_bundles"]) or "<li>なし</li>"
    css = """body{margin:0;background:#f1f0ec;color:#283438;font-family:system-ui,-apple-system,'Noto Sans JP',sans-serif;line-height:1.7}main{max-width:1180px;margin:auto;padding:38px 28px 80px}.hero{background:#fff;border-top:7px solid #526b72;padding:28px 32px;box-shadow:0 4px 18px #26323814}.eyebrow,.id{letter-spacing:.08em;color:#526b72;font-weight:700}.summary{font-size:1.08rem}.overview,.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px}.overview>div,.facts>div{background:#fff;border:1px solid #d7dad7;border-radius:7px;padding:12px;min-width:0}.overview span,.facts span{display:block;color:#68767a;font-size:.78rem}.overview b,.facts b{display:block;margin-top:3px;overflow-wrap:anywhere;word-break:break-word}.insight{background:#fff;margin:22px 0;border:1px solid #d2d6d4;border-left:7px solid #7b8f91;border-radius:8px;overflow:hidden}.insight.pinned{border-left-color:#865d43}.insight.active{border-left-color:#526b72}.insight header,.insight section{padding:18px 24px}.scope{background:#e7eceb;padding:9px 24px;font-weight:700}.facts{padding:14px 24px;background:#f7f7f4}.badge{display:inline-block;margin-left:8px;padding:2px 8px;border:1px solid #8a999b;border-radius:99px;font-size:.75rem}.muted{color:#667275;border-color:#c2c9c8}h1,h2,h3,h4{line-height:1.35}h2{margin-top:42px;border-bottom:2px solid #9ba9a9;padding-bottom:8px}table{width:100%;border-collapse:collapse;background:#fff;font-size:.9rem}th,td{padding:10px;border-bottom:1px solid #dde0dd;text-align:left;vertical-align:top}.empty{padding:24px;background:#fff;border:1px solid #d7dad7}.coverage{background:#fff;padding:18px 22px;border-left:5px solid #8c9b9a}a{color:#355d67}@media print{body{background:#fff}main{max-width:none;padding:0}.hero,.insight{box-shadow:none;break-inside:avoid}a{color:#000;text-decoration:none}}"""
    bundle_type_counts = " / ".join(f"{key}: {value}" for key, value in sorted(review["bundle_type_counts"].items())) or "なし"
    candidate_class_counts = " / ".join(f"{key}: {value}" for key, value in sorted(review["candidate_class_counts"].items())) or "なし"
    operator_counts = " / ".join(f"{key}: {value}" for key, value in sorted(review["operator_counts"].items())) or "なし"
    return f"<!doctype html><html lang='ja'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{html.escape(report['title'])}</title><style>{css}</style></head><body><main><header class='hero'><div class='eyebrow'>CONDUCTOR INTERPRETATION</div><h1>{html.escape(report['title'])}</h1><div class='overview'><div><span>Run / Round</span><b>{html.escape(report['run_id'])} / {html.escape(report['round_id'])}</b></div><div><span>Endpoint</span><b>{html.escape(header['endpoint'])}</b></div><div><span>方向</span><b>higher_is_better={str(header['higher_is_better']).lower()}</b></div><div><span>Outcome</span><b>{html.escape(header['completion'])}</b></div><div><span>Review</span><b>Bundle {len(review['selected_bundle_ids'])} / Result {len(review['detailed_result_refs'])} / 未選択 {len(review['unselected_bundles'])}</b></div></div></header><h2>エグゼクティブサマリー</h2><p class='summary'>{html.escape(report['executive_summary'])}</p><h2>解析範囲</h2><div class='coverage'><p>{html.escape(report['coverage_summary'])}</p><p><b>Bundle種別</b><br>{html.escape(bundle_type_counts)}</p><p><b>Candidate class別</b><br>{html.escape(candidate_class_counts)}</p><p><b>Operator別</b><br>{html.escape(operator_counts)}</p></div><h2>Insight</h2>{''.join(cards)}<h2>参照Operator結果</h2><table><thead><tr><th>Result</th><th>Operator</th><th>対象</th><th>n</th><th>Metric</th><th>詳細</th></tr></thead><tbody>{''.join(rows)}</tbody></table><h2>未選択Review Bundle</h2><ul>{unselected}</ul><footer>Generated from a validated structured report model. 作業記録ではなく解釈レポートです。</footer></main></body></html>"


def quality_issues(report: dict[str, Any]) -> list[str]:
    import re

    issues: list[str] = []
    executive = report.get("executive_summary", "").strip()
    coverage = report.get("coverage_summary", "").strip()
    japanese = re.compile(r"[ぁ-んァ-ヶ一-龯]")
    if len(executive) < 40:
        issues.append("executive_summary is too short for a human interpretation report")
    if not japanese.search(executive):
        issues.append("executive_summary must be written as Japanese human-facing prose")
    if len(coverage) < 30:
        issues.append("coverage_summary is too short to explain the reviewed scope")
    if not japanese.search(coverage):
        issues.append("coverage_summary must be written as Japanese human-facing prose")
    catalog = {card["result_ref"]: card for card in report["result_catalog"]}
    for insight in report["insights"]:
        if not str(insight.get("title") or "").strip():
            issues.append(f"{insight['insight_id']}: title is blank")
        raw_limitations = insight.get("limitations")
        if not isinstance(raw_limitations, list) or not raw_limitations:
            issues.append(f"{insight['insight_id']}: limitations must be a non-empty array")
        elif any(not isinstance(value, str) or not value.strip() for value in raw_limitations):
            issues.append(f"{insight['insight_id']}: limitations contains an empty or non-string value")
        elif len(raw_limitations) >= 2 and all(len(value.strip()) == 1 for value in raw_limitations):
            issues.append(f"{insight['insight_id']}: limitations contains character fragments")
        references = [*insight["supporting_results"], *insight["comparison_results"], *insight["counter_results"]]
        missing = set(references) - set(catalog)
        if missing:
            issues.append(f"{insight['insight_id']}: missing Result refs {sorted(missing)}")
        if insight["claim_kind"] in {"difference", "agreement", "contradiction"} and not insight["comparison_results"]:
            issues.append(f"{insight['insight_id']}: comparison claim requires comparison_results")
        allowed_clusters = set(insight["analysis_subject"]["cluster_ids"])
        text = " ".join(str(insight[key]) for key in ("title", "observation", "interpretation"))
        mentioned = set(re.findall(r"C[0-9]{6}", text))
        if mentioned - allowed_clusters:
            issues.append(f"{insight['insight_id']}: narrative mentions unrelated Cluster IDs {sorted(mentioned-allowed_clusters)}")
        if insight["analysis_subject"]["scope_mode"] == "single_cluster" and not insight["comparison_results"] and "Global" in text and any(token in text for token in ("比較", "差", "高い", "低い", "greater", "lower")):
            issues.append(f"{insight['insight_id']}: ungrounded Global comparison")
        subject = insight["analysis_subject"]
        mode = subject["scope_mode"]
        cluster_count = len(subject["cluster_ids"])
        if mode == "global" and cluster_count:
            issues.append(f"{insight['insight_id']}: Global scope must not carry Cluster IDs")
        if mode == "single_cluster" and cluster_count != 1:
            issues.append(f"{insight['insight_id']}: single_cluster scope requires exactly one Cluster ID")
        if mode in {"global_vs_cluster", "cluster_vs_cluster"} and cluster_count < 1:
            issues.append(f"{insight['insight_id']}: comparative Cluster scope lacks Cluster IDs")
        if len(insight["observation"].strip()) < 30:
            issues.append(f"{insight['insight_id']}: observation is too short")
        if not japanese.search(insight["observation"]):
            issues.append(f"{insight['insight_id']}: observation must be written as Japanese human-facing prose")
        if len(insight["interpretation"].strip()) < 30:
            issues.append(f"{insight['insight_id']}: interpretation is too short")
        if not japanese.search(insight["interpretation"]):
            issues.append(f"{insight['insight_id']}: interpretation must be written as Japanese human-facing prose")
        if subject["analyzed_count"] > subject["endpoint_valid_count"] or subject["endpoint_valid_count"] > subject["population_count"]:
            issues.append(f"{insight['insight_id']}: inconsistent sample counts")
        referenced_cards = [catalog[reference] for reference in references if reference in catalog]
        if referenced_cards:
            referenced_subjects = [card["analysis_subject"] for card in referenced_cards]
            expected_clusters = sorted({cluster for value in referenced_subjects for cluster in value["cluster_ids"]})
            referenced_modes = {value["scope_mode"] for value in referenced_subjects}
            if referenced_modes == {"global"}:
                expected_mode = "global"
            elif referenced_modes <= {"single_cluster"} and len(expected_clusters) == 1:
                expected_mode = "single_cluster"
            elif referenced_modes == {"global_vs_cluster"} and expected_clusters:
                expected_mode = "global_vs_cluster"
            elif referenced_modes == {"cluster_vs_cluster"} and len(expected_clusters) >= 2:
                expected_mode = "cluster_vs_cluster"
            elif "global" in referenced_modes and expected_clusters:
                expected_mode = "global_vs_cluster"
            elif len(expected_clusters) == 2:
                expected_mode = "cluster_vs_cluster"
            else:
                expected_mode = "multi_scope"
            if mode != expected_mode:
                issues.append(f"{insight['insight_id']}: scope_mode does not match referenced Results ({expected_mode})")
            if sorted(subject["cluster_ids"]) != expected_clusters:
                issues.append(f"{insight['insight_id']}: Cluster IDs do not match referenced Results")
            expected_counts = {
                key: max(int(value["analysis_subject"][key]) for value in referenced_cards)
                for key in ("population_count", "endpoint_valid_count", "analyzed_count", "excluded_count")
            }
            for key, expected in expected_counts.items():
                if int(subject[key]) != expected:
                    issues.append(f"{insight['insight_id']}: {key} does not match referenced Results ({expected})")
            expected_operators = sorted({card["capability_id"] for card in referenced_cards})
            if sorted(insight["fact_panel"].get("operators") or []) != expected_operators:
                issues.append(f"{insight['insight_id']}: Operator facts do not match referenced Results")
            expected_samples = {card["result_ref"]: card["analysis_subject"]["analyzed_count"] for card in referenced_cards}
            if insight["fact_panel"].get("result_samples") != expected_samples:
                issues.append(f"{insight['insight_id']}: Result sample facts do not match referenced Results")
    return issues
