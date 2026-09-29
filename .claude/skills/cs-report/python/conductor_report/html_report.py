"""Self-contained, human-readable HTML rendering for accepted reports."""

from __future__ import annotations

import html
import json
import math
import re
from typing import Any

from .visualizations import render_lens_visual


MARKER = re.compile(r"\[\[([^\]]+)\]\]")

LENS_GUIDE = {
    "L1b": ("局所SARの平坦性", "同じ文脈内で、構造的に近い化合物のEndpointがどの程度そろうかを調べます。"),
    "L2a": ("変換効果の文脈依存性", "同じ構造変換のEndpoint効果が、特定文脈の内外で変わるかを調べます。"),
    "L2b": ("フラグメント寄与", "同じフラグメントが複数系列をまたいでEndpointへ一貫して寄与するかを調べます。"),
    "L4": ("未探索の有望領域", "既知化合物から一段階で到達できる未観測候補のうち、有望な領域を探します。"),
    "L5": ("相関方向の文脈差", "特徴量とEndpointの相関方向が、ある文脈と同じ軸の残りで逆転するかを調べます。"),
    "L7": ("系列間SAR比較", "共通置換基を持つ二系列で、SAR順位の反転や系列主効果があるかを調べます。"),
}

DIRECTION_LABELS = {
    "positive": "正方向",
    "negative": "負方向",
    "mixed": "方向反転・混合",
    "flat": "平坦",
}

DEEP_DIVE_LABELS = {
    "SURVIVED": "追加検証後も支持",
    "WEAKENED": "追加検証で弱まった",
    "REFUTED": "追加検証で反証",
    "INCONCLUSIVE": "追加検証では結論不能",
    "not_dived": "追加検証なし",
}

EVIDENCE_FIELDS = {
    "L1b": ("space_id", "context_id", "endpoint_n", "neighbor_k", "lambda", "global_variance"),
    "L2a": ("transform_class", "variable_from", "variable_to", "n_in", "n_out", "median_in", "median_out", "median_shift", "variance_ratio"),
    "L2b": ("fragment_smiles", "transform_class", "series_count", "residual_mean", "residual_sd", "residual_variance"),
    "L4": ("candidate_smiles", "space_count", "neighbor_k", "lower_confidence_limit", "density_gap", "region_score", "conservative_p_value"),
    "L5": ("axis_id", "context_a", "feature_id", "r_a", "r_b", "global_r", "n_a", "n_b", "fisher_z_difference"),
    "L7": ("series_a", "series_b", "common_r_count", "spearman_rho", "mean_difference"),
}

FIELD_LABELS = {
    "space_id": "特徴空間", "context_id": "文脈", "endpoint_n": "化合物数", "neighbor_k": "近傍数",
    "lambda": "局所平坦性 λ", "global_variance": "全体分散", "transform_class": "変換クラス",
    "variable_from": "変換前", "variable_to": "変換後", "n_in": "文脈内ペア数", "n_out": "文脈外ペア数",
    "median_in": "文脈内中央値", "median_out": "文脈外中央値", "median_shift": "中央値差",
    "variance_ratio": "分散比", "fragment_smiles": "フラグメント", "series_count": "系列数",
    "residual_mean": "系列調整後の平均寄与", "residual_sd": "寄与の標準偏差", "residual_variance": "寄与の分散",
    "candidate_smiles": "候補構造", "space_count": "使用空間数", "lower_confidence_limit": "下側信頼限界",
    "density_gap": "密度ギャップ", "region_score": "領域スコア", "conservative_p_value": "保守的p値",
    "axis_id": "文脈軸", "context_a": "対象文脈", "feature_id": "特徴量", "r_a": "対象文脈の相関",
    "r_b": "同軸補集合の相関", "global_r": "全体相関", "n_a": "対象文脈n", "n_b": "補集合n",
    "fisher_z_difference": "Fisher z差", "series_a": "系列A", "series_b": "系列B",
    "common_r_count": "共通置換基数", "spearman_rho": "順位相関", "mean_difference": "系列間平均差",
}


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


