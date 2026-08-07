from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
STAGES = ["description", "grouping", "analysis", "interpretation"]
STAGE_LABELS = {
    "description": "Description",
    "grouping": "Grouping",
    "analysis": "Operator",
    "interpretation": "Interpretation",
}
STATUS_LABELS = {
    "pending": "未実行",
    "running": "実行中",
    "succeeded": "完了",
    "failed": "失敗",
    "unavailable": "利用不可",
    "waived": "省略承認",
    "not_applicable": "非該当",
    "skipped": "Skip",
    "stale": "Stale",
}
STATUS_COLORS = {
    "pending": "#d9dde0",
    "running": "#668196",
    "succeeded": "#5f7d73",
    "failed": "#95645c",
    "unavailable": "#95645c",
    "waived": "#a29b8f",
    "not_applicable": "#a29b8f",
    "skipped": "#a29b8f",
    "stale": "#a48853",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_state(value: dict[str, Any]) -> None:
    try:
        import jsonschema
    except ImportError as exc:
        raise RuntimeError("jsonschema is required to validate State") from exc
    schema = json.loads((SKILL_DIR / "schemas" / "state.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(value, schema)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render an explicitly supplied CONDUCTOR State as a read-only DAG report.")
    parser.add_argument("--state", required=True, help="Explicit path to the target CONDUCTOR state.json.")
    parser.add_argument(
        "--explicit-request",
        action="store_true",
        help="Required acknowledgement that a human explicitly requested this State visualization.",
    )
    args = parser.parse_args()
    if not args.explicit_request:
        parser.error("--explicit-request is required; this Skill must never run implicitly")
    return args


def natural_key(value: str) -> list[Any]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


def all_edges(state: dict[str, Any]) -> list[dict[str, str]]:
    nodes = state.get("execution_graph", {}).get("nodes", [])
    edges: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(source: Any, target: Any, relation: str) -> None:
        key = (str(source), str(target), relation)
        if source and target and key not in seen:
            seen.add(key)
            edges.append({"source": key[0], "target": key[1], "relation": relation})

    for edge in state.get("execution_graph", {}).get("edges", []):
        add(edge.get("source"), edge.get("target"), str(edge.get("relation") or "depends_on"))
    for node in nodes:
        for dependency in node.get("dependencies") or []:
            add(dependency, node.get("node_id"), "depends_on")
        for previous in node.get("previous_interpretation_nodes") or []:
            add(previous, node.get("node_id"), "interpretation_lineage")
    return edges


def runnable_node_ids(nodes: list[dict[str, Any]]) -> list[str]:
    by_id = {str(node.get("node_id")): node for node in nodes}
    runnable = []
    for node in nodes:
        if node.get("status") != "pending" or node.get("human_approval") in {"required", "rejected"}:
            continue
        dependencies = [by_id.get(str(item)) for item in node.get("dependencies") or []]
        if all(item is not None and item.get("status") == "succeeded" for item in dependencies):
            runnable.append(str(node.get("node_id")))
    return sorted(runnable, key=natural_key)


def edge_class(source: dict[str, Any], target: dict[str, Any], relation: str) -> str:
    if relation == "interpretation_lineage":
        return "lineage"
    if source.get("status") == "succeeded" and target.get("status") == "succeeded":
        return "complete"
    if source.get("status") == "succeeded":
        return "available"
    terminal_blockers = {"failed", "unavailable", "waived", "not_applicable", "skipped", "stale"}
    if source.get("status") in terminal_blockers or target.get("status") in terminal_blockers:
        return "blocked"
    return "planned"


def svg_report(state: dict[str, Any]) -> tuple[str, list[str], list[dict[str, str]]]:
    nodes = list(state.get("execution_graph", {}).get("nodes", []))
    by_id = {str(node.get("node_id")): node for node in nodes}
    warnings: list[str] = []
    if len(by_id) != len(nodes):
        warnings.append("Execution graph contains duplicate or blank Node IDs.")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in nodes:
        grouped[str(node.get("stage") or "unknown")].append(node)
    for values in grouped.values():
        values.sort(key=lambda item: natural_key(str(item.get("node_id") or "")))

    x_by_stage = {stage: 160 + index * 300 for index, stage in enumerate(STAGES)}
    positions: dict[str, tuple[float, float]] = {}
    max_rows = max((len(grouped.get(stage, [])) for stage in STAGES), default=0)
    height = max(560, 215 + max_rows * 92)
    width = 1220
    for stage in STAGES:
        for index, node in enumerate(grouped.get(stage, [])):
            positions[str(node.get("node_id"))] = (x_by_stage[stage], 190 + index * 92)
    unknown_count = sum(len(values) for stage, values in grouped.items() if stage not in STAGES)
    if unknown_count:
        warnings.append(f"Unknown stage Nodes omitted from SVG layout: {unknown_count}")

    edge_shapes = []
    valid_edges: list[dict[str, str]] = []
    for edge in all_edges(state):
        source_id, target_id = edge["source"], edge["target"]
        if source_id not in positions or target_id not in positions:
            warnings.append(f"Edge references an unavailable Node: {source_id} -> {target_id}")
            continue
        valid_edges.append(edge)
        source, target = by_id[source_id], by_id[target_id]
        x1, y1 = positions[source_id]
        x2, y2 = positions[target_id]
        if x1 == x2:
            bend = x1 + 80
            path = f"M {x1 + 31:.1f} {y1:.1f} C {bend:.1f} {y1:.1f}, {bend:.1f} {y2:.1f}, {x2 + 31:.1f} {y2:.1f}"
        else:
            direction = 1 if x2 > x1 else -1
            start_x, end_x = x1 + direction * 31, x2 - direction * 31
            middle = (start_x + end_x) / 2
            path = f"M {start_x:.1f} {y1:.1f} C {middle:.1f} {y1:.1f}, {middle:.1f} {y2:.1f}, {end_x:.1f} {y2:.1f}"
        css_class = edge_class(source, target, edge["relation"])
        title = html.escape(f"{source_id} -> {target_id} ({edge['relation']})")
        edge_shapes.append(f"<path class='edge {css_class}' d='{path}'><title>{title}</title></path>")

    node_shapes = []
    for node_id, (x, y) in positions.items():
        node = by_id[node_id]
        status = str(node.get("status") or "pending")
        fill = STATUS_COLORS.get(status, "#c6c9ca")
        text_color = "#ffffff" if status in {"running", "succeeded", "failed", "stale"} else "#283740"
        capability = str(node.get("capability_id") or "-")
        title_parts = [
            f"Node: {node_id}", f"Capability: {capability}", f"Skill: {node.get('skill_name') or '-'}",
            f"Status: {STATUS_LABELS.get(status, status)}",
        ]
        if node.get("selection_reason"):
            title_parts.append(f"Reason: {node['selection_reason']}")
        approval_ring = f"<circle class='approval-ring' cx='{x}' cy='{y}' r='37'/>" if node.get("human_approval") == "required" else ""
        label = node_id if len(node_id) <= 8 else node_id[:7] + "…"
        node_shapes.append(
            f"<g class='node status-{html.escape(status)}'><title>{html.escape(chr(10).join(title_parts))}</title>"
            f"{approval_ring}<circle cx='{x}' cy='{y}' r='31' fill='{fill}'/>"
            f"<text class='node-id' x='{x}' y='{y + 4}' fill='{text_color}'>{html.escape(label)}</text>"
            f"<text class='capability' x='{x}' y='{y + 49}'>{html.escape(capability)}</text></g>"
        )

    stage_headers = "".join(
        f"<g><rect class='stage-band' x='{x_by_stage[stage] - 112}' y='55' width='224' height='{height - 85}' rx='10'/>"
        f"<text class='stage-title' x='{x_by_stage[stage]}' y='92'>{STAGE_LABELS[stage]}</text>"
        f"<text class='stage-count' x='{x_by_stage[stage]}' y='116'>{len(grouped.get(stage, []))} Nodes</text></g>"
        for stage in STAGES
    )
    css = """
    .stage-band{fill:#f7f6f2;stroke:#dedbd3;stroke-width:1}.stage-title{text-anchor:middle;font:600 16px 'Segoe UI','Yu Gothic UI',sans-serif;fill:#304957}.stage-count{text-anchor:middle;font:12px 'Segoe UI','Yu Gothic UI',sans-serif;fill:#748087}.edge{fill:none;stroke-width:2;marker-end:url(#arrow)}.edge.complete{stroke:#5f7d73}.edge.available{stroke:#668196}.edge.planned{stroke:#aeb4b7;stroke-dasharray:7 6}.edge.blocked{stroke:#95645c;stroke-dasharray:3 6}.edge.lineage{stroke:#806637;stroke-dasharray:2 5}.node circle:not(.approval-ring){stroke:#fff;stroke-width:3;filter:url(#shadow)}.approval-ring{fill:none;stroke:#806637;stroke-width:3;stroke-dasharray:4 3}.node-id{text-anchor:middle;font:700 12px 'Segoe UI','Yu Gothic UI',sans-serif}.capability{text-anchor:middle;font:11px 'Segoe UI','Yu Gothic UI',sans-serif;fill:#5e6a70}
    """
    svg = f"""<svg xmlns='http://www.w3.org/2000/svg' role='img' aria-label='CONDUCTOR execution DAG' viewBox='0 0 {width} {height}' width='{width}' height='{height}'>
<defs><marker id='arrow' viewBox='0 0 10 10' refX='8' refY='5' markerWidth='6' markerHeight='6' orient='auto-start-reverse'><path d='M 0 0 L 10 5 L 0 10 z' fill='context-stroke'/></marker><filter id='shadow' x='-30%' y='-30%' width='160%' height='160%'><feDropShadow dx='0' dy='2' stdDeviation='2' flood-color='#263640' flood-opacity='.18'/></filter></defs>
<style>{css}</style><rect width='100%' height='100%' fill='#ffffff'/>{stage_headers}{''.join(edge_shapes)}{''.join(node_shapes)}</svg>"""
    return svg, warnings, valid_edges


def path_link(path_text: Any, label: str | None = None) -> str:
    if not path_text:
        return "-"
    path = Path(str(path_text))
    try:
        href = path.resolve().as_uri()
    except ValueError:
        return html.escape(str(path))
    return f"<a href='{html.escape(href, quote=True)}'>{html.escape(label or str(path))}</a>"


def artifact_links(node: dict[str, Any]) -> str:
    links = []
    output_dir = Path(str(node.get("output_dir"))) if node.get("output_dir") else None
    for artifact in node.get("artifacts") or []:
        path = Path(str(artifact.get("path") or ""))
        if output_dir is not None and not path.is_absolute():
            path = output_dir / path
        if str(path):
            links.append(path_link(path, path.name))
    if not links and output_dir is not None:
        links.append(path_link(output_dir, "output directory"))
    return "<br>".join(links) or "-"


def html_report(
    state: dict[str, Any], state_path: Path, state_sha256: str, svg: str, warnings: list[str],
    edges: list[dict[str, str]], generated_at: str,
) -> str:
    nodes = list(state.get("execution_graph", {}).get("nodes", []))
    status_counts = Counter(str(node.get("status") or "unknown") for node in nodes)
    stage_counts = Counter(str(node.get("stage") or "unknown") for node in nodes)
    runnable = runnable_node_ids(nodes)
    terminal = sum(status_counts.get(status, 0) for status in ("succeeded", "failed", "unavailable", "waived", "not_applicable", "skipped"))
    cards = [
        ("全Node", len(nodes)), ("完了", status_counts.get("succeeded", 0)),
        ("未実行", status_counts.get("pending", 0)), ("実行中", status_counts.get("running", 0)),
        ("失敗", status_counts.get("failed", 0)), ("実行可能", len(runnable)),
    ]
    card_html = "".join(f"<div class='metric'><span>{html.escape(label)}</span><strong>{value}</strong></div>" for label, value in cards)
    stage_rows = "".join(
        f"<tr><th>{STAGE_LABELS[stage]}</th><td>{stage_counts.get(stage, 0)}</td>"
        + "".join(f"<td>{sum(1 for node in nodes if node.get('stage') == stage and node.get('status') == status)}</td>" for status in STATUS_LABELS)
        + "</tr>" for stage in STAGES
    )
    node_rows = []
    for node in sorted(nodes, key=lambda item: (STAGES.index(item.get("stage")) if item.get("stage") in STAGES else 99, natural_key(str(item.get("node_id") or "")))):
        dependencies = ", ".join(str(value) for value in node.get("dependencies") or []) or "-"
        node_rows.append(
            "<tr>"
            f"<td><b>{html.escape(str(node.get('node_id') or '-'))}</b><br><span class='muted'>{html.escape(str(node.get('capability_id') or '-'))}</span></td>"
            f"<td>{html.escape(STAGE_LABELS.get(str(node.get('stage')), str(node.get('stage') or '-')))}</td>"
            f"<td><span class='status-chip status-{html.escape(str(node.get('status') or 'unknown'))}'>{html.escape(STATUS_LABELS.get(str(node.get('status')), str(node.get('status') or '-')))}</span></td>"
            f"<td>{html.escape(dependencies)}</td><td>{html.escape(str(node.get('human_approval') or '-'))}</td>"
            f"<td>{html.escape(str(node.get('selection_reason') or '-'))}</td><td>{artifact_links(node)}</td></tr>"
        )
    warning_html = "".join(f"<li>{html.escape(item)}</li>" for item in warnings) or "<li>構造上の警告はありません。</li>"
    runnable_html = ", ".join(html.escape(item) for item in runnable) or "なし"
    group_index = (state.get("indices") or {}).get("group") or {}
    round_control = state.get("round_control") or {}
    css = """:root{--ink:#283740;--navy:#304957;--muted:#6d787e;--paper:#f1f0ec;--surface:#fff;--line:#d8d5cd;--green:#5f7d73;--blue:#668196;--brick:#95645c;--ochre:#a48853;--skip:#a29b8f;--pending:#d9dde0}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:14px/1.65 "Yu Gothic UI","Segoe UI",sans-serif}main{max-width:1400px;margin:26px auto;padding:38px 44px 60px;background:var(--surface);box-shadow:0 12px 34px #26364018}h1,h2{color:var(--navy)}h1{margin:4px 0 6px;font-size:32px}h2{margin-top:42px;border-bottom:2px solid var(--navy);padding-bottom:7px}.muted,.meta{color:var(--muted)}.metrics{display:grid;grid-template-columns:repeat(6,minmax(110px,1fr));gap:12px;margin:25px 0}.metric{padding:14px 16px;background:#f7f7f4;border:1px solid var(--line);border-radius:6px}.metric span{display:block;color:var(--muted);font-size:12px}.metric strong{display:block;color:var(--navy);font-size:26px}.dag-wrap{overflow:auto;border:1px solid var(--line);background:#fff;padding:10px}.dag-wrap svg{display:block;max-width:none;height:auto}.legend{display:flex;flex-wrap:wrap;gap:14px;margin:12px 0}.legend span{display:inline-flex;align-items:center;gap:6px}.dot{width:13px;height:13px;border-radius:50%;display:inline-block;border:1px solid #fff;box-shadow:0 0 0 1px #aab0b2}.line{width:28px;border-top:2px solid #5f7d73}.line.planned{border-top-style:dashed;border-color:#aeb4b7}.line.lineage{border-top-style:dotted;border-color:#806637}.summary-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.panel{padding:17px 20px;background:#f7f7f4;border:1px solid var(--line)}table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:8px;border:1px solid var(--line);text-align:left;vertical-align:top}thead th{background:#eceeec}tbody th{background:#f6f6f3}.table-wrap{overflow:auto}.status-chip{display:inline-block;border-radius:3px;padding:2px 7px}.status-succeeded{background:#e5eeea;color:#38584e}.status-running{background:#e5ebef;color:#405f73}.status-failed{background:#f0e5e3;color:#79463e}.status-skipped{background:#eeece8;color:#665f55}.status-stale{background:#f0eadf;color:#725c31}.status-pending{background:#eceeef;color:#59646a}a{color:#405f73}code{word-break:break-all}.warning{border-left:4px solid var(--ochre);background:#f3eee3;padding:12px 18px}@media(max-width:900px){main{margin:0;padding:24px 18px}.metrics{grid-template-columns:repeat(2,1fr)}.summary-grid{grid-template-columns:1fr}}@media print{body{background:#fff}main{box-shadow:none;margin:0;max-width:none}.dag-wrap{overflow:visible}}"""
    return f"""<!doctype html><html lang='ja'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>CONDUCTOR State Report</title><style>{css}</style></head><body><main><header><p class='meta'>Read-only execution snapshot</p><h1>CONDUCTOR State Report</h1><p class='meta'>Project {html.escape(str(state.get('run', {}).get('project') or '-'))} · Run {html.escape(str(state.get('run', {}).get('run_id') or '-'))} · Generated {html.escape(generated_at)}</p></header><div class='metrics'>{card_html}</div><div class='summary-grid'><section class='panel'><b>State</b><p>Source: {path_link(state_path, state_path.name)}<br>SHA-256: <code>{state_sha256}</code><br>State updated_at: {html.escape(str(state.get('updated_at') or '-'))}<br>Terminal: {terminal}/{len(nodes)}</p></section><section class='panel'><b>現在実行可能なNode</b><p>{runnable_html}</p><p>Group: {group_index.get('active_group_count', 0)} active / {group_index.get('deprioritized_group_count', 0)} deprioritized<br>Rounds: {len(round_control.get('rounds') or [])} · Active: {html.escape(str(round_control.get('active_round_id') or 'none'))}</p></section></div><h2>実行DAG</h2><p>円は実行Node、矢印は依存関係です。Interpretation lineageは実行依存ではなく、前回解釈の読み取り専用参照です。</p><div class='legend'><span><i class='dot' style='background:var(--green)'></i>完了</span><span><i class='dot' style='background:var(--blue)'></i>実行中</span><span><i class='dot' style='background:var(--pending)'></i>未実行</span><span><i class='dot' style='background:var(--brick)'></i>失敗</span><span><i class='dot' style='background:var(--skip)'></i>Skip</span><span><i class='dot' style='background:var(--ochre)'></i>Stale</span><span><i class='line'></i>完了Edge</span><span><i class='line planned'></i>未完了Edge</span><span><i class='line lineage'></i>Interpretation lineage</span></div><p><a href='state_dag.svg'>SVGを単独で開く</a></p><div class='dag-wrap'>{svg}</div><h2>段階別進捗</h2><div class='table-wrap'><table><thead><tr><th>段階</th><th>全数</th>{''.join(f'<th>{html.escape(label)}</th>' for label in STATUS_LABELS.values())}</tr></thead><tbody>{stage_rows}</tbody></table></div><h2>Node詳細</h2><div class='table-wrap'><table><thead><tr><th>Node / Capability</th><th>段階</th><th>Status</th><th>依存Node</th><th>Approval</th><th>選択理由</th><th>Artifact</th></tr></thead><tbody>{''.join(node_rows)}</tbody></table></div><h2>検証メモ</h2><div class='warning'><ul>{warning_html}</ul><p>Execution edges: {len(edges)}</p></div></main></body></html>"""


def write_nodes_csv(path: Path, nodes: list[dict[str, Any]]) -> None:
    columns = [
        "node_id", "capability_id", "skill_name", "stage", "phase", "status", "dependencies",
        "human_approval", "request_origin", "requested_at", "selection_reason", "output_dir", "artifacts",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for node in nodes:
            writer.writerow({
                "node_id": node.get("node_id"), "capability_id": node.get("capability_id"),
                "skill_name": node.get("skill_name"), "stage": node.get("stage"), "phase": node.get("phase"),
                "status": node.get("status"), "dependencies": ",".join(str(item) for item in node.get("dependencies") or []),
                "human_approval": node.get("human_approval"), "request_origin": node.get("request_origin"),
                "requested_at": node.get("requested_at"), "selection_reason": node.get("selection_reason"),
                "output_dir": node.get("output_dir"), "artifacts": json.dumps(node.get("artifacts") or [], ensure_ascii=False),
            })


def allocate_output_directory(state_path: Path) -> Path:
    base = state_path.parent / "state"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = base / timestamp
    suffix = 1
    while candidate.exists():
        candidate = base / f"{timestamp}-{suffix:02d}"
        suffix += 1
    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


def main() -> int:
    args = parse_args()
    state_path = Path(args.state).expanduser().resolve()
    if not state_path.is_file():
        raise FileNotFoundError(state_path)
    before_hash = file_hash(state_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    validate_state(state)
    generated_at = utc_now()
    svg, warnings, edges = svg_report(state)
    output_dir = allocate_output_directory(state_path)
    svg_path = output_dir / "state_dag.svg"
    html_path = output_dir / "state_report.html"
    nodes_path = output_dir / "state_nodes.csv"
    summary_path = output_dir / "state_summary.json"
    svg_path.write_text(svg, encoding="utf-8")
    write_nodes_csv(nodes_path, list(state.get("execution_graph", {}).get("nodes", [])))
    html_path.write_text(html_report(state, state_path, before_hash, svg, warnings, edges, generated_at), encoding="utf-8")
    nodes = list(state.get("execution_graph", {}).get("nodes", []))
    summary = {
        "schema_version": "1.0.0", "report_type": "conductor_state_dag", "source_state": str(state_path),
        "source_state_sha256": before_hash, "source_state_updated_at": state.get("updated_at"),
        "project": state.get("run", {}).get("project"), "run_id": state.get("run", {}).get("run_id"),
        "generated_at": generated_at, "node_count": len(nodes), "edge_count": len(edges),
        "status_counts": dict(Counter(str(node.get("status") or "unknown") for node in nodes)),
        "stage_counts": dict(Counter(str(node.get("stage") or "unknown") for node in nodes)),
        "runnable_nodes": runnable_node_ids(nodes), "warnings": warnings,
        "artifacts": ["state_report.html", "state_dag.svg", "state_nodes.csv", "state_summary.json"],
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    after_hash = file_hash(state_path)
    if after_hash != before_hash:
        raise RuntimeError("Source State changed while rendering; discard the report and retry from a stable State")
    print(output_dir)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
