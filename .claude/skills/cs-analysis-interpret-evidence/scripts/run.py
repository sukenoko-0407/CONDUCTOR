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
SCHEMA_VERSION = "1.1.0"
POLICY_VERSION = "1.1.0"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_id_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def find_workspace() -> Path:
    skill_candidates = [SKILL_DIR, *SKILL_DIR.parents]
    cwd_candidates = [Path.cwd(), *Path.cwd().parents]

    # The nearest Project containing this installed Skill is authoritative.
    # This also preserves standalone general-mode use without CONDUCTOR_modules.
    for candidate in skill_candidates:
        installed_skill = candidate / ".claude" / "skills" / SKILL_DIR.name
        if (installed_skill / "capability.json").is_file():
            return candidate

    # Fall back to the caller Project only for non-standard script placement.
    for candidate in cwd_candidates:
        if (candidate / ".claude" / "skills").is_dir() and (
            candidate / "CONDUCTOR_modules" / "catalog" / "catalog.json"
        ).is_file():
            return candidate

    for candidate in cwd_candidates:
        if (candidate / ".claude" / "skills").is_dir():
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
        if not args.state:
            parser.error("--conductor Interpretation requires --state")
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


def default_catalog_path() -> Path:
    workspace = find_workspace()
    packaged = workspace / "CONDUCTOR_modules" / "catalog" / "catalog.json"
    legacy = workspace / "catalog" / "catalog.json"
    return packaged if packaged.exists() else legacy


def load_catalog(path_text: str | None) -> dict[str, dict[str, Any]]:
    path = Path(path_text) if path_text else default_catalog_path()
    if not path.exists():
        return {}
    catalog = json.loads(path.read_text(encoding="utf-8"))
    return {item["capability_id"]: item for item in catalog.get("capabilities") or []}


