from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


AXES = (
    ("favorable_signal", "良好方向シグナル"),
    ("context_deviation", "文脈差・Global–Local乖離"),
    ("chemical_actionability", "化学的実行可能性"),
    ("independent_support", "独立な支持"),
    ("follow_up_leverage", "追試・深掘り価値"),
)
CLASS_META = {
    "design_lead": ("Design lead", "#496f67", 0),
    "contextual_anomaly": ("Contextual anomaly", "#9a7145", 1),
    "supporting_evidence": ("Supporting evidence", "#67788a", 2),
    "background": ("Background", "#9a9b96", 3),
    "not_scorable": ("Not scorable", "#806f79", 4),
    "awaiting_comparator": ("Awaiting comparator", "#b0a68f", 5),
}
RELIABILITY = (
    ("sample_support", "サンプル支持", ("strong", "moderate", "limited", "insufficient")),
    ("comparator_validity", "比較妥当性", ("matched", "partial", "none")),
    ("effect_stability", "効果安定性", ("stable", "mixed", "unstable", "unknown")),
    ("independence", "独立性", ("independent", "partially_independent", "overlapping", "unknown")),
)
REPORTABLE = {"design_lead", "contextual_anomaly"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path, *, required: bool = True) -> list[dict[str, Any]]:
    if not path.is_file():
        if required:
            raise FileNotFoundError(f"Required source is missing: {path}")
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"Expected an object at {path}:{line_number}")
            rows.append(value)
    return rows


