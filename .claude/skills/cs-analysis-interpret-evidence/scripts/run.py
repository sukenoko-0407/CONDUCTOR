from __future__ import annotations

import argparse
import hashlib
import html
import json
import sys
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
CAPABILITY = json.loads((SKILL_DIR / "capability.json").read_text(encoding="utf-8"))
POLICY_VERSION = "1.0.0"


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
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    parser = argparse.ArgumentParser(description="Prepare and render CONDUCTOR v4 evidence for policy-guided Interpretation Agent review.")
    parser.add_argument("--evidence", action="append", default=[], help="Evidence JSON; repeat as needed.")
    parser.add_argument("--evidence-dir", action="append", default=[], help="Directory searched recursively for evidence.json.")
    parser.add_argument("--state", help="Read-only CONDUCTOR state.json used for provenance, coverage, failures, and exploration ledger.")
    parser.add_argument("--catalog", help="Catalog JSON; defaults to the workspace Catalog when available.")
    parser.add_argument("--previous-interpretation", action="append", default=[], help="Previous interpretation JSON; repeat for iterative comparison.")
    parser.add_argument("--stage", choices=["discovery", "validation", "mixed"], default="discovery")
    parser.add_argument("--seed", type=int)
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
    if args.seed is not None and args.seed < 0:
        parser.error("--seed must be >= 0")
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


def load_optional_json(path_text: str | None) -> dict[str, Any] | None:
    return json.loads(Path(path_text).read_text(encoding="utf-8")) if path_text else None


def load_catalog(path_text: str | None) -> dict[str, dict[str, Any]]:
    path = Path(path_text) if path_text else find_workspace() / "catalog" / "catalog.json"
    if not path.exists():
        return {}
    catalog = json.loads(path.read_text(encoding="utf-8"))
    return {item["capability_id"]: item for item in catalog.get("capabilities") or []}


def state_context(state: dict[str, Any] | None) -> dict[str, Any]:
    if state is None:
        return {"available": False, "failures": [], "skips": [], "pending": [], "attempted_analysis_signatures": [], "exploration": None}
    nodes = state.get("execution_graph", {}).get("nodes", [])
    return {
        "available": True,
        "failures": [{"node_id": n["node_id"], "capability_id": n["capability_id"], "reason": n.get("error")} for n in nodes if n.get("status") == "failed"],
        "skips": [{"node_id": n["node_id"], "capability_id": n["capability_id"], "reason": n.get("skip_reason")} for n in nodes if n.get("status") == "skipped"],
        "pending": [{"node_id": n["node_id"], "capability_id": n["capability_id"], "status": n.get("status")} for n in nodes if n.get("status") in {"pending", "running", "stale"}],
        "attempted_analysis_signatures": sorted({n["analysis_signature"] for n in nodes if n.get("analysis_signature")}),
        "exploration": state.get("interpretation_exploration"),
        "wide_shallow_plan": state.get("wide_shallow_plan"),
    }


def source_node_for_evidence(state: dict[str, Any] | None, evidence_id: str) -> dict[str, Any] | None:
    if state is None:
        return None
    graph_node = next((item for item in state.get("evidence_graph", {}).get("nodes", []) if item.get("evidence_id") == evidence_id), None)
    if graph_node is None:
        return None
    return next((item for item in state.get("execution_graph", {}).get("nodes", []) if item.get("node_id") == graph_node.get("source_node_id")), None)


def resolved_artifacts(evidence: dict[str, Any], evidence_path: Path) -> list[str]:
    result = []
    for artifact in evidence.get("artifacts") or []:
        path = Path(str(artifact.get("path") or ""))
        if not path.is_absolute():
            path = evidence_path.parent / path
        result.append(str(path.resolve()))
    return result


def representation_family(identifier: str | None, catalog: dict[str, dict[str, Any]]) -> str | None:
    if not identifier:
        return None
    capability = catalog.get(identifier)
    return str(capability.get("family")) if capability else str(identifier)


def pair_keys(evidence: dict[str, Any]) -> set[str]:
    keys = set()
    for pair in evidence.get("supporting_pairs") or []:
        left = pair.get("compound_id_a") or pair.get("compound_id")
        right = pair.get("compound_id_b") or pair.get("neighbor_id")
        if left is not None and right is not None:
            keys.add("::".join(sorted((str(left), str(right)))))
    return keys