def _rank_key(finding: dict[str, Any]) -> tuple[Any, ...]:
    scores = finding.get("scores") or {}
    rank = scores.get("rank")
    p_value, q_value = _best_test(finding)
    return (
        int(rank) if rank is not None else 2**31 - 1,
        -float(scores.get("composite") or 0.0),
        float("inf") if q_value is None else float(q_value),
        float("inf") if p_value is None else float(p_value),
        str(finding.get("finding_id", "")),
    )


def _finding_statement(finding: dict[str, Any]) -> str:
    lens = str(finding.get("lens", ""))
    claim = finding.get("claim") or {}
    subject = str(claim.get("subject_id", ""))
    condition = str(claim.get("condition_id") or "全体")
    direction = DIRECTION_LABELS.get(str(claim.get("effect_direction", "")), str(claim.get("effect_direction", "")))
    feature_ids = (finding.get("entities") or {}).get("feature_ids") or []
    feature = str(feature_ids[0]) if feature_ids else subject.split("|", 1)[0]
    if lens == "L1b":
        return f"文脈「{condition}」の特徴空間「{subject}」で、類似化合物間のEndpointが局所的にそろう傾向を検出しました。"
    if lens == "L2a":
        return f"構造変換「{subject}」のEndpoint効果が、文脈「{condition}」の内外で異なることを検出しました（{direction}）。"
    if lens == "L2b":
        if claim.get("effect_unit") == "oriented_endpoint_variance":
            return f"フラグメント「{subject}」のEndpoint寄与が、系列間で不均一であることを検出しました。"
        return f"フラグメント「{subject}」が複数系列でEndpointへ一貫した{direction}の寄与を示しました。"
    if lens == "L4":
        return f"未観測候補「{subject}」を、既知化合物から到達可能な有望領域として検出しました。"
    if lens == "L5":
        return f"特徴量「{feature}」とEndpointの相関方向が、文脈「{condition.replace('|complement', '')}」と同軸補集合で逆転しました。"
    if lens == "L7":
        if claim.get("effect_unit") == "spearman_rho":
            return f"系列ペア「{subject}」で、共通置換基に対するSAR順位の反転を検出しました。"
        return f"系列ペア「{subject}」で、共通置換基をそろえた後もEndpoint水準に{direction}の差を検出しました。"
    return f"{claim.get('subject_type', '対象')}「{subject}」について{direction}のFindingを検出しました。"


def _evidence_details(lens: str, row: dict[str, Any] | None) -> str:
    if not row:
        return '<p class="muted">詳細な引用行はこのHTML exportでは取得できませんでした。</p>'
    entries = []
    for field in EVIDENCE_FIELDS.get(lens, ()):
        value = row.get(field)
        if value is None or value == "":
            continue
        entries.append(
            f"<div><dt>{_escape(FIELD_LABELS.get(field, field))}</dt><dd>{_number(value)}</dd></div>"
        )
    return f'<dl class="evidence-grid">{"".join(entries)}</dl>' if entries else ""


