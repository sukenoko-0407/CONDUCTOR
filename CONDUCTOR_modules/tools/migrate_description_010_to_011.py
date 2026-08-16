from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SOURCE_VERSION = "0.1.0"
TARGET_VERSION = "0.1.1"
STATE_SCHEMA = "2.0.0"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in rows), encoding="utf-8")


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def value_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def find_workspace() -> Path:
    script = Path(__file__).resolve()
    for candidate in [script.parent, *script.parents, Path.cwd(), *Path.cwd().parents]:
        if (candidate / "CONDUCTOR_modules" / "catalog" / "catalog.json").is_file() and (candidate / ".claude" / "skills").is_dir():
            return candidate
    raise RuntimeError("CONDUCTOR workspace could not be located")


def target_catalog(workspace: Path) -> dict[str, dict[str, Any]]:
    value = read_json(workspace / "CONDUCTOR_modules" / "catalog" / "catalog.json")
    if value.get("conductor_version") != TARGET_VERSION:
        raise ValueError(f"Installed Catalog must be CONDUCTOR {TARGET_VERSION}")
    return {item["capability_id"]: item for item in value.get("capabilities") or []}


def successful_attempt(node: dict[str, Any]) -> dict[str, Any]:
    attempts = [item for item in node.get("execution_attempts") or [] if item.get("status") == "succeeded"]
    if not attempts:
        raise ValueError(f"Succeeded Description Node has no successful attempt: {node.get('node_id')}")
    committed = node.get("committed_attempt_id")
    if committed:
        match = next((item for item in attempts if item.get("attempt_id") == committed), None)
        if match:
            return match
    return attempts[-1]


def artifact_path(node: dict[str, Any], attempt: dict[str, Any], capability: dict[str, Any], kind: str) -> Path:
    names = {
        "description": f"{capability['output']['basename']}.csv",
        "manifest": "description_manifest.json",
        "warnings": "warnings.json",
    }
    for artifact in node.get("artifacts") or []:
        if artifact.get("type") == kind and artifact.get("resolved_path"):
            candidate = Path(artifact["resolved_path"]).resolve()
            if candidate.is_file():
                return candidate
    candidate = Path(node["output_dir"]) / "attempts" / attempt["attempt_id"] / names[kind]
    return candidate.resolve()


def csv_identity(path: Path) -> dict[str, Any]:
    row_count = 0
    compound_ids: list[str] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "compound_id" not in reader.fieldnames:
            raise ValueError(f"Description CSV lacks compound_id: {path}")
        for row in reader:
            row_count += 1
            compound_ids.append(str(row.get("compound_id") or ""))
    if any(not value for value in compound_ids) or len(compound_ids) != len(set(compound_ids)):
        raise ValueError(f"Description CSV compound IDs must be non-empty and unique: {path}")
    return {"row_count": row_count, "compound_id_hash": value_hash(compound_ids)}


