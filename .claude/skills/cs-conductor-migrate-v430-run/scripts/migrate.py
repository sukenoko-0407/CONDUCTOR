from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sys
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


TRANSIENT = {"output_dir", "project", "run_id", "node_id", "conductor", "overwrite", "input", "description", "membership", "state", "evidence", "catalog", "previous_interpretation", "id_reservation"}
STAGE_PREFIX = {"description": "ND", "grouping": "NG", "analysis": "NO"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def value_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def write_json(path: Path, value: Any) -> None:
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def write_csv(path: Path, fields: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def workspace_root() -> Path:
    skill = Path(__file__).resolve().parents[1]
    for candidate in [skill, *skill.parents, Path.cwd(), *Path.cwd().parents]:
        if (candidate / ".claude" / "skills").is_dir() and (candidate / "CONDUCTOR_modules" / "catalog" / "catalog.json").is_file():
            return candidate
    raise RuntimeError("Installed CONDUCTOR Project root was not found")


def basic_coverage(nodes: list[dict[str, Any]], run: dict[str, Any]) -> dict[str, Any]:
    root = workspace_root()
    catalog = read_json(root / "CONDUCTOR_modules" / "catalog" / "catalog.json")
    profile = read_json(root / "CONDUCTOR_modules" / "catalog" / "analysis_profile.json")
    capabilities = {item["capability_id"]: item for item in catalog["capabilities"]}
    succeeded = [node for node in nodes if node.get("status") == "succeeded"]
    by_id = {node["node_id"]: node for node in succeeded}
    descriptions = {node["capability_id"] for node in succeeded if node.get("stage") == "description"}
    grouping_nodes = [node for node in succeeded if node.get("stage") == "grouping"]
    basic = profile["basic_compute"]
    expected_descriptions = (
        sorted(capability_id for capability_id, item in capabilities.items() if item.get("stage") == "description")
        if "*" in basic["description_capabilities"] else list(basic["description_capabilities"])
    )
    expected: list[dict[str, Any]] = []
    expected.extend({"kind": "description", "capability_id": capability_id} for capability_id in expected_descriptions)
    expected.extend({"kind": "direct_grouping", "capability_id": capability_id} for capability_id in basic["direct_structure_grouping"])
    expected.extend(
        {"kind": "vector_grouping", "capability_id": grouping_id, "description_capability_id": description_id}
        for grouping_id in basic["vector_grouping_capabilities"]
        for description_id in basic["vector_grouping_representations"]
    )
    if int(run.get("assay_level_count") or 0) > 1 and "C011" in basic.get("conditional_grouping", []):
        expected.append({"kind": "conditional_grouping", "capability_id": "C011"})

    def covered(item: dict[str, Any]) -> bool:
        if item["kind"] == "description":
            return item["capability_id"] in descriptions
        candidates = [node for node in grouping_nodes if node.get("capability_id") == item["capability_id"]]
        if item["kind"] != "vector_grouping":
            return bool(candidates)
        required_description = item["description_capability_id"]
        return any(
            any(by_id.get(dependency, {}).get("capability_id") == required_description for dependency in node.get("dependencies") or [])
            for node in candidates
        )

    missing = [item for item in expected if not covered(item)]
    return {
        "complete": not missing,
        "expected_count": len(expected),
        "covered_count": len(expected) - len(missing),
        "missing_count": len(missing),
        "missing": missing,
    }


def imported_phase_complete(source_state: dict[str, Any], included_ids: set[str], phase: str) -> bool:
    planned = any(item.get("action") == f"{phase}_planned" for item in source_state.get("history") or [])
    source_nodes = [node for node in source_state.get("execution_graph", {}).get("nodes", []) if node.get("phase") == phase and node.get("stage") != "interpretation"]
    return bool(planned and source_nodes and all(node.get("status") == "succeeded" and node.get("node_id") in included_ids for node in source_nodes))


def topological_nodes(nodes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    ids = [str(node.get("node_id")) for node in nodes]
    duplicates = sorted({node_id for node_id in ids if ids.count(node_id) > 1})
    if duplicates:
        return [], [f"duplicate source Node IDs prevent deterministic dependency resolution: {duplicates[:20]}"]
    by_id = {node["node_id"]: node for node in nodes}
    indegree = {node_id: 0 for node_id in by_id}; adjacency: dict[str, list[str]] = defaultdict(list)
    for node in nodes:
        for dependency in node.get("dependencies") or []:
            if dependency not in by_id:
                errors.append(f"{node['node_id']} references unknown dependency {dependency}")
                continue
            indegree[node["node_id"]] += 1; adjacency[dependency].append(node["node_id"])
    queue = deque(sorted(node_id for node_id, degree in indegree.items() if degree == 0))
    ordered: list[dict[str, Any]] = []
    while queue:
        node_id = queue.popleft(); ordered.append(by_id[node_id])
        for target in sorted(adjacency[node_id]):
            indegree[target] -= 1
            if indegree[target] == 0: queue.append(target)
    if len(ordered) != len(nodes): errors.append("source execution graph contains a cycle or unresolved dependency")
    return ordered, errors


def resolved_artifacts(node: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    for artifact in node.get("artifacts") or []:
        raw = artifact.get("resolved_path")
        if raw: paths.append(Path(raw).expanduser().resolve())
    output = Path(str(node.get("output_dir") or "")).expanduser().resolve()
    if not paths and output.is_dir():
        paths = [path for path in output.rglob("*") if path.is_file()]
    return paths


def validate_scientific_node(node: dict[str, Any]) -> tuple[bool, list[str], list[dict[str, Any]]]:
    reasons: list[str] = []; manifest: list[dict[str, Any]] = []
    output = Path(str(node.get("output_dir") or "")).expanduser().resolve()
    if not output.is_dir(): reasons.append("output_dir_missing")
    paths = resolved_artifacts(node)
    if not paths: reasons.append("no_artifact_files")
    for path in paths:
        if not path.is_file():
            reasons.append(f"artifact_missing:{path}"); continue
        expected = next((item.get("sha256") for item in node.get("artifacts") or [] if item.get("resolved_path") and Path(item["resolved_path"]).expanduser().resolve() == path), None)
        actual = sha256(path)
        if expected and expected != actual: reasons.append(f"artifact_hash_mismatch:{path}")
        manifest.append({"path": str(path), "sha256": actual, "bytes": path.stat().st_size})
    names = {path.name.lower() for path in paths if path.is_file()}
    suffixes = {path.suffix.lower() for path in paths if path.is_file()}
    stage = node.get("stage")
    if stage == "description" and not ({".csv", ".parquet", ".npz"} & suffixes): reasons.append("description_primary_artifact_missing")
    if stage == "grouping" and not any("membership" in name for name in names): reasons.append("group_membership_missing")
    if stage == "analysis":
        for required in ["evidence.json", "operator_report.html"]:
            if required not in names: reasons.append(f"{required}_missing")
    return not reasons, reasons, manifest


def relative_output(node: dict[str, Any], new_id: str) -> str:
    stage_dir = {"description": "description", "grouping": "grouping", "analysis": "analysis"}[node["stage"]]
    return str(Path(stage_dir) / str(node.get("skill_name") or node.get("capability_id")) / new_id)


def scan(source: Path, target: Path, new_run_id: str | None) -> tuple[Path, dict[str, Any]]:
    state_path = source / "state.json"
    if not state_path.is_file(): raise FileNotFoundError(state_path)
    if target.exists(): raise FileExistsError(f"Target must not exist during scan: {target}")
    state = read_json(state_path)
    errors: list[str] = []
    if state.get("conductor_version") != "4.3.0" or state.get("schema_version") != "2.0.0":
        errors.append(f"expected v4.3.0/schema 2.0.0, found {state.get('conductor_version')}/{state.get('schema_version')}")
    ordered, graph_errors = topological_nodes(state.get("execution_graph", {}).get("nodes", [])); errors.extend(graph_errors)
    included: list[dict[str, Any]] = []; excluded: list[dict[str, Any]] = []
    valid_old_ids: set[str] = set(); seen_signatures: set[str] = set(); manifests: dict[str, list[dict[str, Any]]] = {}
    for node in ordered:
        old_id = str(node.get("node_id")); stage = node.get("stage")
        reasons: list[str] = []
        if stage == "interpretation": reasons.append("legacy_interpretation_reference_only")
        elif stage not in STAGE_PREFIX: reasons.append("unsupported_stage")
        if node.get("status") != "succeeded": reasons.append(f"status_{node.get('status')}")
        missing_dependencies = [dep for dep in node.get("dependencies") or [] if dep not in valid_old_ids]
        if missing_dependencies: reasons.append("dependency_not_imported:" + ",".join(missing_dependencies))
        signature = str(node.get("analysis_signature") or "")
        if signature and signature in seen_signatures: reasons.append("duplicate_active_signature")
        artifact_manifest: list[dict[str, Any]] = []
        if not reasons:
            valid, artifact_reasons, artifact_manifest = validate_scientific_node(node)
            if not valid: reasons.extend(artifact_reasons)
        if reasons:
            excluded.append({"old_node_id": old_id, "stage": stage, "capability_id": node.get("capability_id"), "reasons": reasons})
            continue
        included.append(node); valid_old_ids.add(old_id); manifests[old_id] = artifact_manifest
        if signature: seen_signatures.add(signature)
    counters = defaultdict(int); mapping: dict[str, str] = {}
    for node in included:
        counters[node["stage"]] += 1; mapping[node["node_id"]] = f"{STAGE_PREFIX[node['stage']]}{counters[node['stage']]:04d}"
    plan_root = target.parent / ".conductor_migration_plans" / target.name / stamp()
    plan_root.mkdir(parents=True, exist_ok=False)
    node_plan = [{
        "old_node_id": node["node_id"], "new_node_id": mapping[node["node_id"]], "stage": node["stage"],
        "capability_id": node.get("capability_id"), "skill_name": node.get("skill_name"),
        "old_output_dir": str(Path(node["output_dir"]).resolve()), "new_output_relative": relative_output(node, mapping[node["node_id"]]),
        "artifact_manifest": manifests[node["node_id"]],
    } for node in included]
    plan = {
        "schema_version": "1.0.0", "migration": "v4.3.0_to_v4.3.1", "applicable": not errors,
        "source_run_root": str(source), "source_state": str(state_path), "source_state_sha256": sha256(state_path),
        "source_run_id": state.get("run", {}).get("run_id"), "target_run_root": str(target),
        "new_run_id": new_run_id or f"{state.get('run', {}).get('run_id', source.name)}-v431",
        "included_node_count": len(included), "excluded_node_count": len(excluded), "node_plan": node_plan,
        "excluded_nodes": excluded, "node_id_map": mapping, "errors": errors,
        "source_input": state.get("run", {}).get("input"), "source_input_sha256": state.get("run", {}).get("input_hash"),
        "migration_baseline": {
            "basic_compute": basic_coverage(included, state.get("run", {})),
            "initial_global_complete": imported_phase_complete(state, valid_old_ids, "initial_global"),
            "initial_local_complete": imported_phase_complete(state, valid_old_ids, "initial_local"),
        },
        "created_at": now(), "approval_required": True,
    }
    write_json(plan_root / "migration_plan.json", plan)
    write_json(plan_root / "scan_report.json", {key: value for key, value in plan.items() if key not in {"node_plan", "node_id_map"}})
    write_csv(plan_root / "node_id_map.csv", ["old_node_id", "new_node_id", "stage", "capability_id", "skill_name"], node_plan)
    write_csv(plan_root / "excluded_nodes.csv", ["old_node_id", "stage", "capability_id", "reasons"], ({**row, "reasons": ";".join(row["reasons"])} for row in excluded))
    baseline = plan["migration_baseline"]
    lines = ["# CONDUCTOR v4.3.0 Migration Scan", "", f"- Applicable: {plan['applicable']}", f"- Source: `{source}`", f"- Target: `{target}`", f"- Included Nodes: {len(included)}", f"- Excluded Nodes: {len(excluded)}", f"- Basic coverage: {baseline['basic_compute']['covered_count']}/{baseline['basic_compute']['expected_count']}", f"- Initial global complete: {baseline['initial_global_complete']}", f"- Initial local complete: {baseline['initial_local_complete']}", "", "## Errors", ""]
    lines.extend(f"- {error}" for error in errors); lines.extend(["", "## Approval", "", "`apply --approve` は人間がこのscanを確認した後だけ実行する。", ""])
    atomic_write(plan_root / "scan_report.md", "\n".join(lines))
    return plan_root, plan


def replace_value(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, dict): return {key: replace_value(item, replacements) for key, item in value.items()}
    if isinstance(value, list): return [replace_value(item, replacements) for item in value]
    if isinstance(value, str):
        if value in replacements: return replacements[value]
        result = value
        for old, new in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
            if old and old in result: result = result.replace(old, new)
        return result
    return value


def patch_metadata_tree(root: Path, replacements: dict[str, str]) -> None:
    allowed = {".json", ".jsonl", ".csv", ".md", ".html", ".yaml", ".yml", ".txt"}
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in allowed or path.stat().st_size > 20 * 1024 * 1024: continue
        try: text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError: continue
        updated = text
        for old, new in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
            if old: updated = updated.replace(old, new)
        if updated != text: atomic_write(path, updated)


def analysis_signature(node: dict[str, Any]) -> str:
    scientific = {key: value for key, value in node.get("parameters", {}).items() if key not in TRANSIENT}
    scope = {key: scientific.get(key) for key in ["scope_mode", "target_group", "comparison_group"] if scientific.get(key) is not None}
    payload = {"capability_id": node["capability_id"], "dependencies": sorted(node.get("dependencies") or []), "parameters": scientific, "scope": scope}
    return value_hash(payload)


def copy_package_snapshot(target: Path) -> dict[str, Any]:
    root = workspace_root(); snapshot = target / "snapshots"; snapshot.mkdir(parents=True, exist_ok=True)
    sources = {
        "catalog": root / "CONDUCTOR_modules" / "catalog" / "catalog.json",
        "profile": root / "CONDUCTOR_modules" / "catalog" / "analysis_profile.json",
        "orchestration_policy": root / "CONDUCTOR_modules" / "docs" / "CONDUCTOR_v4_policy.md",
        "interpretation_policy": root / "CONDUCTOR_modules" / "docs" / "CONDUCTOR_v4_interpretation_policy.md",
    }
    records = {"profile_id": "comprehensive-multiround-v1", "files": {}}
    for name, source in sources.items():
        destination = snapshot / source.name; shutil.copy2(source, destination)
        records["files"][name] = {"source": str(source), "snapshot": str(destination), "sha256": sha256(source)}
    records["snapshot_hash"] = value_hash({name: item["sha256"] for name, item in records["files"].items()}); records["created_at"] = now()
    return records


def max_entity_counter(source_state: dict[str, Any], key: str) -> int:
    return int(source_state.get("id_counters", {}).get(key) or 0)


def apply(plan_path: Path) -> dict[str, Any]:
    plan = read_json(plan_path)
    if not plan.get("applicable"): raise ValueError(f"Migration plan is not applicable: {plan.get('errors')}")
    source = Path(plan["source_run_root"]).resolve(); target = Path(plan["target_run_root"]).resolve()
    source_state_path = Path(plan["source_state"]).resolve()
    if sha256(source_state_path) != plan["source_state_sha256"]: raise ValueError("Source state changed after scan; rescan is required")
    if target.exists(): raise FileExistsError(f"Target already exists: {target}")
    changed_artifacts = []
    for item in plan["node_plan"]:
        for artifact in item.get("artifact_manifest") or []:
            path = Path(artifact["path"])
            if not path.is_file() or sha256(path) != artifact["sha256"]:
                changed_artifacts.append(str(path))
    if changed_artifacts:
        raise ValueError(f"Source artifacts changed after scan; rescan is required: {changed_artifacts[:20]}")
    input_source = Path(plan["source_input"]).resolve()
    if not input_source.is_file(): raise FileNotFoundError(input_source)
    if plan.get("source_input_sha256") and sha256(input_source) != plan["source_input_sha256"]:
        raise ValueError("Source input changed after scan; rescan is required")
    source_state = read_json(source_state_path)
    by_old_preflight = {node["node_id"]: node for node in source_state["execution_graph"]["nodes"]}
    normalized_signatures: list[str] = []
    evidence_ids: list[str] = []
    for item in plan["node_plan"]:
        source_node = dict(by_old_preflight[item["old_node_id"]])
        source_node["node_id"] = item["new_node_id"]
        source_node["dependencies"] = [plan["node_id_map"][dep] for dep in source_node.get("dependencies") or []]
        normalized_signatures.append(analysis_signature(source_node))
        if source_node.get("stage") == "analysis" and source_node.get("evidence_id"):
            evidence_ids.append(str(source_node["evidence_id"]))
    if len(normalized_signatures) != len(set(normalized_signatures)):
        raise ValueError("Imported Nodes collapse to duplicate v4.3.1 analysis signatures; review exclusions")
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("Source has duplicate Evidence IDs; deterministic import is unsafe")
    target.mkdir(parents=True, exist_ok=False)
    migration_root = target / "migration" / "v430_import"; migration_root.mkdir(parents=True)
    for name in ["migration_plan.json", "scan_report.json", "scan_report.md", "node_id_map.csv", "excluded_nodes.csv"]:
        path = plan_path.parent / name
        if path.is_file(): shutil.copy2(path, migration_root / name)
    input_target = target / "input" / input_source.name; input_target.parent.mkdir(parents=True); shutil.copy2(input_source, input_target)
    if plan.get("source_input_sha256") and sha256(input_target) != plan["source_input_sha256"]: raise ValueError("Input hash does not match source State")
    node_map = plan["node_id_map"]; by_old = {node["node_id"]: node for node in source_state["execution_graph"]["nodes"]}
    replacements = {str(source): str(target), str(input_source): str(input_target), str(source_state.get("run", {}).get("run_id")): str(plan["new_run_id"])}
    for item in plan["node_plan"]:
        replacements[item["old_node_id"]] = item["new_node_id"]
        replacements[item["old_output_dir"]] = str((target / item["new_output_relative"]).resolve())
    imported_nodes: list[dict[str, Any]] = []; artifact_manifest: list[dict[str, Any]] = []
    for item in plan["node_plan"]:
        old = by_old[item["old_node_id"]]; destination = target / item["new_output_relative"]
        shutil.copytree(Path(item["old_output_dir"]), destination)
        patch_metadata_tree(destination, replacements)
        node = replace_value(old, replacements)
        node.update({
            "node_id": item["new_node_id"], "round_id": "RND0001", "status": "succeeded",
            "dependencies": [node_map[dep] for dep in old.get("dependencies") or []],
            "output_dir": str(destination.resolve()), "legacy_node_id": item["old_node_id"],
            "legacy_round_id": old.get("round_id"), "migration_status": "validated_import",
            "current_attempt_id": None,
            "execution_attempts": [{"attempt_id": f"{item['new_node_id']}-TRY001", "number": 1, "status": "succeeded", "started_at": old.get("started_at"), "finished_at": old.get("finished_at"), "origin": "v4.3.0_import"}],
        })
        node["input_bindings"] = replace_value(old.get("input_bindings") or {}, replacements)
        node["parameters"] = replace_value(old.get("parameters") or {}, replacements)
        node["parameters"]["output_dir"] = str(destination.resolve())
        if "input" in node["parameters"] and node["stage"] in {"description", "analysis"}: node["parameters"]["input"] = str(input_target.resolve())
        node["analysis_signature"] = analysis_signature(node)
        artifacts = []
        for artifact in old.get("artifacts") or []:
            copied = replace_value(artifact, replacements)
            old_path = Path(str(artifact.get("resolved_path") or ""))
            try: relative = old_path.resolve().relative_to(Path(item["old_output_dir"]).resolve()); new_path = destination / relative
            except (ValueError, OSError): new_path = Path(str(copied.get("resolved_path") or ""))
            if new_path.is_file():
                copied["resolved_path"] = str(new_path.resolve()); copied["sha256"] = sha256(new_path); artifacts.append(copied)
        if not artifacts:
            artifacts = [{"type": "imported_artifact", "path": str(path.relative_to(destination)), "resolved_path": str(path.resolve()), "sha256": sha256(path)} for path in destination.rglob("*") if path.is_file()]
        node["artifacts"] = artifacts; imported_nodes.append(node)
        artifact_manifest.extend({"old_node_id": item["old_node_id"], "new_node_id": item["new_node_id"], "path": artifact["resolved_path"], "sha256": artifact.get("sha256")} for artifact in artifacts)
    source_registry_value = source_state.get("indices", {}).get("group", {}).get("registry_path")
    source_registry = Path(str(source_registry_value)).expanduser() if source_registry_value else None
    old_group_index = source_registry.parent if source_registry and source_registry.is_file() else source / "grouping" / "group_index"
    new_group_index = target / "grouping" / "group_index"
    if old_group_index.is_dir() and not new_group_index.exists():
        shutil.copytree(old_group_index, new_group_index); patch_metadata_tree(new_group_index, replacements)
    legacy_interpretation = source / "interpretation"
    if legacy_interpretation.is_dir(): shutil.copytree(legacy_interpretation, migration_root / "legacy_interpretation_reference")
    indices_root = target / "indices"; indices_root.mkdir(parents=True, exist_ok=True)
    group_registry = new_group_index / "group_registry.csv"
    matrix = sorted(new_group_index.glob("Cpd_Group_matrix_*.csv")) if new_group_index.is_dir() else []
    evidence_digests: list[dict[str, Any]] = []
    for node in imported_nodes:
        if node["stage"] != "analysis": continue
        evidence_path = Path(node["output_dir"]) / "evidence.json"
        if not evidence_path.is_file(): continue
        evidence = read_json(evidence_path)
        evidence_digests.append({
            "evidence_id": node.get("evidence_id") or evidence.get("evidence_id"), "node_id": node["node_id"],
            "round_id": "RND0001", "capability_id": node["capability_id"], "skill_name": node["skill_name"],
            "status": "succeeded", "artifact": str(evidence_path), "summary": evidence.get("summary") or evidence.get("operator_summary"),
            "imported_from_v430": True,
        })
    def jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
        atomic_write(path, "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    jsonl(indices_root / "evidence_digest.jsonl", evidence_digests)
    jsonl(indices_root / "salience_history.jsonl", ({"event_id": f"SEV{index:04d}", "evidence_id": row["evidence_id"], "attention_class": "untriaged", "scientific_role": "inconclusive", "human_pinned": False, "reason": "Imported v4.3.0 Evidence requires fresh Interpretation", "round_id": "RND0001", "created_at": now()} for index, row in enumerate(evidence_digests, 1)))
    shutil.copy2(indices_root / "salience_history.jsonl", indices_root / "salience_view.jsonl")
    for name in ["question_ledger.jsonl", "relation_index.jsonl", "finding_ledger.jsonl", "hypothesis_ledger.jsonl", "analysis_request_ledger.jsonl"]: atomic_write(indices_root / name, "")
    coverage = [{"node_id": node["node_id"], "capability_id": node["capability_id"], "stage": node["stage"], "phase": node.get("phase"), "round_id": "RND0001", "status": "succeeded", "analysis_signature": node["analysis_signature"], "imported_from": node["legacy_node_id"]} for node in imported_nodes]
    write_json(indices_root / "coverage_index.json", {"schema_version": "2.0.0", "cells": coverage, "updated_at": now()})
    edges = [{"source": dep, "target": node["node_id"], "relation": "depends_on"} for node in imported_nodes for dep in node["dependencies"]]
    stage_counts = {stage: sum(node["stage"] == stage for node in imported_nodes) for stage in STAGE_PREFIX}
    counter = source_state.get("id_counters", {})
    registry_rows: list[dict[str, str]] = []
    if group_registry.is_file():
        with group_registry.open("r", encoding="utf-8-sig", newline="") as handle:
            registry_rows = list(csv.DictReader(handle))
    group_max = max(
        (
            int(match.group(1))
            for match in (re.fullmatch(r"G(\d+)", str(row.get("group_id") or "")) for row in registry_rows)
            if match
        ),
        default=max_entity_counter(source_state, "group"),
    )
    active_group_count = sum(str(row.get("status") or "active").lower() not in {"deprioritized", "inactive", "retired"} for row in registry_rows)
    deprioritized_group_count = len(registry_rows) - active_group_count
    group_by_node: dict[str, str] = {}
    for node in imported_nodes:
        if node["stage"] != "grouping":
            continue
        membership_value = node.get("global_membership_path")
        membership_path = Path(str(membership_value)) if membership_value else None
        if not membership_path or not membership_path.is_file():
            candidates = sorted(
                path
                for path in Path(node["output_dir"]).rglob("*.csv")
                if "membership" in path.name.lower()
            )
            membership_path = candidates[0] if candidates else None
        if membership_path and membership_path.is_file():
            node["global_membership_path"] = str(membership_path.resolve())
            group_by_node[node["node_id"]] = str(membership_path.resolve())
    evidence_max = max(
        (
            int(match.group(1))
            for match in (re.fullmatch(r"E(\d+)", str(row.get("evidence_id") or "")) for row in evidence_digests)
            if match
        ),
        default=max_entity_counter(source_state, "evidence"),
    )
    package_snapshot = copy_package_snapshot(target)
    high_cost = dict(source_state.get("run", {}).get("high_cost_bundle") or {"capability_ids": [], "status": "approved", "scope": {}, "scope_hash": "0" * 64})
    high_cost["status"] = "approved" if high_cost.get("status") == "approved" else "pending"
    state = {
        "schema_version": "2.1.0", "conductor_version": "4.3.1",
        "run": {
            **{key: value for key, value in source_state.get("run", {}).items() if key not in {"run_id", "input", "input_hash", "package_snapshot", "package_snapshot_history", "package_change_gate", "created_at", "high_cost_bundle"}},
            "run_id": plan["new_run_id"], "input": str(input_target.resolve()), "input_hash": sha256(input_target),
            "package_snapshot": package_snapshot, "package_change_gate": {"status": "clear", "checked_at": now(), "differences": []},
            "high_cost_bundle": high_cost, "created_at": now(),
            "migration_provenance": {"source_run_root": str(source), "source_run_id": plan["source_run_id"], "plan": str((migration_root / 'migration_plan.json').resolve())},
            "migration_baseline": plan["migration_baseline"],
        },
        "round_control": {"active_round_id": None, "next_round_number": 2, "rounds": [
            {"round_id": "RND0001", "number": 1, "status": "checkpoint", "request": "Validated v4.3.0 scientific artifact import", "resource_envelope": {}, "started_at": now(), "ended_at": now(), "execution_control": {"stop_reason": "migration_import"}, "close_gate": {"status": "reference_only", "reason_codes": ["LEGACY_INTERPRETATION_NOT_ACTIVE"], "checked_at": now()}},
        ]},
        "orchestration_control": {
            "controller_epoch": 0,
            "lease": {"owner_id": None, "token_hash": None, "epoch": 0, "acquired_at": None, "heartbeat_at": None, "expires_at": None, "duration_minutes": 20},
            "last_bootstrap_at": None, "last_audit_path": None,
            "migration_handoff": {"status": "awaiting_human_start", "created_at": now(), "accepted_at": None, "accepted_round_id": None},
        },
        "id_counters": {
            "description_node": stage_counts["description"], "grouping_node": stage_counts["grouping"], "operator_node": stage_counts["analysis"], "interpretation_node": 0,
            "group": group_max, "evidence": evidence_max, "finding": max_entity_counter(source_state, "finding"), "hypothesis": max_entity_counter(source_state, "hypothesis"), "question": max_entity_counter(source_state, "question"), "relation": max_entity_counter(source_state, "relation"), "request": max_entity_counter(source_state, "request"), "scope": max_entity_counter(source_state, "scope"), "salience_event": max(max_entity_counter(source_state, "salience_event"), len(evidence_digests)),
        },
        "execution_graph": {"nodes": imported_nodes, "edges": edges},
        "indices": {
            "coverage": {"path": str((indices_root / 'coverage_index.json').resolve())},
            "group": {"registry_path": str(group_registry.resolve()), "matrix_shards": [{"path": str(path.resolve())} for path in matrix], "by_node": group_by_node, "group_count": len(registry_rows), "active_group_count": active_group_count, "deprioritized_group_count": deprioritized_group_count},
            "evidence_digest": {"path": str((indices_root / 'evidence_digest.jsonl').resolve()), "count": len(evidence_digests)},
            "salience": {"view_path": str((indices_root / 'salience_view.jsonl').resolve()), "history_path": str((indices_root / 'salience_history.jsonl').resolve())},
            "questions": {"path": str((indices_root / 'question_ledger.jsonl').resolve()), "count": 0}, "relations": {"path": str((indices_root / 'relation_index.jsonl').resolve()), "count": 0}, "findings": {"path": str((indices_root / 'finding_ledger.jsonl').resolve()), "count": 0}, "hypotheses": {"path": str((indices_root / 'hypothesis_ledger.jsonl').resolve()), "count": 0}, "requests": {"path": str((indices_root / 'analysis_request_ledger.jsonl').resolve()), "count": 0},
        },
        "history": [{"timestamp": now(), "action": "v430_validated_import", "source_run_root": str(source), "included_node_count": len(imported_nodes), "excluded_node_count": plan["excluded_node_count"]}], "updated_at": now(),
    }
    state_path = target / "state.json"; write_json(state_path, state)
    summaries = target / "summaries"; summaries.mkdir()
    status_counts = defaultdict(int)
    for node in imported_nodes: status_counts[node["status"]] += 1
    write_json(summaries / "state_summary.json", {"schema_version": "2.0.0", "run": {"run_id": plan["new_run_id"], "project": state["run"].get("project"), "input": str(input_target), "endpoint": state["run"].get("endpoint"), "higher_is_better": state["run"].get("higher_is_better"), "row_count": state["run"].get("row_count"), "profile_id": state["run"].get("profile_id")}, "round_control": {"active_round_id": None, "next_round_number": 2, "rounds": [{"round_id": "RND0001", "status": "checkpoint"}]}, "node_count": len(imported_nodes), "status_counts": dict(status_counts), "evidence_count": len(evidence_digests), "migration_handoff": "awaiting_human_start", "migration_baseline": plan["migration_baseline"], "updated_at": now()})
    write_json(summaries / "orchestrator_brief.json", {"schema_version": "1.0.0", "run_id": plan["new_run_id"], "state_path": str(state_path), "active_round_id": None, "required_control_action": [{"code": "MIGRATION_HANDOFF_REQUIRED", "blocking": True, "next_round_id": "RND0002", "reason": "EXPLICIT_HUMAN_START_REQUIRED"}], "scientific_decision": {"code": "NONE_UNTIL_MIGRATION_HANDOFF", "candidate_question_ids": []}, "updated_at": now()})
    write_json(migration_root / "imported_artifact_manifest.json", {"schema_version": "1.0.0", "artifacts": artifact_manifest, "created_at": now()})
    return verify(target)


def dag_valid(state: dict[str, Any]) -> tuple[bool, str | None]:
    ordered, errors = topological_nodes(state.get("execution_graph", {}).get("nodes", [])); return len(ordered) == len(state.get("execution_graph", {}).get("nodes", [])) and not errors, "; ".join(errors) if errors else None


def verify(target: Path) -> dict[str, Any]:
    state_path = target / "state.json"
    if not state_path.is_file(): raise FileNotFoundError(state_path)
    state = read_json(state_path); checks: list[dict[str, Any]] = []
    def add(code: str, passed: bool, detail: Any = None) -> None: checks.append({"code": code, "passed": bool(passed), "detail": detail})
    add("STATE_VERSION", state.get("conductor_version") == "4.3.1" and state.get("schema_version") == "2.1.0")
    valid, detail = dag_valid(state); add("DAG_VALID", valid, detail)
    ids = [node["node_id"] for node in state["execution_graph"]["nodes"]]; add("NODE_IDS_UNIQUE", len(ids) == len(set(ids)))
    missing = []
    for node in state["execution_graph"]["nodes"]:
        if node["status"] != "succeeded": continue
        for artifact in node.get("artifacts") or []:
            path = Path(str(artifact.get("resolved_path") or ""))
            if not path.is_file(): missing.append({"node_id": node["node_id"], "path": str(path)})
    add("IMPORTED_ARTIFACTS_EXIST", not missing, missing)
    grouping_nodes = [node for node in state["execution_graph"]["nodes"] if node.get("stage") == "grouping"]
    group_index = state.get("indices", {}).get("group", {})
    registry_path = Path(str(group_index.get("registry_path") or ""))
    indexed_grouping_nodes = set((group_index.get("by_node") or {}).keys())
    add(
        "GROUP_INDEX_AVAILABLE",
        not grouping_nodes or (registry_path.is_file() and all(node["node_id"] in indexed_grouping_nodes for node in grouping_nodes)),
        {"registry_path": str(registry_path), "indexed_grouping_nodes": len(indexed_grouping_nodes), "grouping_nodes": len(grouping_nodes)},
    )
    add("SOURCE_IS_DISTINCT", Path(state["run"]["migration_provenance"]["source_run_root"]).resolve() != target.resolve())
    add("MIGRATION_HANDOFF_PENDING", state["round_control"]["active_round_id"] is None and state["round_control"]["next_round_number"] == 2 and state.get("orchestration_control", {}).get("migration_handoff", {}).get("status") == "awaiting_human_start")
    add("NO_POST_MIGRATION_NODES", all(node.get("round_id") == "RND0001" and node.get("status") == "succeeded" for node in state["execution_graph"]["nodes"]))
    add("BOUNDED_SUMMARIES_EXIST", all((target / "summaries" / name).is_file() for name in ["state_summary.json", "orchestrator_brief.json"]))
    result = {"schema_version": "1.0.0", "target_run_root": str(target), "status": "pass" if all(item["passed"] for item in checks) else "fail", "checks": checks, "created_at": now()}
    migration = target / "migration" / "v430_import"; migration.mkdir(parents=True, exist_ok=True); write_json(migration / "verification.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="One-time deterministic CONDUCTOR v4.3.0 to v4.3.1 Run migration")
    sub = parser.add_subparsers(dest="command", required=True)
    scan_parser = sub.add_parser("scan"); scan_parser.add_argument("--source-run-root", required=True); scan_parser.add_argument("--target-run-root", required=True); scan_parser.add_argument("--new-run-id")
    apply_parser = sub.add_parser("apply"); apply_parser.add_argument("--plan", required=True); apply_parser.add_argument("--approve", action="store_true")
    verify_parser = sub.add_parser("verify"); verify_parser.add_argument("--target-run-root", required=True)
    args = parser.parse_args()
    if args.command == "scan":
        source = Path(args.source_run_root).expanduser().resolve(); target = Path(args.target_run_root).expanduser().resolve()
        if source == target or source in target.parents: raise ValueError("Target must be a new sibling location, not the source or a child of source")
        plan_root, plan = scan(source, target, args.new_run_id); print(json.dumps({"plan_dir": str(plan_root), "plan_path": str(plan_root / 'migration_plan.json'), "applicable": plan["applicable"], "included_node_count": plan["included_node_count"], "excluded_node_count": plan["excluded_node_count"], "errors": plan["errors"]}, ensure_ascii=False, indent=2)); return 0 if plan["applicable"] else 1
    if args.command == "apply":
        if not args.approve: raise ValueError("apply requires --approve after explicit human review")
        result = apply(Path(args.plan).expanduser().resolve()); print(json.dumps(result, ensure_ascii=False, indent=2)); return 0 if result["status"] == "pass" else 1
    result = verify(Path(args.target_run_root).expanduser().resolve()); print(json.dumps(result, ensure_ascii=False, indent=2)); return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    try: raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr); raise SystemExit(2)