def _top_finding_card(
    finding: dict[str, Any],
    citation_indexes: dict[str, int],
    evidence_by_ref: dict[str, dict[str, Any]],
    observations_by_finding: dict[str, list[dict[str, Any]]],
    compound_smiles: dict[str, str],
    fragment_smiles: dict[str, str],
    detail_href: str | None = None,
) -> str:
    lens = str(finding.get("lens", ""))
    lens_name = LENS_GUIDE.get(lens, (lens, ""))[0]
    scores = finding.get("scores") or {}
    claim = finding.get("claim") or {}
    state = finding.get("state") or {}
    triviality = finding.get("triviality") or {}
    p_value, q_value = _best_test(finding)
    citations = finding.get("citations") or []
    evidence_row = None
    citation_links = []
    for citation in citations:
        citation_id = str(citation.get("citation_id", ""))
        table_ref = str(citation.get("table_ref", ""))
        evidence_row = evidence_row or evidence_by_ref.get(table_ref)
        index = citation_indexes.get(citation_id)
        if index is not None:
            citation_links.append(f'<a class="citation" href="#{_citation_anchor(index)}">[{_escape(citation_id)}]</a>')
    deep_dive = DEEP_DIVE_LABELS.get(str(state.get("deep_dive", "")), str(state.get("deep_dive", "")))
    adjusted = triviality.get("adjusted_effect_size")
    effect_note = (
        f"調整後効果 {_number(adjusted)}／判定 {_escape(triviality.get('verdict', ''))}"
        if adjusted is not None else "交絡調整値なし"
    )
    detail_link = (
        f'<a class="detail-link" href="{_escape(detail_href)}">この知見の詳しい個別レポートを開く</a>'
        if detail_href else ""
    )
    visual = render_lens_visual(
        finding,
        evidence_row,
        observations_by_finding.get(str(finding.get("finding_key", "")), []),
        compound_smiles,
        fragment_smiles,
        compact=True,
    )
    return (
        '<article class="insight">'
        '<div class="insight-head">'
        f'<span class="rank">#{_escape(scores.get("rank", "—"))}</span>'
        f'<div><span class="lens">{_escape(lens)} · {_escape(lens_name)}</span>'
        f'<h3>{_escape(_finding_statement(finding))}</h3></div></div>'
        '<div class="metric-strip">'
        f'<span><b>総合スコア</b> {_number(scores.get("composite"))}</span>'
        f'<span><b>q値</b> {_number(q_value)}</span><span><b>p値</b> {_number(p_value)}</span>'
        f'<span><b>支持数</b> {_escape(claim.get("support_n", "—"))}</span>'
        f'<span><b>深掘り</b> {_escape(deep_dive)}</span></div>'
        f'<p class="interpretation">効果量 {_number(claim.get("effect_size"))} {_escape(claim.get("effect_unit", ""))}。{effect_note}。</p>'
        f'{visual}'
        f'{_evidence_details(lens, evidence_row)}'
        f'<p class="meta">Finding <code>{_escape(finding.get("finding_id", ""))}</code> · 根拠 {" ".join(citation_links) or "—"}</p>'
        f'{detail_link}'
        '</article>'
    )


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


def _citation_maps(
    findings: list[dict[str, Any]], components: list[dict[str, Any]] | None = None
) -> tuple[dict[str, str], dict[str, int]]:
    references: dict[str, str] = {}
    for finding in findings:
        for citation in finding.get("citations") or []:
            references.setdefault(
                str(citation.get("citation_id", "")),
                str(citation.get("table_ref", "")),
            )
    for component in components or []:
        for citation in component.get("citation_refs") or []:
            references.setdefault(
                str(citation.get("citation_id", "")),
                str(citation.get("table_ref", "")),
            )
    references.pop("", None)
    indexes = {
        citation_id: index
        for index, citation_id in enumerate(sorted(references), start=1)
    }
    return references, indexes


def _citation_rows(references: dict[str, str], indexes: dict[str, int]) -> str:
    return "".join(
        "<tr "
        f'id="{_citation_anchor(index)}"><td>{index}</td>'
        f"<td><code>{_escape(citation_id)}</code></td>"
        f"<td><code>{_escape(references[citation_id])}</code></td></tr>"
        for citation_id, index in indexes.items()
    )