def scan_source(source_root: Path, workspace: Path, input_override: Path | None = None) -> dict[str, Any]:
    source_root = source_root.resolve()
    state_path = source_root / "state.json"
    if not state_path.is_file():
        raise FileNotFoundError(state_path)
    state = read_json(state_path)
    if state.get("schema_version") != STATE_SCHEMA or state.get("conductor_version") != SOURCE_VERSION:
        raise ValueError(f"Source must be CONDUCTOR {SOURCE_VERSION} State schema {STATE_SCHEMA}")
    source_input = (input_override or Path(state["run"]["input"])).resolve()
    if not source_input.is_file():
        raise FileNotFoundError(f"Input CSV referenced by the source Run is unavailable: {source_input}")
    if sha_file(source_input) != state["run"]["input_hash"]:
        raise ValueError("Input CSV hash does not match the source Run")
    capabilities = target_catalog(workspace)
    entries: list[dict[str, Any]] = []
    seen_signatures: set[str] = set()
    reference_identity: dict[str, Any] | None = None
    for node in sorted(state["execution_graph"]["nodes"], key=lambda item: (item.get("capability_id", ""), item.get("node_id", ""))):
        if node.get("stage") != "description" or node.get("status") != "succeeded":
            continue
        capability_id = str(node.get("capability_id") or "")
        capability = capabilities.get(capability_id)
        if not capability or capability.get("stage") != "description":
            raise ValueError(f"Target Catalog has no compatible Description capability: {capability_id}")
        attempt = successful_attempt(node)
        vector_path = artifact_path(node, attempt, capability, "description")
        manifest_path = artifact_path(node, attempt, capability, "manifest")
        if not vector_path.is_file() or not manifest_path.is_file():
            raise FileNotFoundError(f"Description artifact is incomplete for {node['node_id']}")
        manifest = read_json(manifest_path)
        if manifest.get("schema_version") != "2.0.0" or manifest.get("artifact_stage") != "description":
            raise ValueError(f"Unsupported Description manifest: {manifest_path}")
        if str(manifest.get("capability_id")) != capability_id:
            raise ValueError(f"Description manifest capability mismatch: {node['node_id']}")
        manifest_metric = str(manifest.get("natural_metric") or "")
        allowed_metrics = {str(item) for item in capability.get("allowed_metrics") or []}
        if not manifest.get("value_semantics") or manifest_metric not in allowed_metrics:
            raise ValueError(
                f"Description semantics or Metric is not accepted by the 0.1.1 capability: "
                f"{capability_id} ({manifest.get('value_semantics')}, {manifest_metric})"
            )
        identity = csv_identity(vector_path)
        if identity["row_count"] != int(state["run"].get("row_count") or identity["row_count"]):
            raise ValueError(f"Description row count differs from the source Run: {node['node_id']}")
        if reference_identity is None:
            reference_identity = identity
        elif identity != reference_identity:
            raise ValueError(f"Description compound set or order differs across artifacts: {node['node_id']}")
        parameters = {**(capability.get("default_parameters") or {}), **(node.get("parameters") or {})}
        signature = value_hash({"capability_id": capability_id, "dependencies": [], "parameters": parameters, "role": str(parameters.get("role") or "")})
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        warnings_path = artifact_path(node, attempt, capability, "warnings")
        entries.append(
            {
                "capability_id": capability_id,
                "skill_name": capability["skill_name"],
                "source_node_id": node["node_id"],
                "source_attempt_id": attempt["attempt_id"],
                "source_vector_path": str(vector_path),
                "source_manifest_path": str(manifest_path),
                "source_warnings_path": str(warnings_path) if warnings_path.is_file() else None,
                "vector_sha256": sha_file(vector_path),
                "manifest_sha256": sha_file(manifest_path),
                "parameters": parameters,
                "analysis_signature": signature,
                "identity": identity,
            }
        )
    if not entries:
        raise ValueError("Source Run contains no successful Description Node")
    return {
        "schema_version": "1.0.0",
        "migration": "description-only-0.1.0-to-0.1.1",
        "source_run_root": str(source_root),
        "source_state_path": str(state_path.resolve()),
        "source_run_id": state["run"]["run_id"],
        "source_project": state["run"]["project"],
        "input": str(source_input),
        "input_hash": state["run"]["input_hash"],
        "endpoint": state["run"]["endpoint"],
        "higher_is_better": bool(state["run"]["higher_is_better"]),
        "parallel_limit": int(state["run"].get("parallel_limit") or 1),
        "row_count": int(state["run"].get("row_count") or reference_identity["row_count"]),
        "profile_id": state["run"].get("profile_id"),
        "description_count": len(entries),
        "descriptions": entries,
        "excluded_stages": ["clustering", "analysis", "interpretation"],
        "scanned_at": utc_now(),
    }


def index_paths(root: Path) -> dict[str, Any]:
    return {
        "coverage": {"path": str((root / "indices" / "coverage.json").resolve())},
        "operator_results": {"path": str((root / "indices" / "operator_results.jsonl").resolve()), "count": 0},
        "insights": {"path": str((root / "indices" / "insight_ledger.jsonl").resolve()), "count": 0},
        "next_actions": {"path": str((root / "indices" / "next_action_ledger.jsonl").resolve()), "count": 0},
        "clusters": {"registry_path": str((root / "clusters" / "cluster_registry.csv").resolve()), "matrix_paths": [], "cluster_count": 0},
    }


