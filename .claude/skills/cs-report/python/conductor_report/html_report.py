"""Self-contained, human-readable HTML rendering for accepted reports."""

from __future__ import annotations

import html
import math
import re
from typing import Any


MARKER = re.compile(r"\[\[([^\]]+)\]\]")


def _escape(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _number(value: Any) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _escape(value)
    if not math.isfinite(number):
        return "—"
    return f"{number:.6g}"


def _citation_anchor(index: int) -> str:
    return f"citation-{index}"


def _render_narrative(text: str, citation_indexes: dict[str, int]) -> str:
    parts: list[str] = []
    position = 0
    for match in MARKER.finditer(text):
        parts.append(_escape(text[position : match.start()]))
        citation_id = match.group(1)
        label = _escape(citation_id)
        index = citation_indexes.get(citation_id)
        if index is None:
            parts.append(f'<span class="citation missing">[{label}]</span>')
        else:
            parts.append(
                f'<a class="citation" href="#{_citation_anchor(index)}">[{label}]</a>'
            )
        position = match.end()
    parts.append(_escape(text[position:]))
    return "".join(parts)


def _best_test(finding: dict[str, Any]) -> tuple[Any, Any]:
    tests = finding.get("tests") or []
    if not tests:
        return None, None
    ordered = sorted(
        tests,
        key=lambda item: (
            float("inf") if item.get("q_value") is None else float(item["q_value"]),
            float("inf") if item.get("p_value") is None else float(item["p_value"]),
            str(item.get("test_id", "")),
        ),
    )
    return ordered[0].get("p_value"), ordered[0].get("q_value")


def _finding_row(finding: dict[str, Any]) -> str:
    claim = finding.get("claim") or {}
    state = finding.get("state") or {}
    scores = finding.get("scores") or {}
    p_value, q_value = _best_test(finding)
    subject = f"{claim.get('subject_type', '')}: {claim.get('subject_id', '')}"
    effect = " ".join(
        value
        for value in (
            str(claim.get("effect_direction", "")),
            _number(claim.get("effect_size")),
            str(claim.get("effect_unit", "")),
        )
        if value and value != "—"
    )
    return (
        "<tr>"
        f"<td>{_escape(scores.get('rank', '—'))}</td>"
        f"<td><code>{_escape(finding.get('finding_id', ''))}</code></td>"
        f"<td>{_escape(finding.get('lens', ''))}</td>"
        f"<td>{_escape(state.get('deep_dive', state.get('pipeline', '')))}</td>"
        f"<td>{_escape(subject)}</td>"
        f"<td>{_escape(claim.get('condition_id', ''))}</td>"
        f"<td>{_escape(effect)}</td>"
        f"<td>{_escape(claim.get('support_n', '—'))}</td>"
        f"<td>{_number(p_value)}</td>"
        f"<td>{_number(q_value)}</td>"
        f"<td>{_number(scores.get('composite'))}</td>"
        "</tr>"
    )


def render_html_report(
    report: dict[str, Any],
    findings: list[dict[str, Any]],
    validation: dict[str, Any],
    *,
    run_id: str,
    created_at: str,
) -> str:
    """Render one offline HTML document without external assets or scripts."""

    components = report.get("components") or []
    reportable = [
        item
        for item in findings
        if (item.get("state") or {}).get("pipeline") == "reportable"
    ]
    citation_refs: dict[str, str] = {}
    for finding in findings:
        for citation in finding.get("citations") or []:
            citation_refs.setdefault(
                str(citation.get("citation_id", "")),
                str(citation.get("table_ref", "")),
            )
    for component in components:
        for citation in component.get("citation_refs") or []:
            citation_refs.setdefault(
                str(citation.get("citation_id", "")),
                str(citation.get("table_ref", "")),
            )
    citation_refs.pop("", None)
    citation_indexes = {
        citation_id: index
        for index, citation_id in enumerate(sorted(citation_refs), start=1)
    }

    component_html: list[str] = []
    for component in components:
        narrative = component.get("narrative")
        if narrative is None:
            body = '<p class="muted">引用要件を満たす叙述は生成されませんでした。</p>'
        else:
            body = f"<p>{_render_narrative(str(narrative), citation_indexes)}</p>"
        finding_ids = ", ".join(str(value) for value in component.get("finding_ids") or [])
        component_html.append(
            "<article class=\"component\">"
            f"<h3>{_escape(component.get('component_id', 'Component'))}</h3>"
            f"<p class=\"meta\">Findings: {_escape(finding_ids)}</p>"
            f"{body}</article>"
        )

    sorted_findings = sorted(
        findings,
        key=lambda item: (
            int((item.get("scores") or {}).get("rank") or 2**31 - 1),
            str(item.get("finding_id", "")),
        ),
    )
    finding_rows = "".join(_finding_row(item) for item in sorted_findings)
    citation_rows = "".join(
        "<tr "
        f'id="{_citation_anchor(index)}"><td>{index}</td>'
        f"<td><code>{_escape(citation_id)}</code></td>"
        f"<td><code>{_escape(citation_refs[citation_id])}</code></td></tr>"
        for citation_id, index in citation_indexes.items()
    )
    telemetry_rows = "".join(
        "<tr>"
        f"<td>{_escape(item.get('lens', ''))}</td>"
        f"<td>{_escape(item.get('engine') or '—')}</td>"
        f"<td>{_escape(item.get('cost_model_version') or '—')}</td>"
        f"<td>{_escape(item.get('unit_count', '—'))}</td>"
        f"<td>{_number(item.get('estimated_seconds'))}</td>"
        f"<td>{_number(item.get('actual_wall_seconds'))}</td>"
        f"<td>{_number(item.get('estimate_actual_ratio'))}</td>"
        f"<td>{_number(item.get('observed_units_per_second'))}</td>"
        f"<td>{_escape(item.get('evaluation', ''))}</td>"
        "</tr>"
        for item in report.get("lens_telemetry") or []
    )
    errors = validation.get("errors") or []
    error_html = "".join(f"<li>{_escape(value)}</li>" for value in errors)
    status = str(validation.get("status", report.get("status", "unknown")))
    failure_fraction = validation.get("failure_fraction", 0.0)

    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CONDUCTOR report — {_escape(report.get('endpoint_id', ''))}</title>
<style>
:root{{--ink:#16202a;--muted:#5d6a75;--line:#d9e0e6;--paper:#fff;--wash:#f4f7f9;--accent:#155e75;--ok:#166534;--bad:#991b1b}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--wash);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1400px;margin:0 auto;padding:32px}} h1,h2,h3{{line-height:1.25}} h1{{margin-bottom:4px}} h2{{margin-top:36px;border-bottom:2px solid var(--accent);padding-bottom:6px}}
.meta,.muted{{color:var(--muted)}} .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:24px 0}}
.card,.component,.panel{{background:var(--paper);border:1px solid var(--line);border-radius:8px;padding:16px}} .card strong{{display:block;font-size:1.45rem}}
.status-succeeded{{color:var(--ok)}} .status-failed{{color:var(--bad)}} .component{{margin:12px 0}} code{{overflow-wrap:anywhere}}
.table-wrap{{overflow:auto;background:var(--paper);border:1px solid var(--line);border-radius:8px}} table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{border-bottom:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}} th{{position:sticky;top:0;background:#eaf0f3;white-space:nowrap}}
.citation{{font-size:.8em;text-decoration:none;color:var(--accent)}} .citation.missing{{color:var(--bad)}} ul.errors{{color:var(--bad)}}
@media print{{body{{background:#fff}} main{{max-width:none;padding:0}} .table-wrap{{overflow:visible}} th{{position:static}}}}
</style>
</head>
<body><main>
<header>
<h1>CONDUCTOR 0.2.1 解析レポート</h1>
<p class="meta">Run: <code>{_escape(run_id)}</code> ／ Endpoint: <code>{_escape(report.get('endpoint_id', ''))}</code> ／ 生成時刻: {_escape(created_at)}</p>
</header>
<section class="cards" aria-label="概要">
<div class="card"><span>監査状態</span><strong class="status-{_escape(status)}">{_escape(status)}</strong></div>
<div class="card"><span>Finding</span><strong>{len(findings)}</strong></div>
<div class="card"><span>Reportable</span><strong>{len(reportable)}</strong></div>
<div class="card"><span>連結成分</span><strong>{len(components)}</strong></div>
<div class="card"><span>LLM失敗率</span><strong>{_number(failure_fraction)}</strong></div>
</section>
<section><h2>統合叙述</h2>{''.join(component_html) or '<p class="muted">対象となる連結成分はありません。</p>'}</section>
<section><h2>Finding一覧</h2><div class="table-wrap"><table><thead><tr><th>順位</th><th>ID</th><th>Lens</th><th>状態</th><th>対象</th><th>条件</th><th>効果</th><th>support_n</th><th>p</th><th>q</th><th>score</th></tr></thead><tbody>{finding_rows}</tbody></table></div></section>
<section><h2>Lens実行telemetry</h2><div class="table-wrap"><table><thead><tr><th>Lens</th><th>Engine</th><th>Cost model</th><th>Units</th><th>Estimate (s)</th><th>Actual (s)</th><th>Estimate/actual</th><th>Observed units/s</th><th>評価</th></tr></thead><tbody>{telemetry_rows}</tbody></table></div><p class="muted">unsafe_underestimateは見積りが実時間より短いこと、conservativeは3倍を超える安全側見積りを示します。値は自動的な設定変更には使用しません。</p></section>
<section><h2>引用レジストリ</h2><div class="table-wrap"><table><thead><tr><th>#</th><th>Citation ID</th><th>Table reference</th></tr></thead><tbody>{citation_rows}</tbody></table></div></section>
<section class="panel"><h2>検証情報</h2><p>引用検証: <strong>{_escape(status)}</strong> ／ errors: {len(errors)}</p>{f'<ul class="errors">{error_html}</ul>' if errors else ''}<p class="muted">本HTMLは検証済みJSON/JSONL成果物の静的表示です。判断根拠の正本はRun内のFinding、Evidence、artifact manifestです。</p></section>
</main></body></html>
"""