def _page_style() -> str:
    return """
:root{--ink:#17212b;--muted:#5d6a75;--line:#d8e0e6;--paper:#fff;--wash:#f3f6f8;--accent:#0f5f73;--accent-wash:#e7f4f6;--ok:#166534;--bad:#991b1b;--warm:#8a4b08}
*{box-sizing:border-box} body{margin:0;background:var(--wash);color:var(--ink);font:15px/1.62 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1240px;margin:0 auto;padding:34px} h1,h2,h3{line-height:1.3} h1{margin:.2rem 0} h2{margin-top:40px;border-bottom:2px solid var(--accent);padding-bottom:7px} h3{margin:.25rem 0 .7rem}
a{color:var(--accent)} code{overflow-wrap:anywhere}.meta,.muted{color:var(--muted)}.lede{max-width:850px;font-size:1.05rem}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:24px 0}.card,.component,.panel,.insight{background:var(--paper);border:1px solid var(--line);border-radius:10px;padding:18px}.card strong{display:block;font-size:1.45rem}
.status-succeeded{color:var(--ok)}.status-failed{color:var(--bad)}.component,.insight{margin:14px 0}.insight{border-left:5px solid var(--accent)}.insight-head{display:flex;gap:15px;align-items:flex-start}.rank{display:grid;place-items:center;min-width:52px;height:38px;border-radius:20px;background:var(--accent);color:white;font-weight:700}.lens{font-weight:700;color:var(--accent)}
.title-list{display:grid;gap:8px;margin:14px 0}.title-only{display:flex;gap:12px;align-items:center;background:var(--paper);border:1px solid var(--line);border-radius:8px;padding:10px 14px}.title-only .rank{min-width:44px;height:30px;font-size:.9rem}.title-only a{font-weight:700;text-decoration:none}.title-only a:hover{text-decoration:underline}
.metric-strip{display:flex;flex-wrap:wrap;gap:8px;margin:13px 0}.metric-strip span{background:var(--accent-wash);border-radius:16px;padding:4px 10px}.interpretation{font-size:1.02rem}.detail-link{display:inline-block;margin-top:6px;padding:7px 12px;background:var(--accent);color:white;border-radius:6px;text-decoration:none;font-weight:700}
.evidence-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:8px;margin:14px 0}.evidence-grid div{background:#f7f9fa;border:1px solid var(--line);padding:8px 10px;border-radius:6px}.evidence-grid dt{font-size:.8rem;color:var(--muted)}.evidence-grid dd{margin:2px 0;font-weight:650;overflow-wrap:anywhere}
.lens-visual{margin:28px 0}.structure-sequence{display:flex;align-items:center;justify-content:center;gap:15px;flex-wrap:wrap;margin:16px 0}.molecule-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(215px,1fr));gap:12px}.molecule-panel{margin:0;background:#fff;border:1px solid var(--line);border-radius:9px;padding:8px;text-align:center}.molecule-panel svg{display:block;max-width:100%;height:auto;margin:auto}.molecule-panel figcaption{display:grid;gap:3px}.molecule-panel code{font-size:.75rem;color:var(--muted)}.chem-arrow{font-size:1.05rem;font-weight:750;color:var(--accent);max-width:130px;text-align:center}.representative-pair{margin:12px 0;padding:10px;border:1px solid var(--line);border-radius:9px}.data-figure{margin:18px 0}.chart{display:block;width:100%;height:auto;border:1px solid var(--line);border-radius:10px;background:#fff}.chart text{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;fill:var(--ink)}.chart-title{font-size:16px;font-weight:700}.axis-label{font-size:13px;font-weight:650}.tick{font-size:11px;fill:var(--muted)}.chart-legend{display:flex;gap:16px;justify-content:center;flex-wrap:wrap}.chart-legend span{display:inline-flex;align-items:center;gap:5px}.chart-legend i{display:inline-block;width:11px;height:11px;border-radius:50%}.figure-note,.data-figure figcaption{color:var(--muted);font-size:.88rem}.visual-missing{padding:14px;background:#fff8e8;border-left:4px solid #d59422}
.table-wrap{overflow:auto;background:var(--paper);border:1px solid var(--line);border-radius:8px}table{border-collapse:collapse;width:100%;font-size:13px}th,td{border-bottom:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}th{position:sticky;top:0;background:#eaf0f3;white-space:nowrap}
.citation{font-size:.82em;text-decoration:none;color:var(--accent)}.citation.missing,ul.errors{color:var(--bad)}details{margin:18px 0}summary{cursor:pointer;font-weight:700}.callout{background:#fff8e8;border-left:5px solid #d59422;padding:12px 16px;border-radius:6px}.back{display:inline-block;margin-bottom:12px}.json{white-space:pre-wrap;overflow-wrap:anywhere;background:#f7f9fa;border:1px solid var(--line);padding:12px;border-radius:6px}
@media(max-width:650px){main{padding:20px}.insight-head{display:block}.rank{margin-bottom:9px}}
@media print{body{background:#fff}main{max-width:none;padding:0}.table-wrap{overflow:visible}th{position:static}.detail-link{display:none}}
"""