def initialize_indices(root: Path, indices: dict[str, Any]) -> None:
    write_jsonl(Path(indices["operator_results"]["path"]), [])
    write_jsonl(Path(indices["insights"]["path"]), [])
    write_jsonl(Path(indices["next_actions"]["path"]), [])
    write_csv(
        Path(indices["clusters"]["registry_path"]),
        ["cluster_id", "local_cluster_id", "source_node_id", "clustering_capability_id", "cluster_label", "compound_count", "membership_path", "status", "created_at"],
        [],
    )


def migrated_manifest(source: dict[str, Any], capability: dict[str, Any], target: dict[str, str], input_path: Path) -> dict[str, Any]:
    manifest = read_json(Path(source["source_manifest_path"]))
    manifest.update(
        {
            "conductor_version": TARGET_VERSION,
            "run_id": target["run_id"],
            "node_id": target["node_id"],
            "attempt_id": "ATT0001",
            "skill_name": capability["skill_name"],
            "skill_version": capability["version"],
            "input": str(input_path),
            "input_hash": target["input_hash"],
            "created_at": utc_now(),
            "migration": {
                "kind": "description-only",
                "source_conductor_version": SOURCE_VERSION,
                "source_run_id": target["source_run_id"],
                "source_node_id": source["source_node_id"],
                "source_attempt_id": source["source_attempt_id"],
                "source_vector_sha256": source["vector_sha256"],
                "source_manifest_sha256": source["manifest_sha256"],
            },
        }
    )
    return manifest


def write_views(root: Path, state: dict[str, Any]) -> None:
    description_count = len(state["execution_graph"]["nodes"])
    summary = {
        "schema_version": "2.0.0",
        "run": {key: state["run"].get(key) for key in ("run_id", "project", "input", "endpoint", "higher_is_better", "row_count", "parallel_limit")},
        "active_round_id": None,
        "next_round_number": 2,
        "node_count": description_count,
        "status_counts": {"succeeded": description_count},
        "stage_counts": {"description": {"succeeded": description_count}, "clustering": {}, "analysis": {}, "interpretation": {}},
        "cluster_count": 0,
        "clustering_selection_counts": {},
        "clustering_quality_flags": {},
        "operator_result_count": 0,
        "priority_insights": [],
        "open_next_actions": [],
        "time_budget": {"status": "no_active_round", "remaining_minutes": 0, "reserve_minutes": 0},
        "interpretation_gate": {"status": "no_active_round"},
        "updated_at": state["updated_at"],
    }
    brief = {
        "schema_version": "2.0.0",
        "run_id": state["run"]["run_id"],
        "active_round_id": None,
        "required_control_action": {"code": "START_NEXT_ROUND", "next_round_id": "RND0002"},
        "facts": summary,
        "scientific_decision": None,
        "generated_at": utc_now(),
    }
    write_json(root / "summaries" / "state_summary.json", summary)
    write_json(root / "summaries" / "orchestrator_brief.json", brief)
    write_json(
        Path(state["indices"]["coverage"]["path"]),
        {
            "schema_version": "2.0.0",
            "cells": [
                {
                    "node_id": node["node_id"],
                    "capability_id": node["capability_id"],
                    "stage": "description",
                    "phase": "basic_compute",
                    "requested_round_id": "RND0001",
                    "execution_round_id": "RND0001",
                    "status": "succeeded",
                    "dependencies": [],
                    "scope_mode": None,
                    "target_cluster": None,
                    "signature": node["analysis_signature"],
                }
                for node in state["execution_graph"]["nodes"]
            ],
            "updated_at": state["updated_at"],
        },
    )


