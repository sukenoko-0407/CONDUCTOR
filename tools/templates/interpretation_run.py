from __future__ import annotations

import argparse
import hashlib
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
CAPABILITY = json.loads((SKILL_DIR / "capability.json").read_text(encoding="utf-8"))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_id_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def find_workspace() -> Path:
    for candidate in [Path.cwd(), *Path.cwd().parents, SKILL_DIR, *SKILL_DIR.parents]:
        if (candidate / ".claude").exists() and (candidate / "catalog").exists():
            return candidate
    return Path.cwd()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def file_hash(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest


def value_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def validate(value: dict[str, Any], schema_name: str) -> None:
    try:
        import jsonschema
    except ImportError as exc:
        raise RuntimeError("jsonschema is required") from exc
    schema = json.loads((SKILL_DIR / "schemas" / schema_name).read_text(encoding="utf-8"))
    jsonschema.validate(value, schema)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Integrate CONDUCTOR v4 evidence.")
    parser.add_argument("--evidence", action="append", default=[], help="Evidence JSON; repeat as needed.")
    parser.add_argument("--evidence-dir", action="append", default=[], help="Directory searched recursively for evidence.json.")
    parser.add_argument("--run-id")
    parser.add_argument("--project")
    parser.add_argument("--output-dir")
    parser.add_argument("--node-id")
    parser.add_argument("--conductor", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.conductor:
        missing = [name for name in ("project", "run_id", "node_id") if not getattr(args, name)]
        if missing:
            parser.error("--conductor requires --project, --run-id, and --node-id")
    elif args.project or args.node_id:
        parser.error("--project and --node-id are valid only with --conductor")
    return args


def evidence_paths(args: argparse.Namespace) -> list[Path]:
    paths = [Path(value) for value in args.evidence]
    for directory in args.evidence_dir:
        paths.extend(sorted(Path(directory).rglob("evidence.json")))
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved not in seen:
            unique.append(path)
            seen.add(resolved)
    if not unique:
        raise ValueError("Provide at least one --evidence or --evidence-dir")
    return unique


def confidence(evidence: dict[str, Any]) -> tuple[str, str]:
    warnings = evidence.get("warnings") or []
    count = int(evidence.get("sample_count") or 0)
    if count >= 30 and not warnings:
        return "medium", "十分なsample数があるが、単一Operatorのため仮説確定には独立evidenceが必要。"
    if count >= 10:
        return "low_to_medium", "sample数または警告を考慮し、追加の独立evidenceが必要。"
    return "low", "sample数が少ないため探索的観察として扱う。"


def build_interpretation(evidence_items: list[dict[str, Any]], run_id: str) -> dict[str, Any]:
    findings = []
    hypotheses = []
    next_analysis: list[dict[str, Any]] = []
    review_points = ["Operator出力の観察と仮説を区別して確認する。", "assay条件混在、測定誤差、適用範囲を人間が確認する。"]
    for index, evidence in enumerate(evidence_items, start=1):
        evidence_id = str(evidence.get("evidence_id", f"UNKNOWN_{index:04d}"))
        summary = evidence.get("human_readable_summary") or f"Evidence {evidence_id}"
        machine = evidence.get("machine_readable_summary") or {}
        findings.append({"finding_id": f"F{index:04d}", "title": str(evidence.get("operator_name", "Operator evidence")), "observation": summary, "evidence_ids": [evidence_id], "result_values": machine, "warnings": evidence.get("warnings") or []})
        level, rationale = confidence(evidence)
        target = evidence.get("target_group_id")
        hypotheses.append({
            "hypothesis_id": f"H{index:04d}",
            "title": f"{evidence.get('operator_name', '解析')}から得られた検証候補",
            "target_group": target,
            "observation": summary,
            "supporting_evidence": [evidence_id],
            "contradicting_evidence": [],
            "evidence_independence": "このdraftでは単一evidence由来。共通表現を使う他evidenceとの依存性を追加確認する。",
            "alternative_explanations": ["測定誤差またはassay条件差", "sample selectionまたはgroup定義による見かけの関係"],
            "scope": evidence.get("applicability_conditions") or [],
            "exceptions": [],
            "confidence": level,
            "confidence_rationale": rationale,
            "proposed_structural_implication": "具体的構造含意は、独立evidenceと例外確認後に人間が確定する。",
            "recommended_next_analysis": ["異なるrepresentation familyによる再評価", "矛盾evidenceと例外の探索"],
            "recommended_next_compounds": ["仮説を識別できる構造変換方向を検討する。具体的SMILESは生成しない。"],
            "human_review_points": ["観察値と元artifactを照合する。", "化学的妥当性と合成可能性を評価する。"]
        })
        next_analysis.append({"source_hypothesis_id": f"H{index:04d}", "action": "独立した表現またはOperatorで支持・反証を確認する。", "requires_human_approval": False})
    return {"schema_version": "1.0.0", "run_id": run_id, "interpretation_id": f"{run_id}:I001:0001", "notable_findings": findings, "hypotheses": hypotheses, "recommended_next_analysis": next_analysis, "human_review_points": review_points, "created_at": utc_now()}


def markdown_report(value: dict[str, Any]) -> str:
    lines = ["# CONDUCTOR v4 Interpretation Report", "", f"- Run ID: `{value['run_id']}`", f"- Generated: `{value['created_at']}`", "", "## 注目すべき発見", ""]
    for finding in value["notable_findings"]:
        lines.extend([f"### {finding['finding_id']}: {finding['title']}", "", finding["observation"], "", f"Evidence: {', '.join(finding['evidence_ids'])}", ""])
    lines.extend(["## 仮説候補", ""])
    for hypothesis in value["hypotheses"]:
        lines.extend([f"### {hypothesis['hypothesis_id']}: {hypothesis['title']}", "", f"- 対象: `{hypothesis['target_group'] or 'GLOBAL'}`", f"- 観察: {hypothesis['observation']}", f"- 支持Evidence: {', '.join(hypothesis['supporting_evidence'])}", f"- 矛盾Evidence: {', '.join(hypothesis['contradicting_evidence']) or '未検出／未評価'}", f"- 確信度: `{hypothesis['confidence']}`", f"- 根拠: {hypothesis['confidence_rationale']}", f"- 適用範囲: {', '.join(hypothesis['scope']) or '未確定'}", "", "次解析:", ""])
        lines.extend(f"- {item}" for item in hypothesis["recommended_next_analysis"])
        lines.extend(["", "構造設計方向:", ""])
        lines.extend(f"- {item}" for item in hypothesis["recommended_next_compounds"])
        lines.append("")
    lines.extend(["## 人間による確認事項", ""])
    lines.extend(f"- {item}" for item in value["human_review_points"])
    lines.append("")
    return "\n".join(lines)


def html_report(value: dict[str, Any]) -> str:
    findings = "".join(f"<article><h3>{html.escape(item['finding_id'])}: {html.escape(item['title'])}</h3><p>{html.escape(item['observation'])}</p><p class='meta'>Evidence: {html.escape(', '.join(item['evidence_ids']))}</p></article>" for item in value["notable_findings"])
    hypotheses = "".join(f"<article><h3>{html.escape(item['hypothesis_id'])}: {html.escape(item['title'])}</h3><dl><dt>対象</dt><dd>{html.escape(str(item['target_group'] or 'GLOBAL'))}</dd><dt>観察</dt><dd>{html.escape(item['observation'])}</dd><dt>確信度</dt><dd><span class='badge'>{html.escape(item['confidence'])}</span> {html.escape(item['confidence_rationale'])}</dd><dt>次解析</dt><dd><ul>{''.join('<li>'+html.escape(x)+'</li>' for x in item['recommended_next_analysis'])}</ul></dd><dt>構造設計方向</dt><dd><ul>{''.join('<li>'+html.escape(x)+'</li>' for x in item['recommended_next_compounds'])}</ul></dd></dl></article>" for item in value["hypotheses"])
    reviews = "".join(f"<li>{html.escape(item)}</li>" for item in value["human_review_points"])
    return f"""<!doctype html><html lang='ja'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>CONDUCTOR v4 Interpretation</title><style>:root{{--ink:#172033;--muted:#667085;--line:#d8dee9;--accent:#3157a4;--paper:#fff}}*{{box-sizing:border-box}}body{{margin:0;background:#f4f6f9;color:var(--ink);font:15px/1.65 system-ui,sans-serif}}main{{max-width:1080px;margin:32px auto;padding:36px;background:var(--paper);box-shadow:0 8px 30px #1e293b1a}}h1{{font-size:30px;margin:0}}h2{{margin-top:42px;border-bottom:2px solid var(--accent);padding-bottom:8px}}article{{border:1px solid var(--line);border-radius:10px;padding:20px;margin:16px 0}}dt{{font-weight:700;margin-top:10px}}dd{{margin-left:0}}.meta{{color:var(--muted)}}.badge{{display:inline-block;background:#e8eefb;color:#23427e;border-radius:999px;padding:2px 10px;font-weight:700}}@media print{{body{{background:#fff}}main{{box-shadow:none;margin:0;max-width:none}}}}</style></head><body><main><header><h1>CONDUCTOR v4 Interpretation Report</h1><p class='meta'>Run {html.escape(value['run_id'])} · {html.escape(value['created_at'])}</p></header><h2>注目すべき発見</h2>{findings}<h2>仮説候補</h2>{hypotheses}<h2>人間による確認事項</h2><ul>{reviews}</ul></main></body></html>"""


def run() -> int:
    started_at = utc_now()
    args = parse_args()
    paths = evidence_paths(args)
    evidence_items = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    for evidence in evidence_items:
        validate(evidence, "evidence.schema.json")
    run_ids = {str(item.get("run_id")) for item in evidence_items if item.get("run_id")}
    if len(run_ids) > 1:
        raise ValueError(f"Evidence from multiple runs cannot be mixed: {sorted(run_ids)}")
    if args.run_id and run_ids and args.run_id not in run_ids:
        raise ValueError(f"Requested run_id does not match evidence run_id: {sorted(run_ids)}")
    run_id = args.run_id or (next(iter(run_ids)) if len(run_ids) == 1 else run_id_now())
    if args.output_dir:
        outdir = Path(args.output_dir)
    elif args.conductor:
        outdir = find_workspace() / "results" / "CONDUCTOR" / args.project / run_id / "interpretation" / CAPABILITY["skill_name"] / str(args.node_id).replace(":", "-")
    else:
        outdir = find_workspace() / "results" / "interpretation" / "standalone" / CAPABILITY["skill_name"] / run_id
    if outdir.exists() and any(outdir.iterdir()) and not args.overwrite:
        raise FileExistsError(f"Output directory is not empty; use --overwrite: {outdir}")
    interpretation = build_interpretation(evidence_items, run_id)
    validate(interpretation, "interpretation.schema.json")
    outdir.mkdir(parents=True, exist_ok=True)
    targets = [outdir / "interpretation.json", outdir / "interpretation.md", outdir / "interpretation.html"]
    write_json(targets[0], interpretation)
    targets[1].write_text(markdown_report(interpretation), encoding="utf-8")
    targets[2].write_text(html_report(interpretation), encoding="utf-8")
    if args.conductor:
        config = vars(args)
        event = {"schema_version": "1.0.0", "project": args.project, "run_id": run_id, "node_id": args.node_id, "capability_id": CAPABILITY["capability_id"], "skill_name": CAPABILITY["skill_name"], "status": "succeeded", "input_hash": value_hash([file_hash(path) for path in paths]), "config_hash": value_hash(config), "configuration": config, "artifacts": [{"type": "interpretation", "path": path.name, "sha256": file_hash(path)} for path in targets], "warnings": [], "started_at": started_at, "finished_at": utc_now()}
        validate(event, "execution_event.schema.json")
        write_json(outdir / "execution_event.json", event)
    print(outdir)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