def latest_by(rows: Iterable[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        identity = str(row.get(key) or "")
        if not identity:
            continue
        previous = latest.get(identity)
        current_order = (int(row.get("revision") or 0), str(row.get("updated_at") or row.get("created_at") or ""))
        previous_order = (int(previous.get("revision") or 0), str(previous.get("updated_at") or previous.get("created_at") or "")) if previous else (-1, "")
        if previous is None or current_order >= previous_order:
            latest[identity] = row
    return latest


def atomic_text(path: Path, value: str) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def csv_safe(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: csv_safe(row.get(field, "")) for field in fields})
    atomic_text(path, buffer.getvalue())


def e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def find_catalog(run_root: Path) -> dict[str, str]:
    implementation = Path(__file__).resolve()
    candidates = [run_root, *run_root.parents, implementation, *implementation.parents]
    seen: set[Path] = set()
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate in seen:
            continue
        seen.add(candidate)
        path = candidate / "CONDUCTOR_modules" / "catalog" / "catalog.json"
        if path.is_file():
            value = json.loads(path.read_text(encoding="utf-8"))
            return {str(item["capability_id"]): str(item["display_name"]) for item in value.get("capabilities") or []}
    return {}


def bar_rows(counts: Counter[str], order: Iterable[str], labels: dict[str, str] | None = None, colors: dict[str, str] | None = None) -> str:
    maximum = max(counts.values(), default=1)
    parts: list[str] = []
    for key in order:
        count = counts.get(key, 0)
        width = 100.0 * count / maximum if maximum else 0.0
        label = (labels or {}).get(key, key)
        color = (colors or {}).get(key, "#667b7a")
        parts.append(
            f'<div class="bar-row"><span class="bar-label">{e(label)}</span>'
            f'<span class="bar-track"><i style="width:{width:.2f}%;background:{e(color)}"></i></span>'
            f'<b>{count}</b></div>'
        )
    return "".join(parts)


def score_value(value: Any) -> str:
    return str(value) if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 3 else "N/A"


def display_row(assessment: dict[str, Any], bundles: dict[str, dict[str, Any]], picked: dict[str, list[dict[str, Any]]], names: dict[str, str]) -> dict[str, Any]:
    bundle_id = str(assessment.get("bundle_id") or "")
    bundle = bundles.get(bundle_id) or {}
    scores = assessment.get("scores") or {}
    reliability = assessment.get("reliability") or {}
    references = picked.get(bundle_id) or []
    current = bool(bundle) and assessment.get("source_hash") == bundle.get("source_hash") and assessment.get("rubric_version") == "2.0.0"
    return {
        "assessment_id": assessment.get("assessment_id"),
        "bundle_id": bundle_id,
        "bundle_type": assessment.get("bundle_type") or bundle.get("bundle_type"),
        "round_id": assessment.get("round_id"),
        "source_round_id": assessment.get("source_round_id", assessment.get("round_id")),
        "capability_id": assessment.get("capability_id"),
        "capability_name": names.get(str(assessment.get("capability_id")), ""),
        "candidate_class": assessment.get("candidate_class"),
        "assessment_status": assessment.get("assessment_status"),
        "sample_support": reliability.get("sample_support"),
        "comparator_validity": reliability.get("comparator_validity"),
        "effect_stability": reliability.get("effect_stability"),
        "independence": reliability.get("independence"),
        **{axis: score_value(scores.get(axis)) for axis, _ in AXES},
        "cluster_ids": ";".join(bundle.get("cluster_ids") or []),
        "target_result_refs": ";".join(assessment.get("target_result_refs") or []),
        "reason": str(assessment.get("reason") or ""),
        "current_assessment": current,
        "included_in_full_report": bool(references),
        "insight_ids": ";".join(sorted({str(item.get("insight_id")) for item in references if item.get("insight_id")})),
        "interpretation_rounds": ";".join(sorted({str(item.get("round_id")) for item in references if item.get("round_id")})),
        "revision": assessment.get("revision"),
    }


def candidate_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    class_rank = {key: value[2] for key, value in CLASS_META.items()}
    support_rank = {"strong": 0, "moderate": 1, "limited": 2, "insufficient": 3}
    def descending(axis: str) -> int:
        value = row.get(axis)
        return -int(value) if str(value).isdigit() else 1
    return (
        class_rank.get(str(row.get("candidate_class")), 9),
        support_rank.get(str(row.get("sample_support")), 9),
        descending("chemical_actionability"),
        descending("follow_up_leverage"),
        descending("favorable_signal"),
        str(row.get("capability_id")),
        str(row.get("bundle_id")),
    )


def top_table(rows: list[dict[str, Any]], empty_message: str) -> str:
    if not rows:
        return f'<p class="empty">{e(empty_message)}</p>'
    body: list[str] = []
    for rank, row in enumerate(rows, 1):
        class_label, color, _ = CLASS_META.get(str(row["candidate_class"]), (str(row["candidate_class"]), "#777", 9))
        picked = "収載済" if row["included_in_full_report"] else "未収載"
        picked_class = "picked" if row["included_in_full_report"] else "unpicked"
        reason = row["reason"]
        if len(reason) > 220:
            reason = reason[:217] + "…"
        body.append(
            "<tr>"
            f"<td>{rank}</td><td><code>{e(row['bundle_id'])}</code></td>"
            f"<td><span class=\"pill\" style=\"--pill:{e(color)}\">{e(class_label)}</span></td>"
            f"<td><b>{e(row['capability_id'])}</b><br><small>{e(row['capability_name'])}</small></td>"
            f"<td>{e(row['bundle_type'])}<br><small>{e(row['cluster_ids'] or 'Global')}</small></td>"
            f"<td class=\"scores\">{e(row['favorable_signal'])} / {e(row['context_deviation'])} / {e(row['chemical_actionability'])} / {e(row['independent_support'])} / {e(row['follow_up_leverage'])}</td>"
            f"<td>{e(row['sample_support'])}</td><td><span class=\"{picked_class}\">{picked}</span><br><small>{e(row['insight_ids'])}</small></td>"
            f"<td>{e(reason)}</td></tr>"
        )
    return (
        '<div class="table-wrap"><table><thead><tr><th>#</th><th>Bundle</th><th>総合評価区分</th><th>Operator</th>'
        '<th>比較Scope</th><th>5軸<br><small>Fav / Dev / Act / Sup / Next</small></th><th>Sample</th><th>Full report</th><th>一次評価理由</th>'
        "</tr></thead><tbody>" + "".join(body) + "</tbody></table></div>"
    )


def render_html(rows: list[dict[str, Any]], top: list[dict[str, Any]], overlooked: list[dict[str, Any]], run_root: Path, selected_rounds: list[str], created_at: str, invalid_count: int, stale_count: int) -> str:
    current_rows = [row for row in rows if row["current_assessment"]]
    class_counts = Counter(str(row["candidate_class"]) for row in current_rows)
    class_order = list(CLASS_META)
    class_labels = {key: value[0] for key, value in CLASS_META.items()}
    class_colors = {key: value[1] for key, value in CLASS_META.items()}
    reportable = [row for row in current_rows if row["candidate_class"] in REPORTABLE]
    picked_count = sum(bool(row["included_in_full_report"]) for row in reportable)
    axis_panels: list[str] = []
    axis_colors = {"0": "#b8b7b1", "1": "#8e9a99", "2": "#6d8883", "3": "#496f67", "N/A": "#d2cec4"}
    for axis, label in AXES:
        counts = Counter(str(row[axis]) for row in current_rows)
        axis_panels.append(
            f'<article class="chart"><h3>{e(label)}</h3>{bar_rows(counts, ("0", "1", "2", "3", "N/A"), colors=axis_colors)}</article>'
        )
    reliability_panels: list[str] = []
    for key, label, order in RELIABILITY:
        counts = Counter(str(row.get(key) or "unknown") for row in current_rows)
        reliability_panels.append(f'<article class="chart compact"><h3>{e(label)}</h3>{bar_rows(counts, order)}</article>')
    round_stats: dict[str, Counter[str]] = defaultdict(Counter)
    for row in current_rows:
        bucket = round_stats[str(row["source_round_id"])]
        bucket["assessed"] += 1
        if row["candidate_class"] in REPORTABLE:
            bucket["reportable"] += 1
        if row["included_in_full_report"]:
            bucket["picked"] += 1
    round_table = "".join(
        f'<tr><td>{e(round_id)}</td><td>{counts["assessed"]}</td><td>{counts["reportable"]}</td><td>{counts["picked"]}</td><td>{(100*counts["picked"]/counts["reportable"] if counts["reportable"] else 0):.1f}%</td></tr>'
        for round_id, counts in sorted(round_stats.items())
    ) or '<tr><td colspan="5">対象データなし</td></tr>'
    operator_stats: dict[str, Counter[str]] = defaultdict(Counter)
    operator_names: dict[str, str] = {}
    for row in current_rows:
        capability = str(row["capability_id"])
        operator_names[capability] = str(row["capability_name"])
        operator_stats[capability][str(row["candidate_class"])] += 1
    operator_order = sorted(operator_stats, key=lambda key: (-sum(operator_stats[key].values()), key))
    operator_table = "".join(
        f'<tr><td><b>{e(capability)}</b></td><td>{e(operator_names.get(capability))}</td><td>{sum(operator_stats[capability].values())}</td>'
        f'<td>{operator_stats[capability]["design_lead"]}</td><td>{operator_stats[capability]["contextual_anomaly"]}</td>'
        f'<td>{operator_stats[capability]["supporting_evidence"]}</td><td>{operator_stats[capability]["background"]}</td></tr>'
        for capability in operator_order
    ) or '<tr><td colspan="7">対象データなし</td></tr>'
    class_uptake = "".join(
        f'<tr><td>{e(CLASS_META[key][0])}</td><td>{class_counts[key]}</td><td>{sum(1 for row in current_rows if row["candidate_class"] == key and row["included_in_full_report"])}</td>'
        f'<td>{(100*sum(1 for row in current_rows if row["candidate_class"] == key and row["included_in_full_report"])/class_counts[key] if class_counts[key] else 0):.1f}%</td></tr>'
        for key in class_order
    )
    scope_label = ", ".join(selected_rounds) if selected_rounds else "全Round（各Bundleの最新revision）"
    warnings = []
    if stale_count:
        warnings.append(f"最新Bundleとsource hashが一致しない評価 {stale_count}件はTop候補と集計から除外しました。")
    if invalid_count:
        warnings.append(f"必須IDを欠く行 {invalid_count}件は集計できませんでした。")
    warning_html = f'<section class="warning"><b>注意:</b> {e(" ".join(warnings))}</section>' if warnings else ""
    return f'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CONDUCTOR Assessment Summary</title>
<style>
:root{{--ink:#27363a;--muted:#657174;--paper:#f2f0eb;--panel:#fffdf8;--line:#d6d1c7;--accent:#496f67;--warm:#9a7145}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1500px;margin:auto;padding:34px}} h1{{font:600 32px/1.2 Georgia,serif;margin:0 0 8px}} h2{{font:600 23px/1.25 Georgia,serif;margin:0 0 16px}} h3{{font-size:14px;margin:0 0 12px}}
.sub{{color:var(--muted);margin:0}} section{{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:22px;margin:18px 0;box-shadow:0 4px 18px #3331}}
.facts{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}} .fact{{background:#f7f5f0;border-left:4px solid var(--accent);padding:13px}} .fact b{{font-size:26px}}
.charts{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}} .chart{{border:1px solid var(--line);border-radius:6px;padding:15px;background:#faf8f3}}
.bar-row{{display:grid;grid-template-columns:minmax(112px,1.1fr) 3fr 34px;gap:8px;align-items:center;margin:8px 0}} .bar-label{{font-size:12px}} .bar-track{{height:13px;background:#e7e3db;border-radius:2px;overflow:hidden}} .bar-track i{{display:block;height:100%}}
.table-wrap{{overflow:auto}} table{{width:100%;border-collapse:collapse;font-size:13px}} th,td{{padding:9px 10px;border-bottom:1px solid #e0ddd5;text-align:left;vertical-align:top}} th{{background:#eae6de;position:sticky;top:0}} code{{font-size:11px}} small{{color:var(--muted)}}
.pill{{display:inline-block;border-left:5px solid var(--pill);background:#efede8;padding:3px 7px;white-space:nowrap}} .picked{{color:#496f67;font-weight:700}} .unpicked{{color:#9a7145;font-weight:700}} .scores{{white-space:nowrap;font-family:ui-monospace,monospace}}
.note{{border-left:4px solid var(--warm);padding:10px 13px;background:#f3eee6;color:#554738}} .warning{{border-color:#b78668;background:#fff5ed}} .empty{{color:var(--muted)}} footer{{color:var(--muted);font-size:12px;margin:28px 0}}
@media(max-width:700px){{main{{padding:18px}} h1{{font-size:26px}}}}
</style></head><body><main>
<header><h1>CONDUCTOR 一次評価サマリー</h1><p class="sub">{e(scope_label)} ｜ Snapshot: {e(created_at)}</p></header>
{warning_html}
<section class="facts"><div class="fact">有効な一次評価<br><b>{len(current_rows)}</b></div><div class="fact">有望候補<br><b>{len(reportable)}</b></div><div class="fact">Full report収載<br><b>{picked_count}</b></div><div class="fact">Operator<br><b>{len(operator_stats)}</b></div><div class="fact">Round<br><b>{len(round_stats)}</b></div></section>
<section><h2>総合評価区分</h2><p class="note">5軸の単純合計ではありません。Runtimeが確定したCandidate classを、一次評価の総合区分として表示しています。</p><div class="chart">{bar_rows(class_counts, class_order, class_labels, class_colors)}</div></section>
<section><h2>評価軸ヒストグラム</h2><p class="sub">各軸は独立した0～3の絶対評価です。N/Aは当該Bundleで適用不能または未採点を示します。</p><div class="charts">{''.join(axis_panels)}</div></section>
<section><h2>信頼性の内訳</h2><div class="charts">{''.join(reliability_panels)}</div></section>
<section><h2>有望な知見 Top {len(top)}</h2><p class="sub">Design lead、Contextual anomalyのみ。表示順はclass、sample support、chemical actionability、follow-up leverage等に基づき、合計点は使いません。</p>{top_table(top, '現時点で有望候補に分類された一次評価はありません。')}</section>
<section><h2>Full report未収載の有望候補</h2><p class="sub">一次評価では有望だが、最新Insight indexから参照されていない候補です。未収載であること自体は見落としを断定しません。</p>{top_table(overlooked, '未収載の有望候補はありません。')}</section>
<section><h2>Full report収載率</h2><div class="table-wrap"><table><thead><tr><th>Candidate class</th><th>評価数</th><th>収載数</th><th>収載率</th></tr></thead><tbody>{class_uptake}</tbody></table></div></section>
<section><h2>Round推移</h2><div class="table-wrap"><table><thead><tr><th>Round</th><th>一次評価</th><th>有望候補</th><th>Full report収載</th><th>候補収載率</th></tr></thead><tbody>{round_table}</tbody></table></div></section>
<section><h2>Operator別内訳</h2><div class="table-wrap"><table><thead><tr><th>ID</th><th>Operator</th><th>評価数</th><th>Design lead</th><th>Contextual anomaly</th><th>Supporting</th><th>Background</th></tr></thead><tbody>{operator_table}</tbody></table></div></section>
<section><h2>データファイル</h2><ul><li><code>assessment_latest.csv</code>: 対象となった各Bundleの最新一次評価</li><li><code>top_candidates.csv</code>: 有望候補の表示順とFull report収載状況</li><li><code>report_manifest.json</code>: 入力hash、filter、件数、出力一覧</li></ul></section>
<footer>Read-only support report. Run Root: {e(run_root)}</footer>
</main></body></html>'''


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a read-only CONDUCTOR 0.2.0 primary-assessment dashboard")
    parser.add_argument("--run-root", required=True, help="CONDUCTOR Run Root containing conductor_control.json and runtime/")
    parser.add_argument("--round-id", action="append", default=[], help="Optional RND#### filter; repeatable")
    parser.add_argument("--top-n", type=int, default=10, help="Promising-candidate table size (1-50; default 10)")
    parser.add_argument("--explicit-request", action="store_true", help="Confirms explicit human invocation")
    args = parser.parse_args()
    if not args.explicit_request:
        parser.error("--explicit-request is required")
    if not 1 <= args.top_n <= 50:
        parser.error("--top-n must be between 1 and 50")
    selected_rounds = sorted(set(args.round_id))
    invalid_rounds = [value for value in selected_rounds if len(value) != 7 or not value.startswith("RND") or not value[3:].isdigit()]
    if invalid_rounds:
        parser.error(f"Invalid --round-id: {', '.join(invalid_rounds)}")

    root = Path(args.run_root).expanduser().resolve()
    control_path = root / "conductor_control.json"
    if not control_path.is_file():
        raise FileNotFoundError(f"Not a CONDUCTOR Run Root: {control_path} is missing")
    control = json.loads(control_path.read_text(encoding="utf-8"))
    if control.get("conductor_version") != "0.2.0":
        raise ValueError(f"This Skill requires a CONDUCTOR 0.2.0 Run; found {control.get('conductor_version')!r}")

    sources = {
        "control": control_path,
        "assessments": root / "runtime" / "result_assessment_index.jsonl",
        "bundles": root / "runtime" / "review_bundle_index.jsonl",
    }
    insight_path = root / "runtime" / "insight_index.jsonl"
    if insight_path.is_file():
        sources["insights"] = insight_path
    before = {key: file_hash(path) for key, path in sources.items()}
    assessments_raw = read_jsonl(sources["assessments"])
    bundles = latest_by(read_jsonl(sources["bundles"]), "bundle_id")
    insights = latest_by(read_jsonl(insight_path, required=False), "insight_id")
    after_read = {key: file_hash(path) for key, path in sources.items()}
    if before != after_read:
        raise RuntimeError("Canonical source files changed while the snapshot was being read; rerun after writes settle")

    invalid_count = sum(not row.get("bundle_id") for row in assessments_raw)
    assessments = latest_by(assessments_raw, "bundle_id")
    if selected_rounds:
        assessments = {
            key: value for key, value in assessments.items()
            if value.get("source_round_id", value.get("round_id")) in selected_rounds
        }
    picked: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for insight in insights.values():
        for bundle_id in insight.get("review_bundle_ids") or []:
            picked[str(bundle_id)].append(insight)
    names = find_catalog(root)
    rows = [display_row(value, bundles, picked, names) for value in assessments.values()]
    rows.sort(key=lambda row: (str(row["source_round_id"]), str(row["round_id"]), candidate_sort_key(row)))
    stale_count = sum(not row["current_assessment"] for row in rows)
    candidates = sorted(
        (row for row in rows if row["current_assessment"] and row["candidate_class"] in REPORTABLE),
        key=candidate_sort_key,
    )
    top = candidates[: args.top_n]
    overlooked = [row for row in candidates if not row["included_in_full_report"]][: args.top_n]

    report_parent = root / "assessment_reports"
    report_parent.mkdir(parents=True, exist_ok=True)
    try:
        report_parent.resolve().relative_to(root)
    except ValueError as exc:
        raise ValueError("assessment_reports must resolve inside the supplied Run Root") from exc
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = report_parent / stamp
    suffix = 1
    while output.exists():
        output = report_parent / f"{stamp}-{suffix:02d}"
        suffix += 1
    output.mkdir(parents=False, exist_ok=False)

    assessment_fields = [
        "assessment_id", "bundle_id", "bundle_type", "round_id", "source_round_id", "capability_id", "capability_name", "candidate_class",
        "assessment_status", "sample_support", "comparator_validity", "effect_stability", "independence",
        *[key for key, _ in AXES], "cluster_ids", "target_result_refs", "reason", "current_assessment",
        "included_in_full_report", "insight_ids", "interpretation_rounds", "revision",
    ]
    write_csv(output / "assessment_latest.csv", assessment_fields, rows)
    top_rows = [{"display_rank": index, **row} for index, row in enumerate(candidates, 1)]
    write_csv(output / "top_candidates.csv", ["display_rank", *assessment_fields], top_rows)
    created_at = utc_now()
    report_html = render_html(rows, top, overlooked, root, selected_rounds, created_at, invalid_count, stale_count)
    atomic_text(output / "assessment_summary.html", report_html)
    source_after_output = {key: file_hash(path) for key, path in sources.items()}
    if before != source_after_output:
        raise RuntimeError("Canonical source files changed before report completion; the report directory is an invalid partial snapshot")
    manifest = {
        "schema_version": "1.0.0",
        "conductor_version": "0.2.0",
        "created_at": created_at,
        "run_root": str(root),
        "filters": {"source_round_ids": selected_rounds or "all", "latest_revision_per_bundle": True},
        "scientific_axis_sum_used": False,
        "overall_assessment_display": "candidate_class_distribution",
        "candidate_selection": "reportable_class_then_sample_support_then_actionability_then_follow_up_then_favorable",
        "counts": {
            "latest_assessments": len(rows),
            "current_assessments": len(rows) - stale_count,
            "stale_or_orphan_assessments": stale_count,
            "reportable_candidates": len(candidates),
            "full_report_included_candidates": sum(row["included_in_full_report"] for row in candidates),
            "invalid_source_rows": invalid_count,
        },
        "source_hashes": before,
        "outputs": ["assessment_summary.html", "assessment_latest.csv", "top_candidates.csv", "report_manifest.json"],
        "state_mutation": "none",
        "dag_registration": "none",
    }
    atomic_text(output / "report_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output_dir": str(output), "html_report": str(output / "assessment_summary.html"), "candidate_count": len(candidates)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