def apply_migration(scan: dict[str, Any], target_root: Path, workspace: Path, target_run_id: str, project: str, input_path: Path) -> Path:
    target_root = target_root.resolve()
    source_root = Path(scan["source_run_root"]).resolve()
    if target_root.is_relative_to(source_root) or source_root.is_relative_to(target_root):
        raise ValueError("Source and target Run roots must be separate, non-nested directories")
    if target_root.exists():
        raise FileExistsError(f"Target Run root already exists: {target_root}")
    target_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target_root.name}.migration-", dir=target_root.parent)).resolve()
    capabilities = target_catalog(workspace)
    promoted = False
    try:
        indices = index_paths(staging)
        initialize_indices(staging, indices)
        nodes: list[dict[str, Any]] = []
        now = utc_now()
        for number, source in enumerate(scan["descriptions"], 1):
            capability = capabilities[source["capability_id"]]
            node_id = f"ND{number:06d}"
            attempt_id = "ATT0001"
            attempt_dir = staging / "description" / capability["skill_name"] / node_id / "attempts" / attempt_id
            attempt_dir.mkdir(parents=True, exist_ok=True)
            vector_name = f"{capability['output']['basename']}.csv"
            vector_path = attempt_dir / vector_name
            shutil.copy2(Path(source["source_vector_path"]), vector_path)
            if sha_file(vector_path) != source["vector_sha256"]:
                raise ValueError(f"Copied Description hash mismatch: {source['capability_id']}")
            target_context = {
                "run_id": target_run_id,
                "node_id": node_id,
                "input_hash": scan["input_hash"],
                "source_run_id": scan["source_run_id"],
            }
            manifest = migrated_manifest(source, capability, target_context, input_path)
            manifest_path = attempt_dir / "description_manifest.json"
            write_json(manifest_path, manifest)
            warnings_path = attempt_dir / "warnings.json"
            if source.get("source_warnings_path"):
                shutil.copy2(Path(source["source_warnings_path"]), warnings_path)
            else:
                write_json(warnings_path, {"warnings": manifest.get("warnings") or [], "errors": manifest.get("errors") or []})
            parameters = dict(source["parameters"])
            event = {
                "schema_version": "2.0.0",
                "project": project,
                "run_id": target_run_id,
                "round_id": "RND0001",
                "node_id": node_id,
                "attempt_id": attempt_id,
                "capability_id": source["capability_id"],
                "skill_name": capability["skill_name"],
                "status": "succeeded",
                "input_hash": scan["input_hash"],
                "config_hash": value_hash({"parameters": parameters, "migration": "description-only"}),
                "configuration": parameters,
                "artifacts": [
                    {"type": "description", "path": vector_name, "sha256": sha_file(vector_path)},
                    {"type": "manifest", "path": manifest_path.name, "sha256": sha_file(manifest_path)},
                    {"type": "warnings", "path": warnings_path.name, "sha256": sha_file(warnings_path)},
                ],
                "warnings": ["Description artifact imported unchanged from CONDUCTOR 0.1.0"],
                "started_at": now,
                "finished_at": now,
            }
            event_path = attempt_dir / "execution_event.json"
            write_json(event_path, event)
            artifacts = [
                {**item, "resolved_path": str((attempt_dir / item["path"]).resolve())}
                for item in event["artifacts"]
            ]
            output_dir = staging / "description" / capability["skill_name"] / node_id
            nodes.append(
                {
                    "node_id": node_id,
                    "stage": "description",
                    "capability_id": source["capability_id"],
                    "skill_name": capability["skill_name"],
                    "round_id": "RND0001",
                    "requested_round_id": "RND0001",
                    "execution_round_id": "RND0001",
                    "phase": "basic_compute",
                    "dependencies": [],
                    "parameters": parameters,
                    "analysis_signature": source["analysis_signature"],
                    "selection_basis": {"reason": "0.1.0 Description-only migration", "source": "migration"},
                    "status": "succeeded",
                    "human_approval": "not_required",
                    "execution_attempts": [{"attempt_id": attempt_id, "status": "succeeded", "started_at": now, "finished_at": now, "event_path": str(event_path.resolve())}],
                    "current_attempt_id": None,
                    "committed_attempt_id": attempt_id,
                    "output_dir": str(output_dir.resolve()),
                    "final_output_dir": str(attempt_dir.resolve()),
                    "artifacts": artifacts,
                    "input_hash": scan["input_hash"],
                    "config_hash": event["config_hash"],
                    "created_at": now,
                    "finished_at": now,
                    "migration_provenance": manifest["migration"],
                }
            )
        high_cost = [
            capability_id
            for capability_id in ("D016", "D019", "D020")
            if capability_id in capabilities and capabilities[capability_id].get("cost", {}).get("human_approval_required")
        ]
        imported_ids = {node["capability_id"] for node in nodes}
        bundle_status = "satisfied_by_description_migration" if set(high_cost).issubset(imported_ids) else "pending"
        round_record = {
            "round_id": "RND0001",
            "status": "closed",
            "request": "CONDUCTOR 0.1.0で成功済みのDescriptionを0.1.1へ引き継ぐ。",
            "started_at": now,
            "ended_at": now,
            "plans": {"basic_compute": True, "initial_global": False, "initial_local": False},
            "execution_control": {
                "walltime_minutes": 0,
                "deadline_at": now,
                "interpretation_reserve_minutes": 0,
                "parallel_limit": scan["parallel_limit"],
                "max_additional_nodes": 0,
                "interpretation_iterations": 0,
                "additional_nodes_planned": 0,
            },
            "stop_reason": "version_migration_during_basic_compute",
            "completion_state": "partial_basic_compute",
            "migration_baseline": True,
            "interpretation_exception": {"required": False, "reason": "Description-only migration baseline; no Operator result was imported."},
        }
        state = {
            "schema_version": STATE_SCHEMA,
            "conductor_version": TARGET_VERSION,
            "revision": 1,
            "run": {
                "run_id": target_run_id,
                "project": project,
                "run_root": str(staging),
                "input": str(input_path),
                "input_hash": scan["input_hash"],
                "endpoint": scan["endpoint"],
                "higher_is_better": scan["higher_is_better"],
                "parallel_limit": scan["parallel_limit"],
                "row_count": scan["row_count"],
                "profile_id": scan.get("profile_id") or "comprehensive-multiround-beta",
                "high_cost_bundle": {"status": bundle_status, "capability_ids": high_cost},
                "migration": {"kind": "description-only", "source_version": SOURCE_VERSION, "source_run_root": scan["source_run_root"], "source_run_id": scan["source_run_id"]},
            },
            "round_control": {"active_round_id": None, "next_round_number": 2, "rounds": [round_record]},
            "orchestration_control": {"lease": {"owner_id": None, "token_hash": None, "expires_at": None, "heartbeat_at": None, "duration_minutes": 30}, "controller_epoch": 0},
            "counters": {"description_node": len(nodes), "clustering_node": 0, "analysis_node": 0, "interpretation_node": 0, "cluster": 0, "insight": 0, "action": 0},
            "execution_graph": {"nodes": nodes, "edges": []},
            "indices": indices,
            "history": [{"at": now, "action": "description_migration_applied", "source_run_id": scan["source_run_id"], "description_count": len(nodes), "round_id": "RND0001", "completion_state": "partial_basic_compute"}],
            "created_at": now,
            "updated_at": now,
        }
        write_json(staging / "state.json", state)
        write_json(staging / "rounds" / "RND0001" / "round_manifest.json", round_record)
        (staging / "rounds" / "RND0001" / "round_request.md").write_text("# RND0001 Request\n\n0.1.0で成功済みのDescriptionを0.1.1へ引き継ぐ。\n", encoding="utf-8")
        write_views(staging, state)
        validate_target(scan, staging, workspace)
        staging.replace(target_root)
        promoted = True
        rewrite_target_paths(target_root)
        validate_target(scan, target_root, workspace)
        return target_root / "state.json"
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        if promoted:
            shutil.rmtree(target_root, ignore_errors=True)
        raise


