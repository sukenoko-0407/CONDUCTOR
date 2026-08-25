from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


COLORS = {"pending": "#d8d9d6", "running": "#bd9656", "succeeded": "#557a70", "failed": "#a65f58", "cancelled": "#7b7b78"}
KINDS = ("description", "clustering", "analysis", "interpretation")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def svg_dag(nodes: list[dict[str, Any]]) -> str:
    by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in nodes:
        by_kind[node["kind"]].append(node)
    for values in by_kind.values():
        values.sort(key=lambda item: item["node_id"])
    positions: dict[str, tuple[int, int]] = {}
    x_step, y_step, margin = 260, 58, 70
    for column, kind in enumerate(KINDS):
        for row, node in enumerate(by_kind.get(kind, [])):
            positions[node["node_id"]] = (margin + column * x_step, 100 + row * y_step)
    height = max(280, 170 + max((len(by_kind.get(kind, [])) for kind in KINDS), default=1) * y_step)
    width = margin * 2 + (len(KINDS) - 1) * x_step + 100
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="CONDUCTOR DAG">', '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#8b8d8d"/></marker></defs>', '<rect width="100%" height="100%" fill="#f7f5f0"/>']
    for column, kind in enumerate(KINDS):
        parts.append(f'<text x="{margin + column*x_step}" y="40" text-anchor="middle" font-family="sans-serif" font-size="15" fill="#26343a">{html.escape(kind.title())}</text>')
    for node in nodes:
        if node["node_id"] not in positions:
            continue
        x2, y2 = positions[node["node_id"]]
        for source in node.get("input_nodes", []):
            if source in positions:
                x1, y1 = positions[source]
                parts.append(f'<path d="M{x1+18},{y1} C{x1+80},{y1} {x2-80},{y2} {x2-18},{y2}" fill="none" stroke="#a4a5a2" stroke-width="1.5" marker-end="url(#arrow)"/>')
    for node in nodes:
        if node["node_id"] not in positions:
            continue
        x, y = positions[node["node_id"]]
        color = COLORS.get(node["status"], "#999")
        parts.append(f'<circle cx="{x}" cy="{y}" r="17" fill="{color}" stroke="#2e3b40" stroke-width="2"><title>{html.escape(node["node_id"] + " " + node["capability_id"] + " " + node["status"])}</title></circle>')
        parts.append(f'<text x="{x+25}" y="{y+5}" font-family="monospace" font-size="11" fill="#26343a">{html.escape(node["node_id"])}</text>')
    parts.append("</svg>")
    return "".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a read-only CONDUCTOR 0.1.6/0.1.7 DAG report")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--explicit-request", action="store_true")
    args = parser.parse_args()
    if not args.explicit_request:
        parser.error("--explicit-request is required")
    root = Path(args.run_root).expanduser().resolve()
    control_path = root / "conductor_control.json"
    dag_path = root / "runtime" / "dag_snapshot.json"
    if not control_path.is_file() or not dag_path.is_file():
        raise FileNotFoundError("conductor_control.json or runtime/dag_snapshot.json is missing")
    before = {"control": digest(control_path), "dag": digest(dag_path)}
    control, snapshot = load(control_path), load(dag_path)
    nodes = snapshot.get("nodes", [])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = root / "state" / stamp
    output.mkdir(parents=True, exist_ok=False)
    svg = svg_dag(nodes)
    atomic(output / "state_dag.svg", svg)
    with (output / "state_nodes.csv").open("w", encoding="utf-8", newline="") as handle:
        fields = ["node_id", "kind", "capability_id", "scope", "status", "created_in_round", "output_ref", "input_nodes"]
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
        for node in nodes:
            writer.writerow({**{key: node.get(key) for key in fields}, "input_nodes": ";".join(node.get("input_nodes", []))})
    summary = {"schema_version": "1.0.0", "generated_at": datetime.now(timezone.utc).isoformat(), "run_root": str(root), "source_hashes": before, "active_round_id": control.get("active_round_id"), "round_state": control.get("round_state"), "required_action": control.get("required_action"), "counts": dict(Counter(node["status"] for node in nodes)), "kind_counts": dict(Counter(node["kind"] for node in nodes)), "node_count": len(nodes)}
    atomic(output / "state_summary.json", json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    legend = " ".join(f'<span><i style="background:{color}"></i>{name}</span>' for name, color in COLORS.items())
    page = f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><title>CONDUCTOR State</title><style>body{{font-family:system-ui,sans-serif;background:#eceae5;color:#243238;margin:0}}main{{max-width:1500px;margin:auto;padding:30px}}section{{background:#fffdf8;border:1px solid #d5d1c8;border-radius:10px;padding:20px;margin:16px 0}}.facts{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}}.fact{{border-left:4px solid #557a70;padding:8px 12px;background:#f3f1ec}}.legend span{{margin-right:18px}}.legend i{{display:inline-block;width:12px;height:12px;border-radius:50%;margin-right:5px}}object{{width:100%;min-height:700px}}code{{font-size:.9em}}</style></head><body><main><h1>CONDUCTOR State Report</h1><section class="facts"><div class="fact">Round<br><b>{html.escape(str(control.get("active_round_id") or "none"))}</b></div><div class="fact">State<br><b>{html.escape(str(control.get("round_state")))}</b></div><div class="fact">Required action<br><b>{html.escape(str((control.get("required_action") or {{}}).get("code")))}</b></div><div class="fact">Nodes<br><b>{len(nodes)}</b></div></section><section class="legend">{legend}</section><section><object data="state_dag.svg" type="image/svg+xml"></object></section><section><h2>Counts</h2><pre>{html.escape(json.dumps(summary["counts"], ensure_ascii=False, indent=2))}</pre><p>詳細は <code>state_nodes.csv</code> を参照してください。</p></section></main></body></html>'''
    atomic(output / "state_report.html", page)
    after = {"control": digest(control_path), "dag": digest(dag_path)}
    if before != after:
        raise RuntimeError("Runtime files changed while rendering; report is not trustworthy")
    print(json.dumps({"output_dir": str(output), "state_report": str(output / "state_report.html")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