def build_evidence_index(
    evidence_records: list[tuple[Path, dict[str, Any]]],
    catalog: dict[str, dict[str, Any]],
    state: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    items = []
    for path, evidence in evidence_records:
        source_node = source_node_for_evidence(state, evidence["evidence_id"])
        evaluation = evidence.get("evaluation_representation")
        grouping = evidence.get("grouping_representation")
        items.append({
            "evidence_id": evidence["evidence_id"],
            "operator_id": evidence["operator_id"],
            "operator_name": evidence["operator_name"],
            "scope": evidence.get("scope") or {"mode": "global", "sample_count": evidence.get("sample_count", 0)},
            "sample_count": int(evidence.get("sample_count") or 0),
            "evaluation_representation": evaluation,
            "evaluation_family": representation_family(evaluation, catalog),
            "grouping_representation": grouping,
            "grouping_family": representation_family(grouping, catalog),
            "target_group_id": evidence.get("target_group_id"),
            "artifact_paths": resolved_artifacts(evidence, path),
            "evidence_path": str(path.resolve()),
            "result_values": evidence.get("machine_readable_summary") or {},
            "generated_evidence": evidence.get("generated_evidence") or [],
            "warnings": evidence.get("warnings") or [],
            "supporting_pairs": evidence.get("supporting_pairs") or [],
            "source_node_id": source_node.get("node_id") if source_node else None,
            "source_dependencies": source_node.get("dependencies") if source_node else [],
            "analysis_signature": source_node.get("analysis_signature") if source_node else None,
        })
    return items


def build_relations(index: list[dict[str, Any]]) -> list[dict[str, Any]]:
    relations = []
    for number, (left, right) in enumerate(combinations(index, 2), start=1):
        same_operator = left["operator_id"] == right["operator_id"]
        same_evaluation = bool(left.get("evaluation_representation")) and left.get("evaluation_representation") == right.get("evaluation_representation")
        same_grouping = bool(left.get("grouping_representation")) and left.get("grouping_representation") == right.get("grouping_representation")
        same_scope = left.get("scope", {}).get("compound_set_hash") == right.get("scope", {}).get("compound_set_hash")
        same_target = bool(left.get("target_group_id")) and left.get("target_group_id") == right.get("target_group_id")
        shared_pairs = len(pair_keys(left) & pair_keys(right))
        global_local = same_operator and same_evaluation and {left.get("scope", {}).get("mode"), right.get("scope", {}).get("mode")} == {"global", "within-group"}
        if not any((same_operator, same_evaluation, same_grouping, same_scope, same_target, shared_pairs, global_local)):
            continue
        if same_operator and same_evaluation and same_scope:
            relation_type = "duplicates"
        elif global_local:
            relation_type = "localizes"
        else:
            relation_type = "comparison_candidate"
        if same_evaluation or (same_grouping and same_target):
            independence = "low"
        elif left.get("evaluation_family") and left.get("evaluation_family") == right.get("evaluation_family"):
            independence = "medium"
        elif left.get("evaluation_family") and right.get("evaluation_family"):
            independence = "high"
        else:
            independence = "unknown"
        reasons = []
        if same_operator:
            reasons.append("same Operator")
        if same_evaluation:
            reasons.append("same evaluation representation")
        if same_grouping:
            reasons.append("same Grouping representation")
        if same_scope:
            reasons.append("same compound scope")
        if global_local:
            reasons.append("global/local scope contrast")
        if shared_pairs:
            reasons.append(f"{shared_pairs} shared supporting pairs")
        relations.append({
            "relation_id": f"R{number:05d}",
            "evidence_ids": [left["evidence_id"], right["evidence_id"]],
            "relation_type": relation_type,
            "independence": independence,
            "rationale": "; ".join(reasons),
            "status": "candidate",
            "shared_pair_count": shared_pairs,
        })
    return relations


def group_candidates(index: list[dict[str, Any]], dataset_count: int) -> list[dict[str, Any]]:
    candidates: dict[tuple[str, str], dict[str, Any]] = {}
    for evidence in index:
        grouping = str(evidence.get("grouping_representation") or "UNKNOWN")
        for generated in evidence.get("generated_evidence") or []:
            values = generated.get("values") or {}
            group_id = values.get("group_id")
            if group_id is None:
                continue
            key = (grouping, str(group_id))
            item = candidates.setdefault(key, {"candidate_id": f"group:{grouping}:{group_id}", "grouping_representation": grouping, "group_id": str(group_id), "evidence_ids": [], "priority_reasons": [], "cautions": []})
            item["evidence_ids"].append(evidence["evidence_id"])
            if values.get("sample_count") is not None:
                item["sample_count"] = int(values["sample_count"])
            for name in ("mean_tanimoto", "median_tanimoto", "p90_tanimoto", "structural_diversity_score", "odds_ratio", "fisher_pvalue", "property_median", "median_shift_vs_global"):
                if values.get(name) is not None:
                    item[name] = values[name]
    for item in candidates.values():
        count = int(item.get("sample_count") or 0)
        fraction = count / max(1, dataset_count)
        item["sample_fraction"] = fraction
        if fraction > 0.5:
            item["cautions"].append("group exceeds 50% of dataset and is close to a global view")
        elif fraction > 0.3:
            item["cautions"].append("group exceeds 30% of dataset and has reduced locality")
        elif count:
            item["priority_reasons"].append("locally bounded group")
        if count >= 10:
            item["priority_reasons"].append("larger group supports more stable comparison")
        elif count:
            item["cautions"].append("small group requires stability and leave-one-out checks")
        mean_tanimoto = item.get("mean_tanimoto")
        if isinstance(mean_tanimoto, (int, float)):
            item["priority_reasons"].append("structural cohesion is available for human-interpretable prioritization")
    return sorted(candidates.values(), key=lambda item: (-int(item.get("sample_count") or 0), item["candidate_id"]))


def confidence(evidence: dict[str, Any]) -> tuple[str, str]:
    warnings = evidence.get("warnings") or []
    count = int(evidence.get("sample_count") or 0)
    if count >= 30 and not warnings:
        return "medium", "sample数は比較に利用できるが、独立evidenceと反証探索が完了するまで探索的候補として扱う。"
    if count >= 10:
        return "low_to_medium", "sample数またはwarningを考慮し、独立表現、matched control、反証解析を必要とする。"
    return "low", "小Groupまたは少数sampleの観察であり、構造凝集性と一化合物感度を確認する。"


def build_interpretation(
    evidence_items: list[dict[str, Any]],
    evidence_index: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    run_id: str,
    stage: str,
    state_info: dict[str, Any],
    seed: int,
) -> dict[str, Any]:
    findings = []
    hypotheses = []
    next_analysis: list[dict[str, Any]] = []
    review_points = [
        "Operator observationとInterpretationを区別する。",
        "全注目候補について反証、control、または独立replicationを確認する。",
        "依存したDescriptionや共通pairから得た一致を独立支持として重複計上しない。",
        "assay条件混在、測定誤差、Groupのsample割合と構造凝集性を確認する。",
    ]
    for number, evidence in enumerate(evidence_items, start=1):
        evidence_id = str(evidence.get("evidence_id", f"UNKNOWN_{number:04d}"))
        machine = evidence.get("machine_readable_summary") or {}
        summary = evidence.get("human_readable_summary") or f"Evidence {evidence_id}"
        operator_id = str(evidence.get("operator_id") or "")
        if operator_id == "A006":
            representation = evidence.get("evaluation_representation") or "unspecified representation"
            summary = (
                f"{representation}のSALI landscape: scope={(evidence.get('scope') or {}).get('mode', 'global')}, "
                f"metric={machine.get('metric')}, median={machine.get('median_sali')}, p90={machine.get('p90_sali')}, "
                f"p95={machine.get('p95_sali')}, neighbor Spearman={machine.get('neighbor_property_spearman')}。"
                "upper tail、中心値、global/local/between-group差を別々に確認する。"
            )
            implication = "上位pair、Group境界、構造・3D・pharmacophore差を照合し、同じ現象が独立表現でも再現するか確認する。"
            compound_direction = ["Cliff周辺のbridge analogまたは単一変換seriesを検討する。具体的SMILESは生成しない。"]
        else:
            implication = "具体的構造含意は、Group局所性、独立evidence、例外、反証結果を比較した後に人間が確定する。"
            compound_direction = ["候補を識別できる構造変換方向を検討する。具体的SMILESは生成しない。"]
        findings.append({
            "finding_id": f"F{number:04d}",
            "title": str(evidence.get("operator_name", "Operator evidence")),
            "observation": summary,
            "evidence_ids": [evidence_id],
            "result_values": machine,
            "warnings": evidence.get("warnings") or [],
            "status": "discovery",
            "scope": evidence.get("scope") or {},
        })
        level, rationale = confidence(evidence)
        hypotheses.append({
            "hypothesis_id": f"H{number:04d}",
            "title": f"{evidence.get('operator_name', '解析')}から得られた未確定の比較候補",
            "target_group": evidence.get("target_group_id"),
            "observation": summary,
            "supporting_evidence": [evidence_id],
            "contradicting_evidence": [],
            "evidence_independence": "単一evidence由来。evidence relation graphで共有表現、scope、pair、上流nodeを確認する。",
            "alternative_explanations": ["測定誤差またはassay条件差", "sample selection、Group定義、property range、近傍構成による見かけの関係"],
            "scope": evidence.get("applicability_conditions") or [],
            "exceptions": [],
            "confidence": level,
            "confidence_rationale": rationale,
            "proposed_structural_implication": implication,
            "recommended_next_analysis": ["異なるDescription family、Group外、matched controlのいずれかで反証を探索する。"],
            "recommended_next_compounds": compound_direction,
            "human_review_points": ["元artifact、Group size、scope fraction、warningを照合する。"],
            "focus_pairs": (evidence.get("supporting_pairs") or [])[:20],
            "falsification_status": "required",
        })
        next_analysis.append({
            "source_hypothesis_id": f"H{number:04d}",
            "action": "独立表現、Group外、matched control、または反対方向の例外で反証を探索する。",
            "purpose": "falsify",
            "approval_status": "orchestrator_must_determine",
        })
    return {
        "schema_version": "1.0.0",
        "policy_version": POLICY_VERSION,
        "run_id": run_id,
        "interpretation_id": f"{run_id}:I001:{value_hash([item['evidence_id'] for item in evidence_index])[:12]}",
        "evidence_index": evidence_index,
        "evidence_relations": relations,
        "unresolved_contradictions": [],
        "exploration_summary": {
            "stage": stage,
            "seed": seed,
            "attempted_analysis_signatures": state_info["attempted_analysis_signatures"],
            "negative_results_preserved": True,
            "falsification_required": True,
            "evidence_count": len(evidence_index),
            "relation_candidate_count": len(relations),
            "agent_review_required": True,
        },
        "notable_findings": findings,
        "hypotheses": hypotheses,
        "recommended_next_analysis": next_analysis,
        "human_review_points": review_points,
        "created_at": utc_now(),
    }


def markdown_report(value: dict[str, Any]) -> str:
    lines = [
        "# CONDUCTOR v4 Interpretation Report",
        "",
        f"- Run ID: `{value['run_id']}`",
        f"- Policy: `{value['policy_version']}`",
        f"- Stage: `{value['exploration_summary']['stage']}`",
        f"- Generated: `{value['created_at']}`",
        "",
        "## 注目すべき発見",
        "",
    ]
    for finding in value["notable_findings"]:
        lines.extend([f"### {finding['finding_id']}: {finding['title']}", "", finding["observation"], "", f"Evidence: {', '.join(finding['evidence_ids'])}", ""])
    lines.extend(["## Evidence間関係", ""])
    if value["evidence_relations"]:
        for relation in value["evidence_relations"]:
            lines.append(f"- `{relation['relation_id']}` {relation['relation_type']} / independence={relation['independence']}: {', '.join(relation['evidence_ids'])} — {relation['rationale']}")
    else:
        lines.append("- 比較候補なし。")
    lines.extend(["", "## 未解決の矛盾", ""])
    if value["unresolved_contradictions"]:
        lines.extend(f"- {item}" for item in value["unresolved_contradictions"])
    else:
        lines.append("- 未検出またはAgent未評価。")
    lines.extend(["", "## 仮説・検証候補", ""])
    for hypothesis in value["hypotheses"]:
        lines.extend([
            f"### {hypothesis['hypothesis_id']}: {hypothesis['title']}", "",
            f"- 対象: `{hypothesis['target_group'] or 'GLOBAL'}`",
            f"- 観察: {hypothesis['observation']}",
            f"- 支持Evidence: {', '.join(hypothesis['supporting_evidence'])}",
            f"- 矛盾Evidence: {', '.join(hypothesis['contradicting_evidence']) or '未検出／未評価'}",
            f"- 確信度: `{hypothesis['confidence']}`",
            f"- 反証状態: `{hypothesis.get('falsification_status', 'unknown')}`",
            f"- 根拠: {hypothesis['confidence_rationale']}", "", "次解析:", "",
        ])
        lines.extend(f"- {item}" for item in hypothesis["recommended_next_analysis"])
        lines.append("")
    lines.extend(["## 人間による確認事項", ""])
    lines.extend(f"- {item}" for item in value["human_review_points"])
    lines.append("")
    return "\n".join(lines)


def html_report(value: dict[str, Any]) -> str:
    findings = "".join(f"<article><h3>{html.escape(item['finding_id'])}: {html.escape(item['title'])}</h3><p>{html.escape(item['observation'])}</p><p class='meta'>Evidence: {html.escape(', '.join(item['evidence_ids']))}</p></article>" for item in value["notable_findings"])
    relations = "".join(f"<tr><td>{html.escape(item['relation_id'])}</td><td>{html.escape(item['relation_type'])}</td><td>{html.escape(item['independence'])}</td><td>{html.escape(', '.join(item['evidence_ids']))}</td><td>{html.escape(item['rationale'])}</td></tr>" for item in value["evidence_relations"])
    hypotheses = "".join(f"<article><h3>{html.escape(item['hypothesis_id'])}: {html.escape(item['title'])}</h3><dl><dt>対象</dt><dd>{html.escape(str(item['target_group'] or 'GLOBAL'))}</dd><dt>観察</dt><dd>{html.escape(item['observation'])}</dd><dt>確信度</dt><dd><span class='badge'>{html.escape(item['confidence'])}</span> {html.escape(item['confidence_rationale'])}</dd><dt>反証状態</dt><dd>{html.escape(item.get('falsification_status', 'unknown'))}</dd><dt>次解析</dt><dd><ul>{''.join('<li>'+html.escape(x)+'</li>' for x in item['recommended_next_analysis'])}</ul></dd></dl></article>" for item in value["hypotheses"])
    reviews = "".join(f"<li>{html.escape(item)}</li>" for item in value["human_review_points"])
    return f"""<!doctype html><html lang='ja'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>CONDUCTOR v4 Interpretation</title><style>:root{{--ink:#172033;--muted:#667085;--line:#d8dee9;--accent:#3157a4;--paper:#fff}}*{{box-sizing:border-box}}body{{margin:0;background:#f4f6f9;color:var(--ink);font:15px/1.65 system-ui,sans-serif}}main{{max-width:1200px;margin:32px auto;padding:36px;background:var(--paper);box-shadow:0 8px 30px #1e293b1a}}h1{{font-size:30px;margin:0}}h2{{margin-top:42px;border-bottom:2px solid var(--accent);padding-bottom:8px}}article{{border:1px solid var(--line);border-radius:10px;padding:20px;margin:16px 0}}table{{border-collapse:collapse;width:100%;font-size:13px}}th,td{{border:1px solid var(--line);padding:8px;text-align:left;vertical-align:top}}dt{{font-weight:700;margin-top:10px}}dd{{margin-left:0}}.meta{{color:var(--muted)}}.badge{{display:inline-block;background:#e8eefb;color:#23427e;border-radius:999px;padding:2px 10px;font-weight:700}}@media print{{body{{background:#fff}}main{{box-shadow:none;margin:0;max-width:none}}}}</style></head><body><main><header><h1>CONDUCTOR v4 Interpretation Report</h1><p class='meta'>Run {html.escape(value['run_id'])} · Policy {html.escape(value['policy_version'])} · {html.escape(value['created_at'])}</p></header><h2>注目すべき発見</h2>{findings}<h2>Evidence間関係</h2><table><thead><tr><th>ID</th><th>関係</th><th>独立性</th><th>Evidence</th><th>根拠</th></tr></thead><tbody>{relations}</tbody></table><h2>仮説・検証候補</h2>{hypotheses}<h2>人間による確認事項</h2><ul>{reviews}</ul></main></body></html>"""


def run() -> int:
    started_at = utc_now()
    args = parse_args()
    paths = evidence_paths(args)
    records = [(path, json.loads(path.read_text(encoding="utf-8"))) for path in paths]
    for _, evidence in records:
        validate(evidence, "evidence.schema.json")
    evidence_items = [item for _, item in records]
    run_ids = {str(item.get("run_id")) for item in evidence_items if item.get("run_id")}
    if len(run_ids) > 1:
        raise ValueError(f"Evidence from multiple runs cannot be mixed: {sorted(run_ids)}")
    if args.run_id and run_ids and args.run_id not in run_ids:
        raise ValueError(f"Requested run_id does not match evidence run_id: {sorted(run_ids)}")
    run_id = args.run_id or (next(iter(run_ids)) if len(run_ids) == 1 else run_id_now())
    state = load_optional_json(args.state)
    if state and state.get("run", {}).get("run_id") != run_id:
        raise ValueError("State run_id does not match Interpretation run_id")
    catalog = load_catalog(args.catalog)
    index = build_evidence_index(records, catalog, state)
    relations = build_relations(index)
    state_info = state_context(state)
    configured_seed = ((state_info.get("exploration") or {}).get("budget") or {}).get("seed")
    seed = args.seed if args.seed is not None else (configured_seed if configured_seed is not None else int(value_hash(run_id)[:8], 16))
    interpretation = build_interpretation(evidence_items, index, relations, run_id, args.stage, state_info, seed)
    validate(interpretation, "interpretation.schema.json")
    previous = [json.loads(Path(path).read_text(encoding="utf-8")) for path in args.previous_interpretation]
    dataset_count = int((state or {}).get("run", {}).get("row_count") or max((item["sample_count"] for item in index), default=0))
    context = {
        "schema_version": "1.0.0",
        "policy_version": POLICY_VERSION,
        "run_id": run_id,
        "seed": seed,
        "state_context": state_info,
        "evidence_index": index,
        "evidence_relations": relations,
        "group_scope_candidates": group_candidates(index, dataset_count),
        "previous_interpretations": previous,
        "agent_requirements": {
            "read_only_terminal": True,
            "preserve_multiple_discoveries": True,
            "falsification_for_every_discovery": True,
            "never_repeat_analysis_signature": True,
            "orchestrator_decides_execution_cost_and_approval": True,
        },
        "created_at": utc_now(),
    }
    if args.output_dir:
        outdir = Path(args.output_dir)
    elif args.conductor:
        outdir = find_workspace() / "results" / "CONDUCTOR" / args.project / run_id / "interpretation" / CAPABILITY["skill_name"] / str(args.node_id).replace(":", "-")
    else:
        outdir = find_workspace() / "results" / "interpretation" / "standalone" / CAPABILITY["skill_name"] / run_id
    if outdir.exists() and any(outdir.iterdir()) and not args.overwrite:
        raise FileExistsError(f"Output directory is not empty; use --overwrite: {outdir}")
    outdir.mkdir(parents=True, exist_ok=True)
    targets = [outdir / "interpretation.json", outdir / "interpretation.md", outdir / "interpretation.html", outdir / "interpretation_context.json"]
    write_json(targets[0], interpretation)
    targets[1].write_text(markdown_report(interpretation), encoding="utf-8")
    targets[2].write_text(html_report(interpretation), encoding="utf-8")
    write_json(targets[3], context)
    if args.conductor:
        config = vars(args)
        input_components = [file_hash(path) for path in paths]
        if args.state:
            input_components.append(file_hash(Path(args.state)))
        event = {
            "schema_version": "1.0.0", "project": args.project, "run_id": run_id, "node_id": args.node_id,
            "capability_id": CAPABILITY["capability_id"], "skill_name": CAPABILITY["skill_name"], "status": "succeeded",
            "input_hash": value_hash(input_components), "config_hash": value_hash(config), "configuration": config,
            "artifacts": [{"type": "interpretation_context" if path.name.endswith("context.json") else "interpretation", "path": path.name, "sha256": file_hash(path)} for path in targets],
            "warnings": [], "started_at": started_at, "finished_at": utc_now(),
        }
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