def rewrite_target_paths(target_root: Path) -> None:
    state_path = target_root / "state.json"
    state = read_json(state_path)
    old_root = Path(state["run"]["run_root"])
    state["run"]["run_root"] = str(target_root)
    for section in state["indices"].values():
        for key, value in list(section.items()):
            if isinstance(value, str):
                section[key] = str(target_root / Path(value).relative_to(old_root))
            elif isinstance(value, list):
                section[key] = [str(target_root / Path(item).relative_to(old_root)) for item in value]
    for node in state["execution_graph"]["nodes"]:
        for key in ("output_dir", "final_output_dir"):
            node[key] = str(target_root / Path(node[key]).relative_to(old_root))
        for attempt in node["execution_attempts"]:
            if attempt.get("event_path"):
                attempt["event_path"] = str(target_root / Path(attempt["event_path"]).relative_to(old_root))
        for artifact in node.get("artifacts") or []:
            artifact["resolved_path"] = str(target_root / Path(artifact["resolved_path"]).relative_to(old_root))
    state["updated_at"] = utc_now()
    write_json(state_path, state)
    write_views(target_root, state)


def validate_target(scan: dict[str, Any], target_root: Path, workspace: Path) -> dict[str, Any]:
    state_path = target_root / "state.json"
    if not state_path.is_file():
        raise FileNotFoundError(state_path)
    state = read_json(state_path)
    checks: list[dict[str, Any]] = []

    def check(name: str, condition: bool, detail: Any = None) -> None:
        checks.append({"name": name, "status": "pass" if condition else "fail", "detail": detail})
        if not condition:
            raise ValueError(f"Migration verification failed: {name}: {detail}")

    check("TARGET_VERSION", state.get("conductor_version") == TARGET_VERSION, state.get("conductor_version"))
    check("TARGET_SCHEMA", state.get("schema_version") == STATE_SCHEMA, state.get("schema_version"))
    check("NO_ACTIVE_ROUND", state["round_control"].get("active_round_id") is None)
    check("NEXT_ROUND_IS_2", state["round_control"].get("next_round_number") == 2)
    rounds = state["round_control"].get("rounds") or []
    check("ROUND1_PARTIAL_BASIC_CLOSED", len(rounds) == 1 and rounds[0].get("round_id") == "RND0001" and rounds[0].get("status") == "closed" and rounds[0].get("completion_state") == "partial_basic_compute")
    nodes = state["execution_graph"].get("nodes") or []
    check("DESCRIPTION_ONLY", all(node.get("stage") == "description" for node in nodes), [node.get("stage") for node in nodes])
    check("ALL_IMPORTED_DESCRIPTIONS_SUCCEEDED", all(node.get("status") == "succeeded" for node in nodes))
    check("DESCRIPTION_COUNT", len(nodes) == int(scan["description_count"]), {"expected": scan["description_count"], "actual": len(nodes)})
    check("NO_DAG_EDGES", not state["execution_graph"].get("edges"))
    check("NO_CLUSTER_OR_RESULT_INDEX", state["indices"]["clusters"].get("cluster_count") == 0 and state["indices"]["operator_results"].get("count") == 0)
    source_hashes = {item["capability_id"] + ":" + item["analysis_signature"]: item["vector_sha256"] for item in scan["descriptions"]}
    capabilities = target_catalog(workspace)
    for node in nodes:
        capability = capabilities[node["capability_id"]]
        vector_path = Path(node["output_dir"]) / "attempts" / "ATT0001" / f"{capability['output']['basename']}.csv"
        manifest_path = vector_path.parent / "description_manifest.json"
        key = node["capability_id"] + ":" + node["analysis_signature"]
        check(f"VECTOR_HASH_{node['node_id']}", vector_path.is_file() and sha_file(vector_path) == source_hashes.get(key), str(vector_path))
        manifest = read_json(manifest_path)
        check(f"MANIFEST_PROVENANCE_{node['node_id']}", manifest.get("conductor_version") == TARGET_VERSION and manifest.get("migration", {}).get("source_conductor_version") == SOURCE_VERSION)
        check(
            f"MANIFEST_METRIC_{node['node_id']}",
            manifest.get("natural_metric") in set(capability.get("allowed_metrics") or []),
            manifest.get("natural_metric"),
        )
    try:
        import jsonschema

        schema = read_json(workspace / "CONDUCTOR_modules" / "schemas" / "state.schema.json")
        jsonschema.validate(state, schema)
        checks.append({"name": "STATE_SCHEMA_VALIDATION", "status": "pass", "detail": None})
    except ImportError:
        checks.append({"name": "STATE_SCHEMA_VALIDATION", "status": "warning", "detail": "jsonschema unavailable"})
    status = "pass" if all(item["status"] != "fail" for item in checks) else "fail"
    return {"schema_version": "1.0.0", "status": status, "source_run_id": scan["source_run_id"], "target_run_id": state["run"]["run_id"], "description_count": len(nodes), "checks": checks, "verified_at": utc_now()}