def render_finding_html(
    finding: dict[str, Any],
    validation: dict[str, Any],
    *,
    run_id: str,
    endpoint_id: str,
    created_at: str,
    evidence_by_ref: dict[str, dict[str, Any]] | None = None,
    observations_by_finding: dict[str, list[dict[str, Any]]] | None = None,
    compound_smiles: dict[str, str] | None = None,
    fragment_smiles: dict[str, str] | None = None,
    overview_href: str | None = None,
) -> str:
    """Render one detailed Finding page from validated deterministic artifacts."""

    evidence_by_ref = evidence_by_ref or {}
    observations_by_finding = observations_by_finding or {}
    compound_smiles = compound_smiles or {}
    fragment_smiles = fragment_smiles or {}
    references, indexes = _citation_maps([finding])
    lens = str(finding.get("lens", ""))
    lens_name, lens_description = LENS_GUIDE.get(lens, (lens, ""))
    claim = finding.get("claim") or {}
    scores = finding.get("scores") or {}
    state = finding.get("state") or {}
    triviality = finding.get("triviality") or {}
    falsification = finding.get("falsification") or {}
    translation = finding.get("translation") or {}
    entities = finding.get("entities") or {}
    tests = finding.get("tests") or []
    deep_dive = DEEP_DIVE_LABELS.get(
        str(state.get("deep_dive", "")), str(state.get("deep_dive", ""))
    )
    test_rows = "".join(
        "<tr>"
        f"<td><code>{_escape(test.get('test_id', ''))}</code></td>"
        f"<td>{_escape(test.get('method', ''))}</td>"
        f"<td>{_escape(test.get('question', ''))}</td>"
        f"<td>{_number(test.get('statistic'))}</td>"
        f"<td>{_number(test.get('p_value'))}</td>"
        f"<td>{_number(test.get('q_value'))}</td>"
        f"<td>{_escape(test.get('multiplicity_family', ''))}</td></tr>"
        for test in tests
    )
    score_labels = (
        ("統計的強度", "statistical_strength"),
        ("頑健性", "robustness"),
        ("非自明性", "non_triviality"),
        ("実行可能性", "actionability"),
        ("探索価値", "frontier_relevance"),
        ("総合スコア", "composite"),
    )
    score_rows = "".join(
        f"<tr><td>{label}</td><td>{_number(scores.get(field))}</td></tr>"
        for label, field in score_labels
    )
    entity_rows = "".join(
        f"<tr><td>{_escape(name)}</td><td>{_escape(', '.join(str(value) for value in values) if isinstance(values, list) else values)}</td></tr>"
        for name, values in sorted(entities.items())
        if values not in (None, [], "")
    )
    evidence_sections: list[str] = []
    for citation in finding.get("citations") or []:
        citation_id = str(citation.get("citation_id", ""))
        reference = str(citation.get("table_ref", ""))
        row = evidence_by_ref.get(reference)
        evidence_sections.append(
            '<article class="panel">'
            f'<h3 id="{_citation_anchor(indexes[citation_id])}">{_escape(citation_id)}</h3>'
            f'<p class="meta"><code>{_escape(reference)}</code></p>'
            f'{_evidence_details(lens, row)}'
            + (
                '<details><summary>引用行の全フィールド</summary>'
                f'<pre class="json">{_escape(json.dumps(row, ensure_ascii=False, indent=2, default=str))}</pre></details>'
                if row else ""
            )
            + "</article>"
        )
    narrative = finding.get("narrative")
    narrative_html = (
        f'<p>{_render_narrative(str(narrative), indexes)}</p>'
        if narrative is not None
        else '<p class="muted">このFindingには個別の深掘り叙述がありません。</p>'
    )
    back_link = (
        f'<a class="back" href="{_escape(overview_href)}">← 全体レポートへ戻る</a>'
        if overview_href else ""
    )
    status = str(validation.get("status", "unknown"))
    primary_evidence = next(
        (
            evidence_by_ref.get(str(citation.get("table_ref", "")))
            for citation in finding.get("citations") or []
            if evidence_by_ref.get(str(citation.get("table_ref", ""))) is not None
        ),
        None,
    )
    visual = render_lens_visual(
        finding,
        primary_evidence,
        observations_by_finding.get(str(finding.get("finding_key", "")), []),
        compound_smiles,
        fragment_smiles,
    )
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_escape(finding.get('finding_id', 'Finding'))} — CONDUCTOR</title><style>{_page_style()}</style></head>
<body><main>{back_link}<header><p class="lens">{_escape(lens)} · {_escape(lens_name)}</p>
<h1>{_escape(_finding_statement(finding))}</h1>
<p class="meta">Finding <code>{_escape(finding.get('finding_id', ''))}</code> ／ 順位 #{_escape(scores.get('rank', '—'))} ／ Endpoint <code>{_escape(endpoint_id)}</code></p></header>
<section class="cards"><div class="card"><span>総合スコア</span><strong>{_number(scores.get('composite'))}</strong></div><div class="card"><span>効果量</span><strong>{_number(claim.get('effect_size'))}</strong><small>{_escape(claim.get('effect_unit', ''))}</small></div><div class="card"><span>support_n</span><strong>{_escape(claim.get('support_n', '—'))}</strong></div><div class="card"><span>深掘り結果</span><strong>{_escape(deep_dive)}</strong></div></section>
{visual}
<section><h2>この知見が意味すること</h2><p class="lede">{_escape(lens_description)}</p><p>{_escape(_finding_statement(finding))}</p><p>対象は <code>{_escape(claim.get('subject_id', ''))}</code>、条件は <code>{_escape(claim.get('condition_id') or '全体')}</code>、効果方向は <strong>{_escape(DIRECTION_LABELS.get(str(claim.get('effect_direction', '')), claim.get('effect_direction', '')))}</strong>です。</p><p class="callout">この説明は検証済みFindingと引用行を決定論的に整形したものです。外部知識による機序推定や新たな解析結果は追加していません。</p></section>
<section><h2>統計的根拠</h2><div class="table-wrap"><table><thead><tr><th>Test ID</th><th>方法</th><th>検定対象</th><th>統計量</th><th>p</th><th>q</th><th>多重性族</th></tr></thead><tbody>{test_rows}</tbody></table></div></section>
<section><h2>重要度の根拠</h2><p>順位はp値だけでは決まりません。統計的強度と頑健性のgateを通過したFindingを、非自明性・実行可能性・探索価値の総合スコアで評価しています。</p><div class="table-wrap"><table><tbody>{score_rows}</tbody></table></div></section>
<section><h2>交絡・自明性の評価</h2><p>生の効果量 {_number(triviality.get('raw_effect_size'))} ／ 調整後効果量 {_number(triviality.get('adjusted_effect_size'))} ／ 判定 <strong>{_escape(triviality.get('verdict', '—'))}</strong></p><p class="meta">調整対象: {_escape(', '.join(str(value) for value in triviality.get('confounders_tested', [])) or 'なし')}</p></section>
<section><h2>追加検証（deep dive）</h2><p><strong>{_escape(deep_dive)}</strong></p>{narrative_html}</section>
<section><h2>反証条件</h2><p>Type: <code>{_escape(falsification.get('type', ''))}</code></p><p>{_escape(falsification.get('decision_rule', ''))}</p><details><summary>反証パラメータ</summary><pre class="json">{_escape(json.dumps(falsification.get('parameters') or {}, ensure_ascii=False, indent=2, default=str))}</pre></details></section>
<section><h2>次の検証候補</h2><p>優先度: {_escape(translation.get('priority', '—'))} ／ 実行可能性: {_escape(translation.get('actionability', '—'))}</p><p>{_escape(translation.get('suggested_action', translation.get('recommendation', 'Findingの反証条件と引用行を確認し、対象系列で追試候補を設計してください。')))}</p></section>
<section><h2>関連entity</h2><div class="table-wrap"><table><tbody>{entity_rows}</tbody></table></div></section>
<section><h2>引用Evidence</h2>{''.join(evidence_sections) or '<p class="muted">引用行はありません。</p>'}</section>
<section class="panel"><h2>監査情報</h2><p>Run <code>{_escape(run_id)}</code> ／ 生成時刻 {_escape(created_at)} ／ citation validation <strong class="status-{_escape(status)}">{_escape(status)}</strong></p><p class="muted">監査正本はRun内のFinding、Evidence、artifact manifestです。</p></section>
</main></body></html>"""


def render_html_report(
    report: dict[str, Any],
    findings: list[dict[str, Any]],
    validation: dict[str, Any],
    *,
    run_id: str,
    created_at: str,
    evidence_by_ref: dict[str, dict[str, Any]] | None = None,
    observations_by_finding: dict[str, list[dict[str, Any]]] | None = None,
    compound_smiles: dict[str, str] | None = None,
    fragment_smiles: dict[str, str] | None = None,
    finding_report_paths: dict[str, str] | None = None,
) -> str:
    """Render the human overview and retain audit tables as appendices."""

    evidence_by_ref = evidence_by_ref or {}
    observations_by_finding = observations_by_finding or {}
    compound_smiles = compound_smiles or {}
    fragment_smiles = fragment_smiles or {}
    finding_report_paths = finding_report_paths or {}
    components = report.get("components") or []
    reportable = sorted(
        [item for item in findings if (item.get("state") or {}).get("pipeline") == "reportable"],
        key=_rank_key,
    )
    finding_page_k = max(0, int(report.get("finding_page_k", 20)))
    overview_detail_k = max(
        0, min(finding_page_k, int(report.get("overview_detail_k", 10)))
    )
    paged = reportable[:finding_page_k]
    important = paged[:overview_detail_k]
    title_only = paged[overview_detail_k:]
    citation_refs, citation_indexes = _citation_maps(findings, components)

    component_html: list[str] = []
    for component in components:
        narrative = component.get("narrative")
        body = (
            '<p class="muted">引用要件を満たす叙述は生成されませんでした。</p>'
            if narrative is None
            else f"<p>{_render_narrative(str(narrative), citation_indexes)}</p>"
        )
        finding_ids = ", ".join(str(value) for value in component.get("finding_ids") or [])
        component_html.append(
            '<article class="component">'
            f"<h3>{_escape(component.get('component_id', 'Component'))}</h3>"
            f'<p class="meta">Findings: {_escape(finding_ids)}</p>{body}</article>'
        )
    important_html = "".join(
        _top_finding_card(
            finding,
            citation_indexes,
            evidence_by_ref,
            observations_by_finding,
            compound_smiles,
            fragment_smiles,
            finding_report_paths.get(str(finding.get("finding_id", ""))),
        )
        for finding in important
    )
    title_only_html = "".join(
        '<div class="title-only">'
        f'<span class="rank">#{_escape((finding.get("scores") or {}).get("rank", "—"))}</span>'
        + (
            f'<a href="{_escape(finding_report_paths[str(finding.get("finding_id", ""))])}">{_escape(_finding_statement(finding))}</a>'
            if str(finding.get("finding_id", "")) in finding_report_paths
            else f'<span>{_escape(_finding_statement(finding))}</span>'
        )
        + "</div>"
        for finding in title_only
    )
    lens_counts: dict[str, int] = {}
    for finding in reportable:
        lens = str(finding.get("lens", "unknown"))
        lens_counts[lens] = lens_counts.get(lens, 0) + 1
    lens_summary = "".join(
        f'<div class="card"><span>{_escape(lens)} · {_escape(LENS_GUIDE.get(lens, (lens, ""))[0])}</span><strong>{count}</strong></div>'
        for lens, count in sorted(lens_counts.items())
    )
    finding_rows = "".join(_finding_row(item) for item in sorted(findings, key=_rank_key))
    telemetry_rows = "".join(
        "<tr>"
        f"<td>{_escape(item.get('lens', ''))}</td><td>{_escape(item.get('engine') or '—')}</td>"
        f"<td>{_escape(item.get('cost_model_version') or '—')}</td><td>{_escape(item.get('unit_count', '—'))}</td>"
        f"<td>{_number(item.get('estimated_seconds'))}</td><td>{_number(item.get('actual_wall_seconds'))}</td>"
        f"<td>{_number(item.get('estimate_actual_ratio'))}</td><td>{_number(item.get('observed_units_per_second'))}</td>"
        f"<td>{_escape(item.get('evaluation', ''))}</td></tr>"
        for item in report.get("lens_telemetry") or []
    )
    errors = validation.get("errors") or []
    error_html = "".join(f"<li>{_escape(value)}</li>" for value in errors)
    status = str(validation.get("status", report.get("status", "unknown")))
    failure_fraction = validation.get("failure_fraction", 0.0)
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CONDUCTOR report — {_escape(report.get('endpoint_id', ''))}</title><style>{_page_style()}</style></head>
<body><main><header><h1>CONDUCTOR 0.2.1 解析レポート</h1><p class="lede">今回得られた知見のうち、設定済みの重要度評価で優先されたものを、人が内容を理解できる形で示します。</p><p class="meta">Run: <code>{_escape(run_id)}</code> ／ Endpoint: <code>{_escape(report.get('endpoint_id', ''))}</code> ／ 生成時刻: {_escape(created_at)}</p></header>
<section class="cards" aria-label="概要"><div class="card"><span>監査状態</span><strong class="status-{_escape(status)}">{_escape(status)}</strong></div><div class="card"><span>全Finding</span><strong>{len(findings)}</strong></div><div class="card"><span>重要度評価対象</span><strong>{len(reportable)}</strong></div><div class="card"><span>表紙で詳述</span><strong>{len(important)}</strong></div><div class="card"><span>個別レポート</span><strong>{len(paged)}</strong></div><div class="card"><span>LLM失敗率</span><strong>{_number(failure_fraction)}</strong></div></section>
<section><h2>重要な知見：1～{overview_detail_k}位</h2><p>以下は単なるFinding一覧ではなく、対象、条件、効果、統計的根拠、deep dive結果、Evidenceをまとめた要約です。各「個別レポート」では反証条件まで確認できます。</p><p class="muted">順位はp値の昇順ではありません。統計的強度と頑健性のgateを通過後、非自明性・実行可能性・探索価値の総合スコアで評価し、q値は同点時の判定に使います。</p>{important_html or '<p class="muted">詳述対象のreportable Findingはありません。</p>'}</section>
<section><h2>{overview_detail_k + 1}～{finding_page_k}位</h2><p class="muted">表紙ではタイトルだけを示します。各タイトルから図・統計・Evidenceを含む個別レポートを開けます。</p><div class="title-list">{title_only_html or '<p class="muted">該当するFindingはありません。</p>'}</div></section>
<section><h2>Lens別の知見数</h2><div class="cards">{lens_summary or '<p class="muted">対象なし</p>'}</div></section>
<section><h2>知見間のつながり</h2>{''.join(component_html) or '<p class="muted">対象となる連結成分はありません。</p>'}</section>
<details><summary>監査用付録：全Finding一覧</summary><div class="table-wrap"><table><thead><tr><th>順位</th><th>ID</th><th>Lens</th><th>状態</th><th>対象</th><th>条件</th><th>効果</th><th>support_n</th><th>p</th><th>q</th><th>score</th></tr></thead><tbody>{finding_rows}</tbody></table></div></details>
<details><summary>運用付録：Lens実行telemetry</summary><div class="table-wrap"><table><thead><tr><th>Lens</th><th>Engine</th><th>Cost model</th><th>Units</th><th>Estimate (s)</th><th>Actual (s)</th><th>Estimate/actual</th><th>Observed units/s</th><th>評価</th></tr></thead><tbody>{telemetry_rows}</tbody></table></div></details>
<details><summary>監査用付録：引用レジストリ</summary><div class="table-wrap"><table><thead><tr><th>#</th><th>Citation ID</th><th>Table reference</th></tr></thead><tbody>{_citation_rows(citation_refs, citation_indexes)}</tbody></table></div></details>
<section class="panel"><h2>検証情報</h2><p>引用検証: <strong>{_escape(status)}</strong> ／ errors: {len(errors)}</p>{f'<ul class="errors">{error_html}</ul>' if errors else ''}<p class="muted">本HTMLは検証済みJSON/JSONL成果物の静的表示です。判断根拠の正本はRun内のFinding、Evidence、artifact manifestです。</p></section>
</main></body></html>"""