def state_context(state: dict[str, Any] | None) -> dict[str, Any]:
    if state is None:
        return {"available": False, "failures": [], "skips": [], "pending": [], "attempted_analysis_signatures": [], "exploration": None, "group_index": None}
    nodes = state.get("execution_graph", {}).get("nodes", [])
    return {
        "available": True,
        "failures": [{"node_id": n["node_id"], "capability_id": n["capability_id"], "reason": n.get("error")} for n in nodes if n.get("status") == "failed"],
        "skips": [{"node_id": n["node_id"], "capability_id": n["capability_id"], "reason": n.get("skip_reason")} for n in nodes if n.get("status") == "skipped"],
        "pending": [{"node_id": n["node_id"], "capability_id": n["capability_id"], "status": n.get("status")} for n in nodes if n.get("status") in {"pending", "running", "stale"}],
        "attempted_analysis_signatures": sorted({n["analysis_signature"] for n in nodes if n.get("analysis_signature")}),
        "exploration": state.get("interpretation_exploration"),
        "group_index": state.get("group_index"),
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
        same_signature = bool(left.get("analysis_signature")) and left.get("analysis_signature") == right.get("analysis_signature")
        shared_dependencies = sorted(set(left.get("source_dependencies") or []) & set(right.get("source_dependencies") or []))
        shared_pairs = len(pair_keys(left) & pair_keys(right))
        global_local = same_operator and same_evaluation and {left.get("scope", {}).get("mode"), right.get("scope", {}).get("mode")} == {"global", "within-group"}
        if not any((same_operator, same_evaluation, same_grouping, same_scope, same_target, shared_pairs, global_local)):
            continue
        if same_signature:
            relation_type = "duplicates"
        else:
            relation_type = "comparison_candidate"
        if same_evaluation or (same_grouping and same_target) or shared_dependencies:
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
        if same_target:
            reasons.append("same target Group")
        if global_local:
            reasons.append("global/local scope contrast")
        if shared_pairs:
            reasons.append(f"{shared_pairs} shared supporting pairs")
        if same_signature:
            reasons.append("same analysis signature")
        elif same_operator and same_evaluation and same_scope:
            reasons.append("different analysis signatures or parameterizations")
        if shared_dependencies:
            reasons.append(f"shared upstream nodes: {', '.join(shared_dependencies)}")
        relations.append({
            "relation_id": f"R{number:05d}",
            "evidence_ids": [left["evidence_id"], right["evidence_id"]],
            "relation_type": relation_type,
            "independence": independence,
            "rationale": "; ".join(reasons),
            "status": "candidate",
            "shared_pair_count": shared_pairs,
            "candidate_relation": "global_local_contrast" if global_local else ("parameter_contrast" if same_operator and same_evaluation and same_scope else "cross_evidence_comparison"),
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


STATUS_LABELS = {
    "discovery": "探索的発見",
    "validated": "再現・支持あり",
    "refuted": "反証あり",
    "inconclusive": "判定保留",
    "negative": "明瞭な傾向なし",
}
CONTRADICTION_LABELS = {
    "not_assessed": "未評価",
    "none_found": "評価済み・明瞭な矛盾なし",
    "found": "矛盾または反対Evidenceあり",
}
DRAFT_MARKERS = ("機械下書き", "agentによる比較評価待ち", "agentによる意味解釈待ち", "意味解釈前")


def format_number(value: Any, digits: int = 3) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        if value != value:
            return "NaN"
        if value == 0:
            return "0"
        if abs(value) >= 10000 or abs(value) < 0.001:
            return f"{value:.{digits}g}"
        return f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return str(value)


def analysis_context_for(evidence: dict[str, Any], indexed: dict[str, Any]) -> dict[str, Any]:
    machine = evidence.get("machine_readable_summary") or {}
    scope = evidence.get("scope") or indexed.get("scope") or {}
    return {
        "operator_id": str(evidence.get("operator_id") or indexed.get("operator_id") or ""),
        "operator_name": str(evidence.get("operator_name") or indexed.get("operator_name") or ""),
        "evaluation_representation": evidence.get("evaluation_representation"),
        "evaluation_family": indexed.get("evaluation_family"),
        "grouping_representation": evidence.get("grouping_representation"),
        "grouping_family": indexed.get("grouping_family"),
        "scope_mode": scope.get("mode", "global"),
        "target_group_id": scope.get("target_group_id") or evidence.get("target_group_id"),
        "comparison_group_id": scope.get("comparison_group_id"),
        "sample_count": int(scope.get("sample_count") or evidence.get("sample_count") or 0),
        "sample_fraction": scope.get("sample_fraction"),
        "metric": machine.get("metric"),
    }


def analysis_context_text(context: dict[str, Any]) -> str:
    operator = str(context.get("operator_name") or context.get("operator_id") or "unknown")
    if context.get("operator_id"):
        operator += f" ({context['operator_id']})"
    parts = [f"Operator={operator}"]
    if context.get("evaluation_representation"):
        parts.append(f"Description={context['evaluation_representation']}")
    if context.get("grouping_representation"):
        parts.append(f"Grouping={context['grouping_representation']}")
    scope = str(context.get("scope_mode") or "global")
    if context.get("target_group_id"):
        scope += f":{context['target_group_id']}"
    if context.get("comparison_group_id"):
        scope += f" vs {context['comparison_group_id']}"
    parts.extend([f"Scope={scope}", f"N={format_number(context.get('sample_count'))}"])
    if context.get("sample_fraction") is not None:
        parts.append(f"全体比={format_number(100 * float(context['sample_fraction']), 1)}%")
    if context.get("metric"):
        parts.append(f"Metric={context['metric']}")
    return " / ".join(parts)


def is_draft_text(value: Any) -> bool:
    lowered = str(value or "").strip().lower()
    return any(marker in lowered for marker in DRAFT_MARKERS)


def validate_human_report(value: dict[str, Any], allow_draft: bool = False) -> None:
    if value.get("report_status") == "draft":
        if allow_draft:
            return
        raise ValueError("Interpretation is still a machine draft; the dedicated Interpretation Agent must complete it before final rendering")
    errors: list[str] = []
    if value.get("report_status") != "agent_interpreted":
        errors.append("report_status must be agent_interpreted")
    review = value.get("agent_review") or {}
    if review.get("completed") is not True or not review.get("reviewed_at"):
        errors.append("agent_review must record completed=true and reviewed_at")
    summary = value.get("report_summary") or {}
    if not summary.get("key_messages"):
        errors.append("report_summary.key_messages must contain a conclusion")
    for name in ("analysis_objective", "dataset_scope", "executive_summary", "coverage_summary"):
        if not str(summary.get(name) or "").strip() or is_draft_text(summary.get(name)):
            errors.append(f"report_summary.{name} is missing or still a draft")
    if (value.get("contradiction_assessment") or {}).get("status") == "not_assessed":
        errors.append("contradiction_assessment must distinguish none_found from found")
    for finding in value.get("notable_findings") or []:
        operator_name = str((finding.get("analysis_context") or {}).get("operator_name") or "").strip().lower()
        if str(finding.get("title") or "").strip().lower() == operator_name:
            errors.append(f"{finding.get('finding_id')}: title must state a result")
        for name in ("scientific_question", "observation", "interpretation", "why_notable"):
            field_text = str(finding.get(name) or "").strip()
            if not field_text or is_draft_text(field_text):
                errors.append(f"{finding.get('finding_id')}: {name} is missing or still a draft")
        if str(finding.get("observation") or "").strip() == str(finding.get("interpretation") or "").strip():
            errors.append(f"{finding.get('finding_id')}: observation and interpretation must differ")
    for hypothesis in value.get("hypotheses") or []:
        for name in ("title", "scientific_question", "claim", "interpretation", "why_notable"):
            field_text = str(hypothesis.get(name) or "").strip()
            if not field_text or is_draft_text(field_text):
                errors.append(f"{hypothesis.get('hypothesis_id')}: {name} is missing or still a draft")
    if errors:
        raise ValueError("Human Interpretation quality gate failed:\n- " + "\n- ".join(errors))


def build_interpretation(
    evidence_items: list[dict[str, Any]],
    evidence_index: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    run_id: str,
    interpretation_id: str,
    stage: str,
    state_info: dict[str, Any],
    seed: int,
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    for number, (evidence, indexed) in enumerate(zip(evidence_items, evidence_index), start=1):
        evidence_id = str(evidence.get("evidence_id", f"UNKNOWN_{number:04d}"))
        machine = evidence.get("machine_readable_summary") or {}
        observation = evidence.get("human_readable_summary") or f"Evidence {evidence_id}"
        context = analysis_context_for(evidence, indexed)
        if str(evidence.get("operator_id") or "") == "A006":
            representation = evidence.get("evaluation_representation") or "unspecified representation"
            observation = (
                f"{representation}空間の{context['scope_mode']}解析では、median SALI={format_number(machine.get('median_sali'))}、"
                f"p95 SALI={format_number(machine.get('p95_sali'))}、近傍property Spearman={format_number(machine.get('neighbor_property_spearman'))}"
                f"（N={context['sample_count']}、metric={machine.get('metric') or 'unspecified'}）。"
            )
            question = f"{representation}で定義した近傍空間の活性landscapeは、対象scopeで平滑か、Cliff的か。"
        else:
            question = f"{evidence.get('operator_name', 'このOperator')}は対象scopeにどのような傾向、差、または例外を示すか。"
        limitations = list(evidence.get("warnings") or []) or ["単一Evidenceのため、独立性、比較対象、effect size、例外をまだ評価していない。"]
        findings.append({
            "finding_id": f"F{number:04d}",
            "title": str(evidence.get("operator_name", "Operator evidence")),
            "scientific_question": question,
            "analysis_context": context,
            "observation": observation,
            "interpretation": "Interpretation Agentによる比較評価待ちの機械下書き。現時点では意味解釈を確定しない。",
            "why_notable": "他のDescription、Group、scope、Operatorとの比較対象になり得るEvidenceとして索引化した。",
            "evidence_ids": [evidence_id],
            "result_values": machine,
            "warnings": evidence.get("warnings") or [],
            "limitations": limitations,
            "status": "inconclusive",
            "scope": evidence.get("scope") or {},
        })
    scope_modes = sorted({str((item.get("scope") or {}).get("mode", "global")) for item in evidence_index})
    operator_ids = sorted({str(item.get("operator_id")) for item in evidence_index})
    return {
        "schema_version": SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "run_id": run_id,
        "interpretation_id": interpretation_id,
        "report_status": "draft",
        "agent_review": {"completed": False, "reviewed_at": None, "review_scope": "not_started"},
        "report_summary": {
            "analysis_objective": "Operator evidenceをDescription、Grouping、scope、解析手法の違いから比較し、人間が検討すべきSAR上の特徴を抽出する。",
            "dataset_scope": f"同一runのEvidence {len(evidence_index)}件、Operator {len(operator_ids)}種類、scope={', '.join(scope_modes) or 'unknown'}。",
            "executive_summary": "これは意味解釈前の機械下書きであり、専用Interpretation Agentによるartifact確認とEvidence横断比較を必要とする。",
            "key_messages": ["Evidenceの索引化は完了したが、人間向けの結論はまだ作成されていない。"],
            "coverage_summary": f"{len(evidence_index)}件のEvidenceと{len(relations)}件の比較候補を準備した。",
            "limitations": ["この段階では、effect size、Evidence独立性、矛盾、例外、反証結果を統合評価していない。"],
        },
        "evidence_index": evidence_index,
        "evidence_relations": relations,
        "unresolved_contradictions": [],
        "contradiction_assessment": {"status": "not_assessed", "summary": "Interpretation Agentによる矛盾・反対Evidenceの評価待ち。"},
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
        "hypotheses": [],
        "recommended_next_analysis": [],
        "human_review_points": [
            "専用Interpretation Agentが全artifactを確認し、ObservationとInterpretationを明示的に分ける。",
            "注目候補だけを本文に残し、単なる実行記録はEvidence indexへ移す。",
            "矛盾の未評価と、評価した結果として矛盾が見つからない場合を区別する。",
        ],
        "created_at": utc_now(),
    }


def markdown_report(value: dict[str, Any]) -> str:
    summary = value["report_summary"]
    lines = ["# CONDUCTOR Interpretation Report", ""]
    if value["report_status"] == "draft":
        lines.extend(["> **機械下書き — 最終Interpretationではありません。** 専用Interpretation Agentによる意味解釈と最終化が必要です。", ""])
    lines.extend([
        f"- Run ID: {value['run_id']} / Stage: {value['exploration_summary']['stage']}",
        f"- Report status: {value['report_status']} / Generated: {value['created_at']}",
        "", "## 解析の目的と対象", "", summary["analysis_objective"], "",
        f"**対象範囲:** {summary['dataset_scope']}", "",
        f"**Coverage:** {summary['coverage_summary']}", "",
        "## 解釈サマリー", "", summary["executive_summary"], "", "### 主要メッセージ", "",
    ])
    lines.extend(f"- {item}" for item in summary["key_messages"])
    lines.extend(["", "### 全体の制約", ""])
    lines.extend(f"- {item}" for item in summary["limitations"])
    lines.extend(["", "## 重要な解釈", ""])
    if not value["notable_findings"]:
        lines.extend(["- 現時点で本文に掲載すべき注目結果はない。negative resultまたはcoverage不足は後段を参照する。", ""])
    for finding in value["notable_findings"]:
        lines.extend([
            f"### {finding['title']}", "",
            f"{finding['finding_id']} · **{STATUS_LABELS.get(finding['status'], finding['status'])}**", "",
            f"**解析の問い:** {finding['scientific_question']}", "",
            f"**解析条件:** {analysis_context_text(finding['analysis_context'])}", "",
            "#### 観察", "", finding["observation"], "",
            "#### 解釈", "", finding["interpretation"], "",
            f"**なぜ注目するか:** {finding['why_notable']}", "",
            "**制約・代替説明:**", "",
        ])
        lines.extend(f"- {item}" for item in finding["limitations"])
        lines.extend(["", f"Evidence: {', '.join(finding['evidence_ids'])}", ""])
    contradiction = value["contradiction_assessment"]
    lines.extend(["## 矛盾・反証・negative result", "", f"**評価状態:** {CONTRADICTION_LABELS[contradiction['status']]}", "", contradiction["summary"], ""])
    for item in value["unresolved_contradictions"]:
        label = item.get("title") or item.get("summary") or "未解決の矛盾"
        evidence_ids = ", ".join(item.get("evidence_ids") or [])
        lines.append(f"- {label}" + (f"（Evidence: {evidence_ids}）" if evidence_ids else ""))
    lines.extend(["", "## 仮説候補", "", "HはHypothesis（検証可能な仮説候補）のIDであり、単独Evidenceの通し番号ではない。", ""])
    if not value["hypotheses"]:
        lines.extend(["- 現時点で、複数Evidenceを統合した仮説候補は設定されていない。", ""])
    for hypothesis in value["hypotheses"]:
        lines.extend([
            f"### {hypothesis['title']}", "", f"仮説候補 {hypothesis['hypothesis_id']}", "",
            f"**解析の問い:** {hypothesis['scientific_question']}", "",
            f"**仮説:** {hypothesis['claim']}", "",
            f"- 対象: {hypothesis['target_group'] or 'GLOBAL'}",
            f"- 観察: {hypothesis['observation']}",
            f"- 解釈: {hypothesis['interpretation']}",
            f"- 注目理由: {hypothesis['why_notable']}",
            f"- 支持Evidence: {', '.join(hypothesis['supporting_evidence'])}",
            f"- 矛盾Evidence: {', '.join(hypothesis['contradicting_evidence']) or 'なし'}",
            f"- 確信度: {hypothesis['confidence']}",
            f"- 反証状態: {hypothesis.get('falsification_status', 'unknown')}",
            f"- Evidence独立性: {hypothesis['evidence_independence']}",
            f"- 根拠: {hypothesis['confidence_rationale']}",
            f"- 構造的含意: {hypothesis['proposed_structural_implication']}",
            "", "代替説明・制約:", "",
        ])
        lines.extend(f"- {item}" for item in hypothesis["alternative_explanations"])
        lines.extend(f"- {item}" for item in hypothesis["limitations"])
        lines.extend(["", "適用scope:", ""])
        lines.extend(f"- {item}" for item in hypothesis["scope"])
        lines.extend(["", "例外:", ""])
        lines.extend(f"- {item}" for item in hypothesis["exceptions"])
        lines.extend(["", "次解析:", ""])
        lines.extend(f"- {item}" for item in hypothesis["recommended_next_analysis"])
        lines.extend(["", "次化合物の方向性:", ""])
        lines.extend(f"- {item}" for item in hypothesis["recommended_next_compounds"])
        lines.extend(["", "個別の人間確認事項:", ""])
        lines.extend(f"- {item}" for item in hypothesis["human_review_points"])
        lines.append("")
    lines.extend(["## 推奨される次解析", ""])
    if value["recommended_next_analysis"]:
        for item in value["recommended_next_analysis"]:
            lines.append(f"- {item.get('purpose', '')}: {item.get('action', '')} ({item.get('source_id', '')})")
    else:
        lines.append("- 現時点で登録された追加解析要求はない。")
    lines.extend(["", "## 付録A：Evidence index", ""])
    for item in value["evidence_index"]:
        lines.append(f"- {item['evidence_id']} / Operator={item['operator_id']} / scope={(item.get('scope') or {}).get('mode', 'unknown')} / N={item.get('sample_count', 0)}")
    lines.extend(["", "## 付録B：Evidence間関係候補", ""])
    if value["evidence_relations"]:
        for relation in value["evidence_relations"]:
            lines.append(f"- {relation['relation_id']} {relation['relation_type']} / candidate={relation.get('candidate_relation', '-')} / independence={relation['independence']}: {', '.join(relation['evidence_ids'])} — {relation['rationale']}")
    else:
        lines.append("- 比較候補なし。")
    lines.extend([
        "", "## 付録C：探索・監査情報", "",
        f"- Policy: {value['policy_version']}",
        f"- Seed: {value['exploration_summary'].get('seed')}",
        f"- Attempted signatures: {len(value['exploration_summary'].get('attempted_analysis_signatures') or [])}",
        "", "### 人間による確認事項", "",
    ])
    lines.extend(f"- {item}" for item in value["human_review_points"])
    lines.append("")
    return "\n".join(lines)


def html_report(value: dict[str, Any]) -> str:
    def html_list(items: list[Any], empty: str = "なし") -> str:
        body = "".join(f"<li>{html.escape(str(item))}</li>" for item in items)
        return "<ul>" + (body or f"<li class='meta'>{html.escape(empty)}</li>") + "</ul>"

    summary = value["exploration_summary"]
    report_summary = value["report_summary"]
    findings = "".join(
        f"<article class='finding status-{html.escape(item['status'])}'>"
        f"<div class='card-head'><span class='status-label'>{html.escape(STATUS_LABELS.get(item['status'], item['status']))}</span><span class='id-label'>{html.escape(item['finding_id'])}</span></div>"
        f"<h3>{html.escape(item['title'])}</h3>"
        f"<p class='question'><b>解析の問い</b>{html.escape(item['scientific_question'])}</p>"
        f"<p class='context'>{html.escape(analysis_context_text(item['analysis_context']))}</p>"
        f"<div class='observation'><h4>観察</h4><p>{html.escape(item['observation'])}</p></div>"
        f"<div class='meaning'><h4>解釈</h4><p>{html.escape(item['interpretation'])}</p></div>"
        f"<p><b>なぜ注目するか：</b>{html.escape(item['why_notable'])}</p>"
        f"<div class='limitations'><b>制約・代替説明</b>{html_list(item['limitations'])}</div>"
        f"<p class='meta'>Evidence: {html.escape(', '.join(item['evidence_ids']))}</p></article>"
        for item in value["notable_findings"]
    ) or "<p class='empty'>現時点で本文に掲載すべき注目結果はありません。</p>"
    hypotheses = "".join(
        "<article class='hypothesis'>"
        f"<div class='card-head'><span class='status-label'>仮説候補</span><span class='id-label'>{html.escape(item['hypothesis_id'])}</span></div>"
        f"<h3>{html.escape(item['title'])}</h3>"
        f"<p class='question'><b>解析の問い</b>{html.escape(item['scientific_question'])}</p>"
        f"<p class='claim'><b>仮説</b>{html.escape(item['claim'])}</p><dl>"
        f"<dt>対象</dt><dd>{html.escape(str(item['target_group'] or 'GLOBAL'))}</dd>"
        f"<dt>観察</dt><dd>{html.escape(item['observation'])}</dd>"
        f"<dt>解釈</dt><dd>{html.escape(item['interpretation'])}</dd>"
        f"<dt>注目理由</dt><dd>{html.escape(item['why_notable'])}</dd>"
        f"<dt>支持Evidence</dt><dd>{html.escape(', '.join(item['supporting_evidence']))}</dd>"
        f"<dt>矛盾Evidence</dt><dd>{html.escape(', '.join(item['contradicting_evidence']) or 'なし')}</dd>"
        f"<dt>Evidence独立性</dt><dd>{html.escape(item['evidence_independence'])}</dd>"
        f"<dt>代替説明</dt><dd>{html_list(item['alternative_explanations'])}</dd>"
        f"<dt>制約</dt><dd>{html_list(item['limitations'])}</dd>"
        f"<dt>確信度</dt><dd>{html.escape(item['confidence'])} — {html.escape(item['confidence_rationale'])}</dd>"
        f"<dt>反証状態</dt><dd>{html.escape(item['falsification_status'])}</dd>"
        f"<dt>次解析</dt><dd>{html_list(item['recommended_next_analysis'])}</dd>"
        "</dl></article>"
        for item in value["hypotheses"]
    ) or "<p class='empty'>現時点で、複数Evidenceを統合した仮説候補は設定されていません。</p>"
    contradiction = value["contradiction_assessment"]
    contradiction_items = "".join(
        f"<article class='contradiction'><h3>{html.escape(item['title'])}</h3><p>{html.escape(item['summary'])}</p>{html_list(item['evidence_ids'])}</article>"
        for item in value["unresolved_contradictions"]
    ) or "<p class='empty'>個別に記録された未解決矛盾はありません。</p>"
    next_items = "".join(
        f"<li><b>{html.escape(item['purpose'])}</b> — {html.escape(item['action'])} <span class='meta'>({html.escape(item['source_id'])})</span></li>"
        for item in value["recommended_next_analysis"]
    )
    evidence_rows = "".join(
        f"<tr><td>{html.escape(item['evidence_id'])}</td><td>{html.escape(item['operator_id'])}</td>"
        f"<td>{html.escape(str((item.get('scope') or {}).get('mode', 'unknown')))}</td>"
        f"<td>{html.escape(str(item.get('evaluation_representation') or '-'))}</td>"
        f"<td>{html.escape(str(item.get('grouping_representation') or '-'))}</td><td>{item.get('sample_count', 0)}</td></tr>"
        for item in value["evidence_index"]
    )
    relation_rows = "".join(
        f"<tr><td>{html.escape(item['relation_id'])}</td><td>{html.escape(item['relation_type'])}</td>"
        f"<td>{html.escape(str(item.get('candidate_relation') or '-'))}</td><td>{html.escape(item['independence'])}</td>"
        f"<td>{html.escape(', '.join(item['evidence_ids']))}</td><td>{html.escape(item['rationale'])}</td></tr>"
        for item in value["evidence_relations"]
    ) or "<tr><td colspan='6'>比較候補なし。</td></tr>"
    draft_banner = "<div class='draft-banner'><b>機械下書き</b> — 最終Interpretationではありません。専用Agentによる最終化が必要です。</div>" if value["report_status"] == "draft" else ""
    css = """:root{--ink:#263640;--muted:#68747b;--line:#d8d5cd;--paper:#f4f2ed;--surface:#fff;--navy:#304957;--blue:#536f80;--blue-soft:#e9eef1;--teal:#4d706b;--teal-soft:#e6eeec;--ochre:#806637;--ochre-soft:#f2ede1;--brick:#85534b;--brick-soft:#f2e8e5;--gray-soft:#eeefed}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.75 "Yu Gothic UI","Segoe UI",sans-serif}main{max-width:1120px;margin:28px auto;padding:44px 52px 64px;background:var(--surface);box-shadow:0 12px 36px #24374618}header{border-bottom:1px solid var(--line);padding-bottom:22px}h1,h2{font-family:"Yu Mincho","Hiragino Mincho ProN",serif;color:var(--navy)}h1{font-size:34px;margin:4px 0 8px}h2{margin-top:48px;padding-bottom:9px;border-bottom:2px solid var(--navy);font-size:23px}.draft-banner{margin:22px 0;padding:14px 18px;border-left:5px solid var(--ochre);background:var(--ochre-soft)}.lead{font-size:17px}.scope{padding:14px 18px;background:var(--blue-soft);border-left:4px solid var(--blue)}.key-messages{padding:18px 24px;background:#f7f8f6;border:1px solid var(--line)}article{border:1px solid var(--line);border-radius:7px;padding:22px 24px;margin:18px 0}.card-head{display:flex;gap:9px}.status-label,.id-label{padding:2px 8px;font-size:12px;font-weight:700;border-radius:3px}.id-label{background:var(--gray-soft);color:var(--muted)}.status-discovery,.hypothesis{border-left:6px solid var(--ochre)}.status-validated{border-left:6px solid var(--teal)}.status-refuted,.contradiction{border-left:6px solid var(--brick)}.status-inconclusive,.status-negative{border-left:6px solid #8b9292}.question b,.claim b{display:block;color:var(--navy);font-size:12px}.context{font-size:13px;color:var(--muted);padding:8px 12px;background:#f6f6f3}.observation{padding:13px 16px;background:#f7f8f7;border-left:4px solid #89969c}.meaning{padding:15px 18px;margin:12px 0;background:var(--teal-soft);border-left:5px solid var(--teal)}.limitations,.claim{padding:12px 16px;background:var(--ochre-soft)}.contradiction-summary{padding:16px 19px;background:var(--brick-soft);border-left:5px solid var(--brick)}.empty,.meta{color:var(--muted)}.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{border:1px solid var(--line);padding:8px;text-align:left;vertical-align:top}th{background:#f0f1ee}dt{font-weight:700;color:var(--navy);margin-top:10px}dd{margin-left:0}details{margin-top:24px;border-top:1px solid var(--line);padding-top:12px}summary{cursor:pointer;color:var(--navy);font-weight:700}@media(max-width:700px){main{margin:0;padding:26px 20px}}@media print{body{background:#fff}main{box-shadow:none;margin:0;max-width:none}}"""
    key_messages = html_list(report_summary["key_messages"])
    limitations = html_list(report_summary["limitations"])
    next_body = f"<ul>{next_items}</ul>" if next_items else "<p class='empty'>現時点で登録された追加解析要求はありません。</p>"
    reviews = html_list(value["human_review_points"])
    return f"""<!doctype html><html lang='ja'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>CONDUCTOR Interpretation Report</title><style>{css}</style></head><body><main><header><p class='meta'>SAR evidence interpretation</p><h1>CONDUCTOR Interpretation Report</h1><p class='meta'>Run {html.escape(value['run_id'])} · Stage {html.escape(summary['stage'])} · {html.escape(value['created_at'])}</p></header>{draft_banner}<h2>解析の目的と対象</h2><p class='lead'>{html.escape(report_summary['analysis_objective'])}</p><p class='scope'><b>対象範囲</b><br>{html.escape(report_summary['dataset_scope'])}<br><b>Coverage</b><br>{html.escape(report_summary['coverage_summary'])}</p><h2>解釈サマリー</h2><p class='lead'>{html.escape(report_summary['executive_summary'])}</p><div class='key-messages'><b>主要メッセージ</b>{key_messages}</div><div class='limitations'><b>全体の制約</b>{limitations}</div><h2>重要な解釈</h2>{findings}<h2>矛盾・反証・negative result</h2><div class='contradiction-summary'><b>{html.escape(CONTRADICTION_LABELS[contradiction['status']])}</b><p>{html.escape(contradiction['summary'])}</p></div>{contradiction_items}<h2>仮説候補</h2><p class='meta'>HはHypothesis（検証可能な仮説候補）のIDです。単独Evidenceの通し番号ではありません。</p>{hypotheses}<h2>推奨される次解析</h2>{next_body}<details><summary>付録A：Evidence index</summary><div class='table-wrap'><table><thead><tr><th>Evidence</th><th>Operator</th><th>Scope</th><th>Description</th><th>Grouping</th><th>N</th></tr></thead><tbody>{evidence_rows}</tbody></table></div></details><details><summary>付録B：Evidence間関係候補</summary><div class='table-wrap'><table><thead><tr><th>ID</th><th>関係</th><th>候補比較</th><th>独立性</th><th>Evidence</th><th>根拠</th></tr></thead><tbody>{relation_rows}</tbody></table></div></details><details><summary>付録C：探索・監査情報</summary><p>Policy {html.escape(value['policy_version'])} / Seed {html.escape(str(summary.get('seed')))} / Attempted signatures {len(summary.get('attempted_analysis_signatures') or [])}</p><h3>人間による確認事項</h3>{reviews}</details></main></body></html>"""


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
    if state:
        validate(state, "state.schema.json")
    if state and state.get("run", {}).get("run_id") != run_id:
        raise ValueError("State run_id does not match Interpretation run_id")
    catalog = load_catalog(args.catalog)
    index = build_evidence_index(records, catalog, state)
    relations = build_relations(index)
    state_info = state_context(state)
    configured_seed = ((state_info.get("exploration") or {}).get("budget") or {}).get("seed")
    seed = args.seed if args.seed is not None else (configured_seed if configured_seed is not None else int(value_hash(run_id)[:8], 16))
    interpretation_id = f"{run_id}:{args.node_id}" if args.conductor else f"{run_id}:standalone:{value_hash([item['evidence_id'] for item in index])[:12]}"
    interpretation = build_interpretation(evidence_items, index, relations, run_id, interpretation_id, args.stage, state_info, seed)
    validate(interpretation, "interpretation.schema.json")
    previous = []
    for path_text in args.previous_interpretation:
        prior = json.loads(Path(path_text).read_text(encoding="utf-8"))
        validate(prior, "interpretation.schema.json")
        if prior.get("run_id") != run_id:
            raise ValueError(f"Previous Interpretation belongs to another run: {prior.get('run_id')}")
        previous.append(prior)
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
    if outdir.exists() and any(outdir.iterdir()):
        if not args.overwrite:
            raise FileExistsError(f"Output directory is not empty; use --overwrite: {outdir}")
        for name in ["interpretation.json", "interpretation.md", "interpretation.html", "interpretation_context.json", "exploration_plan.json", "execution_event.json"]:
            (outdir / name).unlink(missing_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)
    targets = [outdir / "interpretation.json", outdir / "interpretation.md", outdir / "interpretation.html", outdir / "interpretation_context.json"]
    write_json(targets[0], interpretation)
    targets[1].write_text(markdown_report(interpretation), encoding="utf-8")
    targets[2].write_text(html_report(interpretation), encoding="utf-8")
    write_json(targets[3], context)
    if args.conductor:
        config = vars(args)
        input_components = [{"role": "evidence", "path": str(path.resolve()), "sha256": file_hash(path)} for path in paths]
        if args.state:
            state_path = Path(args.state)
            input_components.append({"role": "state", "path": str(state_path.resolve()), "sha256": file_hash(state_path)})
        for path_text in args.previous_interpretation:
            previous_path = Path(path_text)
            input_components.append({"role": "previous_interpretation", "path": str(previous_path.resolve()), "sha256": file_hash(previous_path)})
        catalog_path = Path(args.catalog) if args.catalog else default_catalog_path()
        if catalog_path.exists():
            input_components.append({"role": "catalog", "path": str(catalog_path.resolve()), "sha256": file_hash(catalog_path)})
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