def render_report(report: dict[str, Any]) -> str:
    lines = ["# Description Migration Report", "", f"- Status: `{report['status']}`", f"- Source Run: `{report['source_run_id']}`", f"- Target Run: `{report['target_run_id']}`", f"- Imported Description Nodes: `{report['description_count']}`", "", "| Check | Status | Detail |", "|---|---|---|"]
    for item in report["checks"]:
        detail = json.dumps(item.get("detail"), ensure_ascii=False, default=str) if item.get("detail") is not None else "-"
        lines.append(f"| {item['name']} | {item['status']} | {detail} |")
    lines.extend(["", "RND0001はDescription成功後、基本計算途中でVersion migrationにより終了したRoundとして閉じています。RND0002は作成していません。", ""])
    return "\n".join(lines)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Migrate only successful CONDUCTOR 0.1.0 Description artifacts into a new 0.1.1 Run.")
    sub = value.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan")
    scan.add_argument("--source-run-root", required=True)
    scan.add_argument("--input", help="Replacement path to the unchanged input CSV; its hash must match.")
    apply = sub.add_parser("apply")
    apply.add_argument("--source-run-root", required=True)
    apply.add_argument("--target-run-root", required=True)
    apply.add_argument("--target-run-id")
    apply.add_argument("--project")
    apply.add_argument("--input", help="Replacement path to the unchanged input CSV; its hash must match.")
    verify = sub.add_parser("verify")
    verify.add_argument("--source-run-root", required=True)
    verify.add_argument("--target-run-root", required=True)
    verify.add_argument("--input", help="Replacement path to the unchanged input CSV; its hash must match.")
    return value


def main() -> int:
    args = parser().parse_args()
    workspace = find_workspace()
    input_override = Path(args.input).resolve() if args.input else None
    scan = scan_source(Path(args.source_run_root), workspace, input_override)
    if args.command == "scan":
        print(json.dumps(scan, ensure_ascii=False, indent=2))
        return 0
    if args.command == "apply":
        target_root = Path(args.target_run_root).resolve()
        target_run_id = args.target_run_id or target_root.name
        project = args.project or scan["source_project"]
        input_path = input_override or Path(scan["input"])
        state_path = apply_migration(scan, target_root, workspace, target_run_id, project, input_path)
        report = validate_target(scan, target_root, workspace)
        report_dir = target_root / "migration" / stamp()
        write_json(report_dir / "migration_report.json", report)
        (report_dir / "migration_report.md").write_text(render_report(report), encoding="utf-8")
        print(json.dumps({"status": "pass", "state": str(state_path), "report_dir": str(report_dir), "next_round_id": "RND0002", "round_started": False}, ensure_ascii=False, indent=2))
        return 0
    report = validate_target(scan, Path(args.target_run_root).resolve(), workspace)
    report_dir = Path(args.target_run_root).resolve() / "migration" / stamp()
    write_json(report_dir / "migration_report.json", report)
    (report_dir / "migration_report.md").write_text(render_report(report), encoding="utf-8")
    print(json.dumps({**report, "report_dir": str(report_dir)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
