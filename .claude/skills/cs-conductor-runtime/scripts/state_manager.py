from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import re
import secrets
import shutil
import sys
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator


SKILL_DIR = Path(__file__).resolve().parents[1]
CONDUCTOR_VERSION = "4.3.1"
STATE_SCHEMA_VERSION = "2.1.0"
SUMMARY_SCHEMA_VERSION = "2.0.0"
DEFAULT_LEASE_MINUTES = 20
SUMMARY_LIMIT = 20
TERMINAL_STATUSES = {"succeeded", "failed", "unavailable", "waived", "not_applicable", "skipped"}
SUCCESS_LIKE_STATUSES = {"succeeded", "waived", "not_applicable"}
STAGE_COUNTER = {
    "description": ("description_node", "ND"),
    "grouping": ("grouping_node", "NG"),
    "analysis": ("operator_node", "NO"),
    "interpretation": ("interpretation_node", "NI"),
}
ENTITY_COUNTER = {
    "group": ("group", "G", 6),
    "evidence": ("evidence", "E", 6),
    "finding": ("finding", "F", 4),
    "hypothesis": ("hypothesis", "H", 4),
    "question": ("question", "Q", 4),
    "relation": ("relation", "REL", 4),
    "request": ("request", "REQ", 4),
    "scope": ("scope", "SCP", 4),
    "salience_event": ("salience_event", "SEV", 4),
}
GROUP_REGISTRY_FIELDS = [
    "group_id", "local_group_id", "group_label", "grouping_capability_id", "grouping_skill_name",
    "source_node_id", "source_description_id", "source_description_node_id", "source_grouping_node_ids",
    "membership_semantics", "compound_count", "sample_fraction", "endpoint_variance", "activity_blind",
    "status", "membership_artifact", "node_membership_artifact", "definition_json", "created_at",
    "deprioritize_reason", "deprioritized_at",
]
TRANSIENT_PARAMETER_KEYS = {
    "output_dir", "project", "run_id", "node_id", "conductor", "overwrite", "input", "description",
    "membership", "state", "evidence", "catalog", "previous_interpretation", "id_reservation",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_id_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def timestamp_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def bounded(values: Iterable[Any], limit: int = SUMMARY_LIMIT) -> list[Any]:
    materialized = list(values)
    return materialized[-limit:]


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def find_workspace() -> Path:
    candidates = [SKILL_DIR, *SKILL_DIR.parents, Path.cwd(), *Path.cwd().parents]
    for candidate in candidates:
        if (candidate / ".claude" / "skills").is_dir() and (candidate / "CONDUCTOR_modules" / "catalog" / "catalog.json").is_file():
            return candidate
    raise RuntimeError("CONDUCTOR project root could not be located")


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def value_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    result = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"Expected object at {path}:{line_number}")
            result.append(value)
    return result


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def write_jsonl(path: Path, values: Iterable[dict[str, Any]]) -> None:
    text = "".join(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n" for value in values)
    atomic_write_text(path, text)


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    existing = read_jsonl(path)
    existing.append(value)
    write_jsonl(path, existing)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv_rows(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def validate_json(value: dict[str, Any], schema_name: str) -> None:
    try:
        import jsonschema
    except ImportError as exc:
        raise RuntimeError("jsonschema is required") from exc
    schema = read_json(SKILL_DIR / "schemas" / schema_name)
    jsonschema.validate(value, schema)


def validate_dag(state: dict[str, Any]) -> None:
    nodes = {node["node_id"] for node in state["execution_graph"]["nodes"]}
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    indegree = {node_id: 0 for node_id in nodes}
    for edge in state["execution_graph"]["edges"]:
        source, target = edge["source"], edge["target"]
        if source not in nodes or target not in nodes:
            raise ValueError(f"DAG edge references an unknown node: {source} -> {target}")
        adjacency[source].append(target)
        indegree[target] += 1
    queue = deque(node_id for node_id, count in indegree.items() if count == 0)
    visited = 0
    while queue:
        node_id = queue.popleft()
        visited += 1
        for target in adjacency[node_id]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if visited != len(nodes):
        raise ValueError("Execution graph must remain acyclic")


def validate_state(state: dict[str, Any]) -> None:
    validate_json(state, "state.schema.json")
    validate_dag(state)
    active = [item for item in state["round_control"]["rounds"] if item["status"] == "active"]
    if len(active) > 1:
        raise ValueError("Only one Round can be active")
    current_id = state["round_control"]["active_round_id"]
    if current_id is not None:
        current = next((item for item in state["round_control"]["rounds"] if item["round_id"] == current_id), None)
        if current is None or current["status"] not in {"active", "paused"}:
            raise ValueError("round_control.active_round_id must identify an active or paused Round")
        if active and active[0]["round_id"] != current_id:
            raise ValueError("round_control.active_round_id is inconsistent")
    elif active:
        raise ValueError("An active Round requires round_control.active_round_id")
    lease = state.get("orchestration_control", {}).get("lease") or {}
    if lease.get("token_hash") and not (lease.get("owner_id") and lease.get("expires_at")):
        raise ValueError("A claimed Orchestrator lease requires owner_id and expires_at")
    node_ids = [node["node_id"] for node in state["execution_graph"]["nodes"]]
    if len(node_ids) != len(set(node_ids)):
        raise ValueError("Node IDs must be unique")


@contextmanager
def state_lock(state_path: Path) -> Iterator[None]:
    lock_path = state_path.with_suffix(state_path.suffix + ".lock")
    descriptor: int | None = None
    try:
        descriptor = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(descriptor, f"pid={os.getpid()} created={utc_now()}".encode("utf-8"))
        yield
    except FileExistsError as exc:
        raise RuntimeError(f"State is locked by another writer: {lock_path}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
            lock_path.unlink(missing_ok=True)


def lease_is_live(state: dict[str, Any]) -> bool:
    lease = state.get("orchestration_control", {}).get("lease") or {}
    expires_at = parse_timestamp(lease.get("expires_at"))
    return bool(lease.get("token_hash") and expires_at and expires_at > datetime.now(timezone.utc))


def require_controller(state: dict[str, Any], args: argparse.Namespace) -> None:
    control = state.get("orchestration_control")
    if not control:
        raise ValueError("State has no v4.3.1 orchestration control; migrate the Run before mutation")
    token = getattr(args, "lease_token", None)
    lease = control.get("lease") or {}
    if not lease_is_live(state):
        raise ValueError("No live Orchestrator lease; run bootstrap first")
    if not token or token_hash(token) != lease.get("token_hash"):
        raise ValueError("This process does not own the Orchestrator lease")


def renew_lease(state: dict[str, Any], minutes: int | None = None) -> None:
    lease = state["orchestration_control"]["lease"]
    now = datetime.now(timezone.utc)
    duration = minutes or int(lease.get("duration_minutes") or DEFAULT_LEASE_MINUTES)
    lease["heartbeat_at"] = now.isoformat()
    lease["expires_at"] = (now + timedelta(minutes=duration)).isoformat()


def controller_mutation(state: dict[str, Any], args: argparse.Namespace) -> None:
    require_controller(state, args)
    renew_lease(state)
    handoff = (state.get("orchestration_control") or {}).get("migration_handoff") or {}
    if handoff.get("status") == "awaiting_human_start" and getattr(args, "command", None) != "round-start":
        raise ValueError("Migration handoff is awaiting an explicit human Round start; no other State mutation is allowed")
    scientific_expansion_commands = {"plan-basic", "plan-initial-global", "plan-initial-local", "plan-additional", "plan-deep-dive", "add"}
    if getattr(args, "command", None) in scientific_expansion_commands:
        time_status = round_time_status(state)
        if time_status["status"] in {"interpretation_reserve", "expired"}:
            raise ValueError(f"Scientific expansion is closed by Round time control: {time_status['status']}")


def add_lease_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--lease-token",
        help="Opaque token returned by bootstrap. Required for every State mutation after initialization.",
    )


def append_history(state: dict[str, Any], action: str, **details: Any) -> None:
    state["history"].append({"timestamp": utc_now(), "action": action, **details})


def write_state(path: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = utc_now()
    validate_state(state)
    write_json(path, state)
    refresh_state_summary(path, state)


def catalog_by_id(workspace: Path | None = None) -> dict[str, dict[str, Any]]:
    root = workspace or find_workspace()
    catalog = read_json(root / "CONDUCTOR_modules" / "catalog" / "catalog.json")
    return {item["capability_id"]: item for item in catalog["capabilities"]}


def load_profile(workspace: Path | None = None) -> dict[str, Any]:
    root = workspace or find_workspace()
    profile = read_json(root / "CONDUCTOR_modules" / "catalog" / "analysis_profile.json")
    try:
        import jsonschema
        schema = read_json(root / "CONDUCTOR_modules" / "schemas" / "analysis_profile.schema.json")
        jsonschema.validate(profile, schema)
    except ImportError as exc:
        raise RuntimeError("jsonschema is required") from exc
    return profile


def state_nodes(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {node["node_id"]: node for node in state["execution_graph"]["nodes"]}


def active_round(state: dict[str, Any], required: bool = True) -> dict[str, Any] | None:
    round_id = state["round_control"]["active_round_id"]
    item = next((value for value in state["round_control"]["rounds"] if value["round_id"] == round_id), None)
    if required and item is None:
        raise ValueError("No active Round; start or resume a Round first")
    return item


def allocate_id(state: dict[str, Any], entity: str, count: int = 1) -> list[str]:
    if count < 1:
        raise ValueError("ID reservation count must be >= 1")
    if entity in STAGE_COUNTER:
        counter, prefix = STAGE_COUNTER[entity]
        width = 4
    else:
        counter, prefix, width = ENTITY_COUNTER[entity]
    first = int(state["id_counters"][counter]) + 1
    state["id_counters"][counter] = first + count - 1
    return [f"{prefix}{number:0{width}d}" for number in range(first, first + count)]


def analysis_signature(capability_id: str, dependencies: list[str], parameters: dict[str, Any], scope: Any = None) -> str:
    scientific = {key: value for key, value in parameters.items() if key not in TRANSIENT_PARAMETER_KEYS}
    payload = {"capability_id": capability_id, "dependencies": sorted(dependencies), "parameters": scientific, "scope": scope}
    return value_hash(payload)


def infer_id_column(header: list[str]) -> str:
    normalized = {re.sub(r"[^a-z0-9]", "", name.lower()): name for name in header}
    for candidate in ["compoundid", "moleculeid", "id", "chemblid"]:
        if candidate in normalized:
            return normalized[candidate]
    raise ValueError("CONDUCTOR input requires an explicit compound ID column")


def inspect_input(path: Path, endpoint: str, assay_column: str | None) -> dict[str, Any]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames or []
        if endpoint not in header:
            raise ValueError(f"Endpoint column not found: {endpoint}")
        if assay_column and assay_column not in header:
            raise ValueError(f"Assay column not found: {assay_column}")
        id_column = infer_id_column(header)
        ids: list[str] = []
        numeric = 0
        assay_levels: set[str] = set()
        for row_number, row in enumerate(reader, start=2):
            identifier = str(row.get(id_column) or "").strip()
            if not identifier:
                raise ValueError(f"Blank compound ID at input row {row_number}")
            ids.append(identifier)
            raw = str(row.get(endpoint) or "").strip()
            if raw:
                try:
                    float(raw)
                    numeric += 1
                except ValueError as exc:
                    raise ValueError(f"Non-numeric endpoint at row {row_number}: {raw}") from exc
            if assay_column and str(row.get(assay_column) or "").strip():
                assay_levels.add(str(row[assay_column]).strip())
    duplicates = sorted({identifier for identifier in ids if ids.count(identifier) > 1})
    if duplicates:
        raise ValueError(f"Duplicate compound IDs: {duplicates[:10]}")
    if numeric < 2:
        raise ValueError("At least two numeric endpoint values are required")
    return {"id_column": id_column, "row_count": len(ids), "assay_level_count": len(assay_levels)}


def index_paths(run_root: Path) -> dict[str, Any]:
    indices = run_root / "indices"
    group_root = run_root / "grouping" / "group_index"
    return {
        "coverage": {"path": str((indices / "coverage_index.json").resolve())},
        "group": {
            "registry_path": str((group_root / "group_registry.csv").resolve()),
            "matrix_shards": [], "by_node": {}, "group_count": 0, "active_group_count": 0,
            "deprioritized_group_count": 0,
        },
        "evidence_digest": {"path": str((indices / "evidence_digest.jsonl").resolve()), "count": 0},
        "salience": {
            "view_path": str((indices / "salience_view.jsonl").resolve()),
            "history_path": str((indices / "salience_history.jsonl").resolve()),
        },
        "questions": {"path": str((indices / "question_ledger.jsonl").resolve()), "count": 0},
        "relations": {"path": str((indices / "relation_index.jsonl").resolve()), "count": 0},
        "findings": {"path": str((indices / "finding_ledger.jsonl").resolve()), "count": 0},
        "hypotheses": {"path": str((indices / "hypothesis_ledger.jsonl").resolve()), "count": 0},
        "requests": {"path": str((indices / "analysis_request_ledger.jsonl").resolve()), "count": 0},
    }


def snapshot_package(
    workspace: Path, run_root: Path, profile: dict[str, Any], snapshot_label: str | None = None,
) -> dict[str, Any]:
    snapshot_root = run_root / "snapshots"
    if snapshot_label:
        snapshot_root = snapshot_root / "package_changes" / snapshot_label
    snapshot_root.mkdir(parents=True, exist_ok=True)
    sources = {
        "catalog": workspace / "CONDUCTOR_modules" / "catalog" / "catalog.json",
        "profile": workspace / "CONDUCTOR_modules" / "catalog" / "analysis_profile.json",
        "orchestration_policy": workspace / "CONDUCTOR_modules" / "docs" / "CONDUCTOR_v4_policy.md",
        "interpretation_policy": workspace / "CONDUCTOR_modules" / "docs" / "CONDUCTOR_v4_interpretation_policy.md",
    }
    records: dict[str, Any] = {"profile_id": profile["profile_id"], "files": {}}
    for name, source in sources.items():
        target = snapshot_root / source.name
        shutil.copy2(source, target)
        records["files"][name] = {"source": str(source.resolve()), "snapshot": str(target.resolve()), "sha256": file_hash(source)}
    records["snapshot_hash"] = value_hash({name: value["sha256"] for name, value in records["files"].items()})
    records["created_at"] = utc_now()
    return records


def create_round(state: dict[str, Any], run_root: Path, request: str, envelope: dict[str, Any]) -> dict[str, Any]:
    if state["round_control"]["active_round_id"] is not None:
        raise ValueError("An active Round already exists")
    number = state["round_control"]["next_round_number"]
    round_id = f"RND{number:04d}"
    round_root = run_root / "rounds" / round_id
    round_root.mkdir(parents=True, exist_ok=False)
    (round_root / "round_request.md").write_text(request.rstrip() + "\n", encoding="utf-8")
    started = datetime.now(timezone.utc)
    walltime = max(1, int(envelope.get("walltime_minutes") or 480))
    reserve = max(10, min(60, int(round(walltime * 0.15))))
    migration_baseline = state.get("run", {}).get("migration_baseline") or {}
    prior_phase_plans = {
        phase: any(entry.get("action") == f"{phase}_planned" for entry in state.get("history") or [])
        for phase in ["basic_compute", "initial_global", "initial_local"]
    }
    baseline_flags = {
        "basic_plan_complete": bool((migration_baseline.get("basic_compute") or {}).get("complete")) if number == 2 and migration_baseline else prior_phase_plans["basic_compute"],
        "initial_global_plan_complete": bool(migration_baseline.get("initial_global_complete")) if number == 2 and migration_baseline else prior_phase_plans["initial_global"],
        "initial_local_plan_complete": bool(migration_baseline.get("initial_local_complete")) if number == 2 and migration_baseline else prior_phase_plans["initial_local"],
    }
    item = {
        "round_id": round_id, "number": number, "status": "active", "request": request,
        "request_path": str((round_root / "round_request.md").resolve()), "resource_envelope": envelope,
        "sampling_events": [], "started_at": started.isoformat(), "ended_at": None,
        "execution_control": {
            "deadline_at": (started + timedelta(minutes=walltime)).isoformat(),
            "interpretation_reserve_minutes": reserve,
            "additional_nodes_planned": 0,
            "stop_reason": None,
            "last_progress_at": started.isoformat(),
            **baseline_flags,
        },
        "close_gate": {"status": "open", "reason_codes": ["ROUND_ACTIVE"], "checked_at": started.isoformat()},
    }
    state["round_control"]["rounds"].append(item)
    state["round_control"]["active_round_id"] = round_id
    state["round_control"]["next_round_number"] = number + 1
    append_history(state, "round_started", round_id=round_id)
    return item


def cmd_init(args: argparse.Namespace) -> int:
    workspace = find_workspace()
    input_path = Path(args.input).resolve()
    if not input_path.is_file():
        raise FileNotFoundError(input_path)
    inspected = inspect_input(input_path, args.endpoint, args.assay_column)
    profile = load_profile(workspace)
    input_hash = file_hash(input_path)
    bundle_scope = {
        "input_hash": input_hash,
        "endpoint": args.endpoint,
        "higher_is_better": args.higher_is_better,
        "profile_id": profile["profile_id"],
        "profile_hash": file_hash(workspace / "CONDUCTOR_modules" / "catalog" / "analysis_profile.json"),
        "catalog_hash": file_hash(workspace / "CONDUCTOR_modules" / "catalog" / "catalog.json"),
        "capability_ids": profile["basic_compute"]["high_cost_bundle"],
        "resource_envelope": {
            "walltime_minutes": args.walltime_minutes,
            "max_additional_nodes": args.max_additional_nodes,
            "interpretation_iterations": args.interpretation_iterations,
            "parallel_limit": args.parallel_limit,
        },
    }
    run_id = args.run_id or run_id_now()
    run_root = Path(args.output_dir).resolve() if args.output_dir else (workspace / "results" / "CONDUCTOR" / args.project / run_id).resolve()
    state_path = run_root / "state.json"
    if state_path.exists():
        raise FileExistsError(f"State already exists: {state_path}")
    run_root.mkdir(parents=True, exist_ok=True)
    indices = index_paths(run_root)
    counters = {name: 0 for name in ["description_node", "grouping_node", "operator_node", "interpretation_node", "group", "evidence", "finding", "hypothesis", "question", "relation", "request", "scope", "salience_event"]}
    state = {
        "schema_version": STATE_SCHEMA_VERSION, "conductor_version": CONDUCTOR_VERSION,
        "run": {
            "run_id": run_id, "project": args.project, "input": str(input_path), "input_hash": input_hash,
            "endpoint": args.endpoint, "higher_is_better": args.higher_is_better,
            "parallel_limit": args.parallel_limit, **inspected, "assay_column": args.assay_column,
            "profile_id": profile["profile_id"], "package_snapshot": {},
            "package_change_gate": {"status": "clear", "checked_at": utc_now(), "differences": []},
            "high_cost_bundle": {
                "capability_ids": profile["basic_compute"]["high_cost_bundle"], "status": "pending",
                "scope": bundle_scope, "scope_hash": value_hash(bundle_scope),
            },
            "created_at": utc_now(),
        },
        "round_control": {"active_round_id": None, "next_round_number": 1, "rounds": []},
        "orchestration_control": {
            "controller_epoch": 0,
            "lease": {
                "owner_id": None, "token_hash": None, "epoch": 0,
                "acquired_at": None, "heartbeat_at": None, "expires_at": None,
                "duration_minutes": DEFAULT_LEASE_MINUTES,
            },
            "last_bootstrap_at": None,
            "last_audit_path": None,
        },
        "id_counters": counters, "execution_graph": {"nodes": [], "edges": []}, "indices": indices,
        "history": [], "updated_at": utc_now(),
    }
    state["run"]["package_snapshot"] = snapshot_package(workspace, run_root, profile)
    envelope = {"walltime_minutes": args.walltime_minutes, "max_additional_nodes": args.max_additional_nodes, "interpretation_iterations": args.interpretation_iterations}
    create_round(state, run_root, args.request or "新規CONDUCTOR Runを開始する。", envelope)
    initialize_indices(state)
    append_history(state, "initialized")
    write_state(state_path, state)
    print(state_path)
    return 0


def initialize_indices(state: dict[str, Any]) -> None:
    write_json(Path(state["indices"]["coverage"]["path"]), {"schema_version": "1.0.0", "cells": [], "updated_at": utc_now()})
    write_jsonl(Path(state["indices"]["evidence_digest"]["path"]), [])
    write_jsonl(Path(state["indices"]["salience"]["view_path"]), [])
    write_jsonl(Path(state["indices"]["salience"]["history_path"]), [])
    write_jsonl(Path(state["indices"]["questions"]["path"]), [])
    write_jsonl(Path(state["indices"]["relations"]["path"]), [])
    write_jsonl(Path(state["indices"]["findings"]["path"]), [])
    write_jsonl(Path(state["indices"]["hypotheses"]["path"]), [])
    write_jsonl(Path(state["indices"]["requests"]["path"]), [])
    write_csv_rows(Path(state["indices"]["group"]["registry_path"]), GROUP_REGISTRY_FIELDS, [])


def current_package_hashes(workspace: Path) -> dict[str, str]:
    sources = {
        "catalog": workspace / "CONDUCTOR_modules" / "catalog" / "catalog.json",
        "profile": workspace / "CONDUCTOR_modules" / "catalog" / "analysis_profile.json",
        "orchestration_policy": workspace / "CONDUCTOR_modules" / "docs" / "CONDUCTOR_v4_policy.md",
        "interpretation_policy": workspace / "CONDUCTOR_modules" / "docs" / "CONDUCTOR_v4_interpretation_policy.md",
    }
    return {name: file_hash(path) for name, path in sources.items()}


def detect_package_change(state: dict[str, Any], workspace: Path) -> dict[str, Any]:
    snapshot_hashes = {name: item["sha256"] for name, item in state["run"]["package_snapshot"]["files"].items()}
    current_hashes = current_package_hashes(workspace)
    differences = sorted(
        name for name in set(snapshot_hashes) | set(current_hashes)
        if snapshot_hashes.get(name) != current_hashes.get(name)
    )
    gate = state["run"].setdefault("package_change_gate", {})
    rejected_same_package = gate.get("status") == "rejected" and gate.get("current_hashes") == current_hashes
    gate.update({
        "status": ("rejected" if rejected_same_package else "approval_required") if differences else "clear",
        "checked_at": utc_now(),
        "differences": differences,
        "snapshot_hashes": snapshot_hashes,
        "current_hashes": current_hashes,
    })
    if differences:
        gate.setdefault("detected_at", utc_now())
    else:
        gate.pop("detected_at", None)
    return gate


def package_gate_error(state: dict[str, Any]) -> str | None:
    gate = state["run"].get("package_change_gate") or {}
    if gate.get("status") == "approval_required":
        return "Package change approval is required before planning or executing Nodes"
    if gate.get("status") == "rejected":
        return "Package change was rejected; restore the Run snapshot package or start a new Run"
    return None


def binding_node_ids(bindings: dict[str, Any], stage: str) -> list[str]:
    value = bindings.get(stage)
    if value is None:
        return []
    return [str(item) for item in value] if isinstance(value, list) else [str(value)]


def dependency_bindings(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for node in nodes:
        grouped[node["stage"]].append(node["node_id"])
    return {stage: ids[0] if len(ids) == 1 else ids for stage, ids in grouped.items()}


def validate_dependency_contract(capability: dict[str, Any], dependency_nodes: list[dict[str, Any]], parameters: dict[str, Any]) -> None:
    required = ["analysis" if stage == "evidence" else stage for stage in capability.get("dependencies") or []]
    actual = [node["stage"] for node in dependency_nodes]
    allowed = set(required)
    if capability["stage"] == "analysis" and str(parameters.get("scope_mode") or "global") != "global":
        allowed.add("grouping")
    if capability["stage"] == "interpretation":
        allowed.add("analysis")
    missing = [stage for stage in required if stage not in actual]
    unexpected = [stage for stage in actual if stage not in allowed]
    if missing:
        raise ValueError(f"{capability['capability_id']} requires dependency stage(s): {sorted(set(missing))}")
    if unexpected:
        raise ValueError(f"{capability['capability_id']} does not accept dependency stage(s): {sorted(set(unexpected))}")
    if capability["stage"] == "analysis" and str(parameters.get("scope_mode") or "global") != "global" and "grouping" not in actual:
        raise ValueError("A local Operator requires a Grouping dependency")


def primary_artifact_path(node: dict[str, Any], capability: dict[str, Any]) -> Path:
    output = capability["output"]
    if node["stage"] == "description":
        extension = "parquet" if node.get("parameters", {}).get("format") == "parquet" else "csv"
        return Path(node["output_dir"]) / f"{output['basename']}.{extension}"
    if node["stage"] == "grouping":
        return Path(node.get("global_membership_path") or (Path(node["output_dir"]) / output["membership"]))
    if node["stage"] == "analysis":
        return Path(node["output_dir"]) / output["filename"]
    return Path(node["output_dir"]) / output.get("json", "interpretation.json")


def bind_system_parameter(parameters: dict[str, Any], key: str, value: Any) -> None:
    if key in parameters and parameters[key] != value:
        raise ValueError(f"CONDUCTOR-bound parameter {key} conflicts with planned value")
    parameters[key] = value


def description_natural_metric(description_node: dict[str, Any]) -> str:
    capability_id = description_node["capability_id"]
    if capability_id == "D017" and description_node.get("parameters", {}).get("reduction") == "svd":
        return "cosine"
    profile = load_profile()
    return str(profile["description_semantics"][capability_id]["natural_metric"])


def configure_node_io(state: dict[str, Any], node: dict[str, Any], capability: dict[str, Any], capabilities: dict[str, dict[str, Any]], run_root: Path) -> None:
    stage_dir = {"description": "description", "grouping": "grouping", "analysis": "analysis", "interpretation": "interpretation"}[node["stage"]]
    if node["stage"] == "interpretation":
        output_dir = run_root / stage_dir / node["node_id"]
    else:
        output_dir = run_root / stage_dir / capability["skill_name"] / node["node_id"]
    node["output_dir"] = str(output_dir.resolve())
    parameters = node["parameters"]
    bind_system_parameter(parameters, "output_dir", node["output_dir"])
    bindings = node["input_bindings"]
    nodes = state_nodes(state)
    if node["stage"] == "description":
        bind_system_parameter(parameters, "input", state["run"]["input"])
        parameters.setdefault("format", "csv")
    elif node["stage"] == "grouping":
        description_ids = binding_node_ids(bindings, "description")
        grouping_ids = binding_node_ids(bindings, "grouping")
        sources = description_ids or grouping_ids
        if sources:
            paths = [str(primary_artifact_path(nodes[source], capabilities[nodes[source]["capability_id"]])) for source in sources]
            bind_system_parameter(parameters, "input", paths[0] if len(paths) == 1 else paths)
            if description_ids:
                bind_system_parameter(parameters, "input_representation", nodes[description_ids[0]]["capability_id"])
        else:
            bind_system_parameter(parameters, "input", state["run"]["input"])
    elif node["stage"] == "analysis":
        bind_system_parameter(parameters, "input", state["run"]["input"])
        bind_system_parameter(parameters, "property_column", state["run"]["endpoint"])
        bind_system_parameter(parameters, "higher_is_better", state["run"]["higher_is_better"])
        description_ids = binding_node_ids(bindings, "description")
        grouping_ids = binding_node_ids(bindings, "grouping")
        if description_ids:
            source = nodes[description_ids[0]]
            bind_system_parameter(parameters, "description", str(primary_artifact_path(source, capabilities[source["capability_id"]])))
            bind_system_parameter(parameters, "evaluation_representation", source["capability_id"])
            bind_system_parameter(parameters, "description_node_id", source["node_id"])
        if grouping_ids:
            source = nodes[grouping_ids[0]]
            membership = source.get("global_membership_path") or str(primary_artifact_path(source, capabilities[source["capability_id"]]))
            bind_system_parameter(parameters, "membership", membership)
            bind_system_parameter(parameters, "grouping_representation", source["capability_id"])
            bind_system_parameter(parameters, "grouping_node_id", source["node_id"])
        if capability["capability_id"] in {"A003", "A007", "A010"}:
            bind_system_parameter(parameters, "evaluation_representation", "internal_morgan_r2_2048")
        bind_system_parameter(parameters, "evidence_id", node["evidence_id"])
        bind_system_parameter(parameters, "round_id", node["round_id"])
    else:
        evidence_paths = [str(Path(nodes[source]["output_dir"]) / "evidence.json") for source in node["dependencies"] if nodes[source]["stage"] == "analysis"]
        if evidence_paths:
            bind_system_parameter(parameters, "evidence", evidence_paths)
        bind_system_parameter(parameters, "state", str((run_root / "state.json").resolve()))
        bind_system_parameter(parameters, "round_id", node["round_id"])
        reservation = Path(node["output_dir"]) / "id_reservation.json"
        bind_system_parameter(parameters, "id_reservation", str(reservation.resolve()))


def add_node(
    state: dict[str, Any], capability: dict[str, Any], dependencies: list[str] | None = None,
    parameters: dict[str, Any] | None = None, phase: str = "human_directed", reason: str = "",
    request_origin: str = "orchestrator", question_ids: list[str] | None = None,
) -> tuple[dict[str, Any], bool]:
    round_item = active_round(state)
    dependencies = list(dict.fromkeys(dependencies or []))
    nodes = state_nodes(state)
    unknown = [node_id for node_id in dependencies if node_id not in nodes]
    if unknown:
        raise ValueError(f"Unknown dependency node(s): {unknown}")
    selected = dict(capability.get("default_parameters") or {})
    selected.update(parameters or {})
    dependency_nodes = [nodes[node_id] for node_id in dependencies]
    description_dependencies = [item for item in dependency_nodes if item["stage"] == "description"]
    needs_representation_metric = (
        capability.get("grouping_kind") == "description_vector"
        or capability["capability_id"] in {"A005", "A006"}
    )
    if description_dependencies and needs_representation_metric:
        selected.setdefault("metric", description_natural_metric(description_dependencies[0]))
    validate_dependency_contract(capability, dependency_nodes, selected)
    bindings = dependency_bindings(dependency_nodes)
    scope_key = {key: selected.get(key) for key in ["scope_mode", "target_group", "comparison_group"] if selected.get(key) is not None}
    if capability["stage"] == "interpretation":
        # The same Evidence may legitimately be reinterpreted in a later Round. Keeping
        # Round in this signature also makes an accidental duplicate request idempotent
        # within one Round.
        scope_key["round_id"] = round_item["round_id"]
    signature = analysis_signature(capability["capability_id"], dependencies, selected, scope_key)
    existing = next((node for node in state["execution_graph"]["nodes"] if node["analysis_signature"] == signature and node["status"] != "stale"), None)
    if existing:
        return existing, False
    node_id = allocate_id(state, capability["stage"])[0]
    approval = "not_required"
    if capability["capability_id"] in state["run"]["high_cost_bundle"]["capability_ids"] and phase == "basic_compute":
        approval = "approved" if state["run"]["high_cost_bundle"]["status"] == "approved" else "bundle_pending"
    elif capability["cost"].get("human_approval_required"):
        approval = "required"
    node = {
        "node_id": node_id, "capability_id": capability["capability_id"], "skill_name": capability["skill_name"],
        "stage": capability["stage"], "phase": phase, "round_id": round_item["round_id"], "status": "pending",
        "dependencies": dependencies, "input_bindings": bindings, "parameters": selected,
        "analysis_signature": signature, "human_approval": approval, "output_dir": ".",
        "selection_reason": reason, "request_origin": request_origin, "question_ids": question_ids or [],
        "cost": capability["cost"], "artifacts": [], "warnings": [], "requested_at": utc_now(),
        "execution_attempts": [], "current_attempt_id": None,
    }
    if node["stage"] == "analysis":
        node["evidence_id"] = allocate_id(state, "evidence")[0]
    state["execution_graph"]["nodes"].append(node)
    for dependency in dependencies:
        state["execution_graph"]["edges"].append({"source": dependency, "target": node_id, "relation": "depends_on"})
    append_history(state, "node_added", node_id=node_id, capability_id=capability["capability_id"], round_id=round_item["round_id"], phase=phase)
    return node, True


def succeeded_nodes(state: dict[str, Any], stage: str, capability_ids: Iterable[str] | None = None) -> list[dict[str, Any]]:
    allowed = set(capability_ids or [])
    return [
        node for node in state["execution_graph"]["nodes"]
        if node["stage"] == stage and node["status"] == "succeeded" and (not allowed or node["capability_id"] in allowed)
    ]


def expand_capability_list(capabilities: dict[str, dict[str, Any]], values: list[str], stage: str) -> list[str]:
    if "*" in values:
        return sorted(capability_id for capability_id, item in capabilities.items() if item["stage"] == stage)
    return values


def plan_node(
    state: dict[str, Any], capabilities: dict[str, dict[str, Any]], run_root: Path,
    capability_id: str, dependencies: list[str], phase: str, reason: str,
    parameters: dict[str, Any] | None = None, question_ids: list[str] | None = None,
) -> tuple[dict[str, Any], bool]:
    gate_error = package_gate_error(state)
    if gate_error:
        raise ValueError(gate_error)
    capability = capabilities.get(capability_id)
    if capability is None or capability["stage"] == "orchestration":
        raise ValueError(f"Capability is not executable or absent from Catalog: {capability_id}")
    node, created = add_node(state, capability, dependencies, parameters, phase, reason, question_ids=question_ids)
    if created:
        configure_node_io(state, node, capability, capabilities, run_root)
    return node, created


def cmd_plan_basic(args: argparse.Namespace) -> int:
    state_path = Path(args.state).resolve()
    capabilities = catalog_by_id()
    profile = load_profile()
    with state_lock(state_path):
        state = read_json(state_path)
        controller_mutation(state, args)
        run_root = state_path.parent
        planned: list[str] = []
        description_ids = expand_capability_list(capabilities, profile["basic_compute"]["description_capabilities"], "description")
        description_nodes: dict[str, dict[str, Any]] = {}
        for capability_id in description_ids:
            existing = next((node for node in state["execution_graph"]["nodes"] if node["stage"] == "description" and node["capability_id"] == capability_id and node["status"] == "succeeded"), None)
            node, created = (existing, False) if existing else plan_node(state, capabilities, run_root, capability_id, [], "basic_compute", "基本計算として全Descriptionを生成する。")
            description_nodes[capability_id] = node
            if created:
                planned.append(node["node_id"])
        for capability_id in profile["basic_compute"]["direct_structure_grouping"]:
            existing = next((node for node in state["execution_graph"]["nodes"] if node["stage"] == "grouping" and node["capability_id"] == capability_id and node["status"] == "succeeded"), None)
            node, created = (existing, False) if existing else plan_node(state, capabilities, run_root, capability_id, [], "basic_compute", "Direct structure基本Groupingを生成する。")
            if created:
                planned.append(node["node_id"])
        for grouping_id in profile["basic_compute"]["vector_grouping_capabilities"]:
            for description_id in profile["basic_compute"]["vector_grouping_representations"]:
                source = description_nodes.get(description_id) or next((node for node in state["execution_graph"]["nodes"] if node["capability_id"] == description_id and node["stage"] == "description"), None)
                if source is None:
                    continue
                existing = next(
                    (
                        node for node in state["execution_graph"]["nodes"]
                        if node["stage"] == "grouping" and node["capability_id"] == grouping_id and node["status"] == "succeeded"
                        and any(state_nodes(state).get(dependency, {}).get("capability_id") == description_id for dependency in node.get("dependencies") or [])
                    ),
                    None,
                )
                node, created = (existing, False) if existing else plan_node(
                    state, capabilities, run_root, grouping_id, [source["node_id"]], "basic_compute",
                    f"表現family代表{description_id}へVector Clustering {grouping_id}を適用する。",
                )
                if created:
                    planned.append(node["node_id"])
        if state["run"].get("assay_level_count", 0) > 1 and "C011" in profile["basic_compute"]["conditional_grouping"]:
            existing = next((node for node in state["execution_graph"]["nodes"] if node["stage"] == "grouping" and node["capability_id"] == "C011" and node["status"] == "succeeded"), None)
            node, created = (existing, False) if existing else plan_node(
                state, capabilities, run_root, "C011", [], "basic_compute",
                "複数assay条件を検出したため、条件を混合せず比較可能にする。",
                {"columns": state["run"]["assay_column"]},
            )
            if created:
                planned.append(node["node_id"])
        active_round(state).setdefault("execution_control", {})["basic_plan_complete"] = True
        append_history(state, "basic_compute_planned", node_ids=planned, profile_id=profile["profile_id"])
        update_coverage_index(state_path, state)
        write_state(state_path, state)
    print(json.dumps({"planned_nodes": planned, "high_cost_bundle": state["run"]["high_cost_bundle"]}, ensure_ascii=False, indent=2))
    return 0


def cmd_approve_basic_bundle(args: argparse.Namespace) -> int:
    state_path = Path(args.state).resolve()
    with state_lock(state_path):
        state = read_json(state_path)
        controller_mutation(state, args)
        status = "approved" if args.approve else "rejected"
        bundle = state["run"]["high_cost_bundle"]
        bundle.update({"status": status, "rationale": args.rationale, "decided_at": utc_now(), "decided_scope_hash": bundle["scope_hash"]})
        affected = []
        for node in state["execution_graph"]["nodes"]:
            if node["phase"] != "basic_compute" or node["capability_id"] not in bundle["capability_ids"]:
                continue
            affected.append(node["node_id"])
            if args.approve:
                node["human_approval"] = "approved"
            else:
                node["human_approval"] = "rejected"
                if node["status"] == "pending":
                    node["status"] = "waived"
                    node["waiver_reason"] = args.rationale
        cascaded = cascade_terminal_dependencies(state) if not args.approve else []
        append_history(state, "basic_bundle_decided", status=status, node_ids=affected, cascaded_node_ids=cascaded, rationale=args.rationale)
        update_coverage_index(state_path, state)
        write_state(state_path, state)
    return 0


def phase_terminal(state: dict[str, Any], phase: str) -> bool:
    nodes = [node for node in state["execution_graph"]["nodes"] if node["phase"] == phase]
    if nodes:
        return all(node["status"] in TERMINAL_STATUSES for node in nodes)
    # A scientifically applicable phase can legitimately be empty (for example, no
    # valid local Groups). The auditable planning event closes that empty phase.
    return any(item.get("action") == f"{phase}_planned" for item in state.get("history") or [])


def cascade_terminal_dependencies(state: dict[str, Any]) -> list[str]:
    """Close pending descendants whose required upstream ended without an artifact."""
    changed: list[str] = []
    nodes = state_nodes(state)
    progress = True
    while progress:
        progress = False
        for node in state["execution_graph"]["nodes"]:
            if node["status"] not in {"pending", "stale"}:
                continue
            blocked = [dependency for dependency in node["dependencies"] if nodes[dependency]["status"] in TERMINAL_STATUSES - {"succeeded"}]
            if not blocked:
                continue
            node["status"] = "not_applicable"
            node["terminal_reason"] = f"Required upstream Node(s) ended without usable artifacts: {', '.join(blocked)}"
            node["finished_at"] = utc_now()
            changed.append(node["node_id"])
            progress = True
    return changed


def ensure_initial_gate(state: dict[str, Any], allow_override: bool) -> None:
    if phase_terminal(state, "basic_compute"):
        return
    if not allow_override:
        raise ValueError("basic_compute is not terminal; use an explicit human override only when scientifically justified")
    append_history(state, "phase_gate_overridden", gate="basic_compute", round_id=active_round(state)["round_id"])


def master_description_nodes(state: dict[str, Any], profile: dict[str, Any]) -> list[dict[str, Any]]:
    by_capability: dict[str, dict[str, Any]] = {}
    for node in succeeded_nodes(state, "description"):
        by_capability.setdefault(node["capability_id"], node)
    return [by_capability[capability_id] for capability_id in profile["initial_exploration"]["description_master_panel"] if capability_id in by_capability]


def dependency_sets_for_operator(
    capability: dict[str, Any], description_nodes: list[dict[str, Any]], grouping_nodes: list[dict[str, Any]], scope_mode: str,
) -> list[list[str]]:
    dependencies = capability.get("dependencies") or []
    result: list[list[str]] = []
    if "description" in dependencies:
        for description in description_nodes:
            if scope_mode == "global":
                result.append([description["node_id"]])
            else:
                for grouping in grouping_nodes:
                    result.append([description["node_id"], grouping["node_id"]])
    elif "grouping" in dependencies:
        result = [[grouping["node_id"]] for grouping in grouping_nodes]
    elif scope_mode == "global":
        result = [[]]
    else:
        result = [[grouping["node_id"]] for grouping in grouping_nodes]
    return result


def cmd_plan_initial_global(args: argparse.Namespace) -> int:
    state_path = Path(args.state).resolve()
    capabilities = catalog_by_id()
    profile = load_profile()
    with state_lock(state_path):
        state = read_json(state_path)
        controller_mutation(state, args)
        ensure_initial_gate(state, args.override_gate)
        run_root = state_path.parent
        descriptions = master_description_nodes(state, profile)
        groupings = succeeded_nodes(state, "grouping")
        planned: list[str] = []
        for capability_id in profile["initial_exploration"]["global_operator_capabilities"]:
            capability = capabilities[capability_id]
            if "global" not in (capability.get("scope_support") or ["global"]):
                continue
            for dependencies in dependency_sets_for_operator(capability, descriptions, groupings, "global"):
                node, created = plan_node(
                    state, capabilities, run_root, capability_id, dependencies, "initial_global",
                    "全体scopeの全applicable Operator roleを共通master panelで実行する。", {"scope_mode": "global"},
                )
                if created:
                    planned.append(node["node_id"])
        active_round(state).setdefault("execution_control", {})["initial_global_plan_complete"] = True
        append_history(state, "initial_global_planned", node_ids=planned)
        update_coverage_index(state_path, state)
        write_state(state_path, state)
    print(json.dumps({"planned_nodes": planned}, ensure_ascii=False, indent=2))
    return 0


def load_compound_endpoint(state: dict[str, Any]) -> dict[str, float]:
    values: dict[str, float] = {}
    with Path(state["run"]["input"]).open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            identifier = str(row.get(state["run"]["id_column"]) or "").strip()
            try:
                values[identifier] = float(row[state["run"]["endpoint"]])
            except (TypeError, ValueError):
                pass
    return values


def membership_sets(path: Path) -> dict[str, set[str]]:
    rows = read_csv_rows(path)
    if not rows:
        return {}
    if {"cluster_id", "compound_id", "membership_value"}.issubset(rows[0]):
        groups: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            try:
                active = float(row.get("membership_value") or 0) > 0
            except ValueError:
                active = False
            if active:
                groups[str(row["cluster_id"])].add(str(row["compound_id"]))
        return dict(groups)
    groups = {column: set() for column in rows[0] if column != "compound_id"}
    for row in rows:
        for group_id in groups:
            if str(row.get(group_id) or "").strip().lower() in {"true", "1", "yes"}:
                groups[group_id].add(str(row["compound_id"]))
    return groups


def select_representative_groups(state: dict[str, Any], grouping_node: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    membership_path = grouping_node.get("global_membership_path")
    if not membership_path or not Path(membership_path).is_file():
        return []
    groups = membership_sets(Path(membership_path))
    endpoint = load_compound_endpoint(state)
    rows = [row for row in read_csv_rows(Path(state["indices"]["group"]["registry_path"])) if row.get("source_node_id") == grouping_node["node_id"] and row.get("status") == "active"]
    candidates: list[dict[str, Any]] = []
    for row in rows:
        group_id = row["group_id"]
        members = groups.get(group_id, set())
        values = [endpoint[compound] for compound in members if compound in endpoint]
        mean = sum(values) / len(values) if values else 0.0
        variance = sum((value - mean) ** 2 for value in values) / max(1, len(values) - 1) if len(values) > 1 else 0.0
        candidates.append({"row": row, "members": members, "count": len(members), "fraction": len(members) / max(1, state["run"]["row_count"]), "variance": variance})
    strongly_local = [item for item in candidates if item["count"] >= 3 and item["fraction"] <= 0.3]
    moderately_local = [item for item in candidates if item["count"] >= 3 and item["fraction"] <= 0.5]
    local = strongly_local or moderately_local or [item for item in candidates if item["count"] >= 3]
    if not local:
        return []
    selected: list[dict[str, Any]] = []
    def add(item: dict[str, Any], role: str) -> None:
        if item not in selected and len(selected) < limit:
            item = dict(item)
            item["role"] = role
            selected.append(item)
    add(max(local, key=lambda item: (item["count"], item["row"]["group_id"])), "largest_local")
    ordered = sorted(local, key=lambda item: (item["count"], item["row"]["group_id"]))
    add(ordered[len(ordered) // 2], "middle_size")
    add(max(local, key=lambda item: (item["variance"], item["row"]["group_id"])), "endpoint_dispersion_extreme")
    if grouping_node["capability_id"] == "C002":
        add(min(local, key=lambda item: (item["count"], item["row"]["group_id"])), "structurally_cohesive_mcs")
    while len(selected) < min(limit, len(local)):
        best = max(
            (item for item in local if all(item["row"]["group_id"] != chosen["row"]["group_id"] for chosen in selected)),
            key=lambda item: (min(1 - len(item["members"] & chosen["members"]) / max(1, len(item["members"] | chosen["members"])) for chosen in selected), item["count"]),
            default=None,
        )
        if best is None:
            break
        add(best, "low_overlap")
    return selected


def cmd_plan_initial_local(args: argparse.Namespace) -> int:
    state_path = Path(args.state).resolve()
    capabilities = catalog_by_id()
    profile = load_profile()
    with state_lock(state_path):
        state = read_json(state_path)
        controller_mutation(state, args)
        if not phase_terminal(state, "initial_global") and not args.override_gate:
            raise ValueError("initial_global is not terminal")
        run_root = state_path.parent
        descriptions = master_description_nodes(state, profile)
        groupings = succeeded_nodes(state, "grouping")
        planned: list[str] = []
        selections: list[dict[str, Any]] = []
        limit = profile["initial_exploration"]["representative_groups_per_grouping"]
        for grouping in groupings:
            if len(planned) >= args.batch_size:
                break
            for selected in select_representative_groups(state, grouping, limit):
                if len(planned) >= args.batch_size:
                    break
                group_id = selected["row"]["group_id"]
                selections.append({"grouping_node_id": grouping["node_id"], "group_id": group_id, "role": selected["role"], "count": selected["count"], "fraction": selected["fraction"], "endpoint_variance": selected["variance"]})
                for capability_id in profile["initial_exploration"]["local_operator_capabilities"]:
                    if len(planned) >= args.batch_size:
                        break
                    capability = capabilities[capability_id]
                    if "within-group" not in (capability.get("scope_support") or []):
                        continue
                    dependency_sets = dependency_sets_for_operator(capability, descriptions, [grouping], "within-group")
                    for dependencies in dependency_sets:
                        if len(planned) >= args.batch_size:
                            break
                        params = {"scope_mode": "within-group", "target_group": group_id}
                        node, created = plan_node(
                            state, capabilities, run_root, capability_id, dependencies, "initial_local",
                            f"{grouping['node_id']}の代表Group {group_id}（role={selected['role']}）を全applicable local Operatorで評価する。", params,
                        )
                        if created:
                            planned.append(node["node_id"])
        round_item = active_round(state)
        round_item["representative_group_selections"] = selections
        round_item.setdefault("execution_control", {})["initial_local_plan_complete"] = len(planned) < args.batch_size
        append_history(state, "initial_local_planned", node_ids=planned, selections=selections, batch_size=args.batch_size)
        update_coverage_index(state_path, state)
        write_state(state_path, state)
    print(json.dumps({"planned_nodes": planned, "representative_groups": selections}, ensure_ascii=False, indent=2))
    return 0


def candidate_cells(state: dict[str, Any], capabilities: dict[str, dict[str, Any]], profile: dict[str, Any]) -> list[dict[str, Any]]:
    descriptions = succeeded_nodes(state, "description")
    groupings = succeeded_nodes(state, "grouping")
    registry = [row for row in read_csv_rows(Path(state["indices"]["group"]["registry_path"])) if row.get("status") == "active"]
    groups_by_node: dict[str, list[str]] = defaultdict(list)
    for row in registry:
        groups_by_node[row["source_node_id"]].append(row["group_id"])
    existing = {node["analysis_signature"] for node in state["execution_graph"]["nodes"] if node["status"] != "stale"}
    result: list[dict[str, Any]] = []
    operator_ids = profile["initial_exploration"]["global_operator_capabilities"]
    for operator_id in operator_ids:
        capability = capabilities[operator_id]
        scopes = capability.get("scope_support") or ["global"]
        if "description" in (capability.get("dependencies") or []):
            for description in descriptions:
                if "global" in scopes:
                    params = {"scope_mode": "global"}
                    if operator_id in {"A005", "A006"}:
                        params["metric"] = description_natural_metric(description)
                    signature = analysis_signature(operator_id, [description["node_id"]], params, {"scope_mode": "global"})
                    if signature not in existing:
                        result.append({"capability_id": operator_id, "dependencies": [description["node_id"]], "parameters": params, "stratum": [capabilities[description["capability_id"]]["family"], "none", operator_id, "global"], "signature": signature})
                if "within-group" in scopes:
                    for grouping in groupings:
                        for group_id in groups_by_node.get(grouping["node_id"], []):
                            params = {"scope_mode": "within-group", "target_group": group_id}
                            if operator_id in {"A005", "A006"}:
                                params["metric"] = description_natural_metric(description)
                            deps = [description["node_id"], grouping["node_id"]]
                            signature = analysis_signature(operator_id, deps, params, params)
                            if signature not in existing:
                                result.append({"capability_id": operator_id, "dependencies": deps, "parameters": params, "stratum": [capabilities[description["capability_id"]]["family"], grouping["capability_id"], operator_id, "within-group"], "signature": signature})
        elif "grouping" in (capability.get("dependencies") or []):
            for grouping in groupings:
                params = {"scope_mode": "global"}
                signature = analysis_signature(operator_id, [grouping["node_id"]], params, params)
                if signature not in existing:
                    result.append({"capability_id": operator_id, "dependencies": [grouping["node_id"]], "parameters": params, "stratum": ["none", grouping["capability_id"], operator_id, "global"], "signature": signature})
        else:
            params = {"scope_mode": "global"}
            signature = analysis_signature(operator_id, [], params, params)
            if signature not in existing:
                result.append({"capability_id": operator_id, "dependencies": [], "parameters": params, "stratum": ["none", "none", operator_id, "global"], "signature": signature})
            if "within-group" in scopes:
                for grouping in groupings:
                    for group_id in groups_by_node.get(grouping["node_id"], []):
                        params = {"scope_mode": "within-group", "target_group": group_id}
                        signature = analysis_signature(operator_id, [grouping["node_id"]], params, params)
                        if signature not in existing:
                            result.append({"capability_id": operator_id, "dependencies": [grouping["node_id"]], "parameters": params, "stratum": ["none", grouping["capability_id"], operator_id, "within-group"], "signature": signature})
    unique: dict[str, dict[str, Any]] = {}
    for item in result:
        unique.setdefault(item["signature"], item)
    return list(unique.values())


def balanced_sample(candidates: list[dict[str, Any]], count: int, seed: int, state: dict[str, Any]) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    buckets: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for item in candidates:
        buckets[tuple(item["stratum"])].append(item)
    for values in buckets.values():
        rng.shuffle(values)
    coverage: dict[tuple[str, ...], int] = defaultdict(int)
    for node in state["execution_graph"]["nodes"]:
        if node["stage"] != "analysis":
            continue
        key = tuple(node.get("coverage_stratum") or [])
        if key:
            coverage[key] += 1
    selected: list[dict[str, Any]] = []
    while buckets and len(selected) < count:
        ordered = sorted(buckets, key=lambda key: (coverage[key], key))
        minimum = coverage[ordered[0]]
        tied = [key for key in ordered if coverage[key] == minimum]
        key = rng.choice(tied)
        selected.append(buckets[key].pop())
        coverage[key] += 1
        if not buckets[key]:
            del buckets[key]
    return selected


def cmd_plan_additional(args: argparse.Namespace) -> int:
    state_path = Path(args.state).resolve()
    capabilities = catalog_by_id()
    profile = load_profile()
    with state_lock(state_path):
        state = read_json(state_path)
        controller_mutation(state, args)
        current_control = active_round(state).get("execution_control") or {}
        global_done = phase_terminal(state, "initial_global") or bool(current_control.get("initial_global_plan_complete") and not any(node["phase"] == "initial_global" and node["status"] not in TERMINAL_STATUSES for node in state["execution_graph"]["nodes"]))
        local_done = phase_terminal(state, "initial_local") or bool(current_control.get("initial_local_plan_complete") and not any(node["phase"] == "initial_local" and node["status"] not in TERMINAL_STATUSES for node in state["execution_graph"]["nodes"]))
        if not (global_done and local_done) and not args.override_gate:
            raise ValueError("initial_global and initial_local must be terminal before automatic additional exploration")
        round_item = active_round(state)
        control = round_item.setdefault("execution_control", {})
        already_planned = int(control.get("additional_nodes_planned") or 0)
        maximum = int(round_item.get("resource_envelope", {}).get("max_additional_nodes") or 0)
        remaining = max(0, maximum - already_planned)
        if remaining == 0:
            raise ValueError(f"Round additional-exploration budget is exhausted ({maximum})")
        requested = min(args.count, remaining)
        candidates = candidate_cells(state, capabilities, profile)
        selected = balanced_sample(candidates, requested, args.seed, state)
        planned: list[str] = []
        for item in selected:
            node, created = plan_node(
                state, capabilities, state_path.parent, item["capability_id"], item["dependencies"], "additional_exploration",
                "coverage不足層からseed付きランダム非復元抽出した追加探索。", item["parameters"],
            )
            if created:
                node["coverage_stratum"] = item["stratum"]
                planned.append(node["node_id"])
        event = {
            "seed": args.seed, "requested_count": args.count, "accepted_count": requested, "candidate_count": len(candidates),
            "candidate_pool_hash": value_hash(sorted(item["signature"] for item in candidates)),
            "selected_signatures": [item["signature"] for item in selected], "selected_node_ids": planned,
            "sampling": "seeded_balanced_without_replacement", "created_at": utc_now(),
        }
        round_item["sampling_events"].append(event)
        control["additional_nodes_planned"] = already_planned + len(planned)
        control["additional_candidate_pool_exhausted"] = not bool(candidates)
        append_history(state, "additional_exploration_planned", **event)
        update_coverage_index(state_path, state)
        write_state(state_path, state)
    print(json.dumps(event, ensure_ascii=False, indent=2))
    return 0


def latest_entity_view(path: Path, id_key: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in read_jsonl(path):
        identifier = str(item[id_key])
        if identifier not in result or int(item.get("revision", 1)) >= int(result[identifier].get("revision", 1)):
            result[identifier] = item
    return result


def cmd_question_add(args: argparse.Namespace) -> int:
    state_path = Path(args.state).resolve()
    with state_lock(state_path):
        state = read_json(state_path)
        controller_mutation(state, args)
        target_groups = [value for value in (args.target_group or "").split(",") if value]
        evidence_ids = [value for value in (args.evidence or "").split(",") if value]
        operator_ids = [value for value in (args.operator or "").split(",") if value]
        known_groups = {row["group_id"] for row in read_csv_rows(Path(state["indices"]["group"]["registry_path"]))}
        known_evidence = {row["evidence_id"] for row in read_jsonl(Path(state["indices"]["evidence_digest"]["path"]))}
        known_operators = {key for key, value in catalog_by_id().items() if value["stage"] == "analysis"}
        if set(target_groups) - known_groups:
            raise ValueError(f"Unknown Run-global Group IDs: {sorted(set(target_groups) - known_groups)}")
        if set(evidence_ids) - known_evidence:
            raise ValueError(f"Unknown Evidence IDs: {sorted(set(evidence_ids) - known_evidence)}")
        if set(operator_ids) - known_operators:
            raise ValueError(f"Unknown Operator capability IDs: {sorted(set(operator_ids) - known_operators)}")
        question_id = allocate_id(state, "question")[0]
        item = {
            "question_id": question_id, "revision": 1, "title": args.title, "rationale": args.rationale,
            "deep_dive_potential": args.deep_dive_potential, "agent_priority": args.priority,
            "human_decision": "unreviewed", "status": "open", "reopen_recommended": False,
            "target_group_ids": target_groups, "evidence_ids": evidence_ids, "operator_ids": operator_ids,
            "origin_round_id": active_round(state)["round_id"], "last_updated_round_id": active_round(state)["round_id"],
            "created_at": utc_now(),
        }
        append_jsonl(Path(state["indices"]["questions"]["path"]), item)
        state["indices"]["questions"]["count"] = len(latest_entity_view(Path(state["indices"]["questions"]["path"]), "question_id"))
        append_history(state, "question_added", question_id=question_id)
        write_state(state_path, state)
    print(json.dumps(item, ensure_ascii=False, indent=2))
    return 0


def cmd_question_decision(args: argparse.Namespace) -> int:
    state_path = Path(args.state).resolve()
    with state_lock(state_path):
        state = read_json(state_path)
        controller_mutation(state, args)
        path = Path(state["indices"]["questions"]["path"])
        current = latest_entity_view(path, "question_id").get(args.question_id)
        if current is None:
            raise ValueError(f"Unknown Question: {args.question_id}")
        item = dict(current)
        item.update({"revision": int(current.get("revision", 1)) + 1, "human_decision": args.decision, "decision_rationale": args.rationale, "last_updated_round_id": active_round(state)["round_id"], "updated_at": utc_now()})
        append_jsonl(path, item)
        append_history(state, "question_decision", question_id=args.question_id, decision=args.decision)
        write_state(state_path, state)
    return 0


def group_source_node(state: dict[str, Any], group_id: str) -> dict[str, Any]:
    row = next((item for item in read_csv_rows(Path(state["indices"]["group"]["registry_path"])) if item.get("group_id") == group_id), None)
    if row is None:
        raise ValueError(f"Unknown Group: {group_id}")
    return state_nodes(state)[row["source_node_id"]]


def sibling_group_ids(state: dict[str, Any], grouping: dict[str, Any], target_group_id: str, limit: int = 3) -> list[str]:
    selected = select_representative_groups(state, grouping, limit + 1)
    result = [item["row"]["group_id"] for item in selected if item["row"]["group_id"] != target_group_id]
    if len(result) < limit:
        remaining = sorted(
            (
                row for row in read_csv_rows(Path(state["indices"]["group"]["registry_path"]))
                if row.get("source_node_id") == grouping["node_id"]
                and row.get("status") == "active"
                and row.get("group_id") != target_group_id
                and row.get("group_id") not in result
            ),
            key=lambda row: (-int(row.get("compound_count") or 0), row["group_id"]),
        )
        result.extend(row["group_id"] for row in remaining[: max(0, limit - len(result))])
    return result[:limit]


def cmd_plan_deep_dive(args: argparse.Namespace) -> int:
    state_path = Path(args.state).resolve()
    capabilities = catalog_by_id()
    profile = load_profile()
    with state_lock(state_path):
        state = read_json(state_path)
        controller_mutation(state, args)
        questions = latest_entity_view(Path(state["indices"]["questions"]["path"]), "question_id")
        question = questions.get(args.question_id)
        if question is None:
            raise ValueError(f"Unknown Question: {args.question_id}")
        if question.get("human_decision") == "skip":
            raise ValueError("Human decision is skip; deep-dive planning is blocked")
        if question.get("human_decision") == "defer":
            raise ValueError("Human decision is defer; deep-dive planning is paused")
        if not question.get("deep_dive_potential", False) and question.get("human_decision") != "allow":
            raise ValueError("Question is not marked for deep dive; an explicit human allow decision is required")
        target_groups = question.get("target_group_ids") or []
        if not target_groups:
            raise ValueError("Question requires at least one target_group_id for automatic deep-dive planning")
        descriptions = master_description_nodes(state, profile)
        operator_ids = question.get("operator_ids") or profile["initial_exploration"]["local_operator_capabilities"]
        planned: list[str] = []
        for group_id in target_groups:
            grouping = group_source_node(state, group_id)
            siblings = sibling_group_ids(state, grouping, group_id)
            for operator_id in operator_ids:
                capability = capabilities[operator_id]
                if "within-group" in (capability.get("scope_support") or []):
                    for dependencies in dependency_sets_for_operator(capability, descriptions, [grouping], "within-group"):
                        node, created = plan_node(
                            state, capabilities, state_path.parent, operator_id, dependencies, "deep_dive",
                            f"Question {args.question_id}のtarget Groupを異Operator／異Descriptionで比較する。",
                            {"scope_mode": "within-group", "target_group": group_id}, [args.question_id],
                        )
                        if created:
                            planned.append(node["node_id"])
                        for sibling_id in siblings:
                            sibling, sibling_created = plan_node(
                                state, capabilities, state_path.parent, operator_id, dependencies, "deep_dive",
                                f"Question {args.question_id}のsibling Group {sibling_id} comparator。",
                                {"scope_mode": "within-group", "target_group": sibling_id}, [args.question_id],
                            )
                            if sibling_created:
                                planned.append(sibling["node_id"])
                if siblings and "between-groups" in (capability.get("scope_support") or []):
                    for dependencies in dependency_sets_for_operator(capability, descriptions, [grouping], "within-group"):
                        comparison, comparison_created = plan_node(
                            state, capabilities, state_path.parent, operator_id, dependencies, "deep_dive",
                            f"Question {args.question_id}のtarget対sibling直接比較。",
                            {"scope_mode": "between-groups", "target_group": group_id, "comparison_group": siblings[0]}, [args.question_id],
                        )
                        if comparison_created:
                            planned.append(comparison["node_id"])
                if "global" in (capability.get("scope_support") or []):
                    global_grouping = [grouping] if "grouping" in (capability.get("dependencies") or []) else []
                    for dependencies in dependency_sets_for_operator(capability, descriptions, global_grouping, "global"):
                        node, created = plan_node(
                            state, capabilities, state_path.parent, operator_id, dependencies, "deep_dive",
                            f"Question {args.question_id}のglobal comparator。", {"scope_mode": "global"}, [args.question_id],
                        )
                        if created:
                            planned.append(node["node_id"])
        append_history(state, "deep_dive_planned", question_id=args.question_id, node_ids=planned, bundle_roles=["target_other_operators", "sibling_groups", "global_comparator", "cross_description", "between_group_control"])
        update_coverage_index(state_path, state)
        write_state(state_path, state)
    print(json.dumps({"question_id": args.question_id, "planned_nodes": planned}, ensure_ascii=False, indent=2))
    return 0


def cmd_salience_set(args: argparse.Namespace) -> int:
    state_path = Path(args.state).resolve()
    with state_lock(state_path):
        state = read_json(state_path)
        controller_mutation(state, args)
        digest_ids = {item["evidence_id"] for item in read_jsonl(Path(state["indices"]["evidence_digest"]["path"]))}
        if args.evidence_id not in digest_ids:
            raise ValueError(f"Unknown Evidence: {args.evidence_id}")
        history_path = Path(state["indices"]["salience"]["history_path"])
        event = {
            "event_id": allocate_id(state, "salience_event")[0], "evidence_id": args.evidence_id,
            "attention_class": args.attention_class, "scientific_role": args.scientific_role,
            "human_pinned": args.human_pin, "reason": args.reason, "round_id": active_round(state)["round_id"], "created_at": utc_now(),
        }
        append_jsonl(history_path, event)
        rebuild_salience_view(state)
        append_history(state, "salience_changed", **event)
        write_state(state_path, state)
    return 0


def rebuild_salience_view(state: dict[str, Any]) -> None:
    latest: dict[str, dict[str, Any]] = {}
    for event in read_jsonl(Path(state["indices"]["salience"]["history_path"])):
        latest[event["evidence_id"]] = event
    write_jsonl(Path(state["indices"]["salience"]["view_path"]), [latest[key] for key in sorted(latest)])


def reserve_interpretation_ids(state: dict[str, Any], node: dict[str, Any], counts: dict[str, int]) -> dict[str, Any]:
    path = Path(node["output_dir"]) / "id_reservation.json"
    if path.exists():
        return read_json(path)
    reservation = {
        "schema_version": "1.0.0", "run_id": state["run"]["run_id"], "node_id": node["node_id"], "round_id": node["round_id"],
        "finding_ids": allocate_id(state, "finding", counts["finding"]),
        "hypothesis_ids": allocate_id(state, "hypothesis", counts["hypothesis"]),
        "question_ids": allocate_id(state, "question", counts["question"]),
        "relation_ids": allocate_id(state, "relation", counts["relation"]),
        "request_ids": allocate_id(state, "request", counts["request"]), "reserved_at": utc_now(),
        "revisable_ids": {
            "finding_ids": sorted(latest_entity_view(Path(state["indices"]["findings"]["path"]), "finding_id")),
            "hypothesis_ids": sorted(latest_entity_view(Path(state["indices"]["hypotheses"]["path"]), "hypothesis_id")),
            "question_ids": sorted(latest_entity_view(Path(state["indices"]["questions"]["path"]), "question_id")),
            "relation_ids": sorted(latest_entity_view(Path(state["indices"]["relations"]["path"]), "relation_id")),
            "request_ids": sorted(latest_entity_view(Path(state["indices"]["requests"]["path"]), "request_id")),
        },
    }
    validate_json(reservation, "interpretation_id_reservation.schema.json")
    write_json(path, reservation)
    node["id_reservation_path"] = str(path.resolve())
    return reservation


def cmd_reserve_interpretation_ids(args: argparse.Namespace) -> int:
    state_path = Path(args.state).resolve()
    with state_lock(state_path):
        state = read_json(state_path)
        controller_mutation(state, args)
        node = state_nodes(state).get(args.node_id)
        if node is None or node["stage"] != "interpretation":
            raise ValueError("--node-id must identify an Interpretation Node")
        reservation = reserve_interpretation_ids(state, node, {"finding": args.findings, "hypothesis": args.hypotheses, "question": args.questions, "relation": args.relations, "request": args.requests})
        append_history(state, "interpretation_ids_reserved", node_id=node["node_id"], path=node["id_reservation_path"])
        write_state(state_path, state)
    print(json.dumps(reservation, ensure_ascii=False, indent=2))
    return 0


def run_compound_ids(state: dict[str, Any]) -> list[str]:
    with Path(state["run"]["input"]).open(encoding="utf-8-sig", newline="") as handle:
        return [str(row[state["run"]["id_column"]]).strip() for row in csv.DictReader(handle)]


def grouping_semantics(capability_id: str) -> str:
    if capability_id in {"C005", "C006"}:
        return "exclusive_partition"
    if capability_id == "C007":
        return "exclusive_partition_with_noise"
    if capability_id in {"C001", "C002", "C003", "C004", "C008", "C009", "C010", "C011", "C012"}:
        return "overlapping_sets"
    return "unknown"


def rebuild_group_matrix_shards(state: dict[str, Any], registry_rows: list[dict[str, str]], compounds: list[str]) -> None:
    """Materialize the human-auditable compound-by-Run-Group Boolean matrix."""
    group_root = Path(state["indices"]["group"]["registry_path"]).parent
    groups_by_shard: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in registry_rows:
        number = int(str(row["group_id"])[1:])
        groups_by_shard[number // 100000].append(row)
    shard_records: list[dict[str, Any]] = []
    for shard_number, group_rows in sorted(groups_by_shard.items()):
        lower = shard_number * 100000
        upper = lower + 99999
        group_ids = sorted((row["group_id"] for row in group_rows), key=lambda value: int(value[1:]))
        membership: dict[str, dict[str, bool]] = {compound: {} for compound in compounds}
        node_paths = {row["source_node_id"]: Path(row["node_membership_artifact"]) for row in group_rows}
        for node_path in node_paths.values():
            for source in read_csv_rows(node_path):
                compound = source.get("compound_id")
                if compound not in membership:
                    continue
                for group_id in group_ids:
                    if group_id in source:
                        membership[compound][group_id] = str(source[group_id]).strip().lower() in {"true", "1", "yes"}
        rows = [{"compound_id": compound, **{group_id: str(membership[compound].get(group_id, False)) for group_id in group_ids}} for compound in compounds]
        path = group_root / f"Cpd_Group_matrix_G{lower:06d}_{upper:06d}.csv"
        write_csv_rows(path, ["compound_id", *group_ids], rows)
        shard_records.append({"path": str(path.resolve()), "first_group_id": f"G{lower:06d}", "last_group_id": f"G{upper:06d}", "group_count": len(group_ids)})
    state["indices"]["group"]["matrix_shards"] = shard_records


def update_group_index(state_path: Path, state: dict[str, Any], node: dict[str, Any], membership_path: Path, registry_path: Path) -> None:
    registry_json = read_json(registry_path)
    if not isinstance(registry_json, list):
        raise ValueError("group_registry.json must contain an array")
    local_ids = [str(item.get("group_id") or "") for item in registry_json]
    if any(not item for item in local_ids) or len(local_ids) != len(set(local_ids)):
        raise ValueError("Grouping artifact contains blank or duplicate local Group IDs")
    long_memberships = membership_sets(membership_path)
    compounds = run_compound_ids(state)
    compound_set = set(compounds)
    for members in long_memberships.values():
        unknown = members - compound_set
        if unknown:
            raise ValueError(f"Grouping membership contains unknown compound IDs: {sorted(unknown)[:10]}")
    registry_file = Path(state["indices"]["group"]["registry_path"])
    rows = read_csv_rows(registry_file)
    existing_by_source_local = {(row["source_node_id"], row["local_group_id"]): row for row in rows}
    source_description_nodes = binding_node_ids(node["input_bindings"], "description")
    source_grouping_nodes = binding_node_ids(node["input_bindings"], "grouping")
    endpoint = load_compound_endpoint(state)
    local_to_global: dict[str, str] = {}
    for item in registry_json:
        local_id = str(item["group_id"])
        existing = existing_by_source_local.get((node["node_id"], local_id))
        group_id = existing["group_id"] if existing else allocate_id(state, "group")[0]
        local_to_global[local_id] = group_id
        members = long_memberships.get(local_id, set())
        values = [endpoint[compound] for compound in members if compound in endpoint]
        mean = sum(values) / len(values) if values else 0.0
        variance = sum((value - mean) ** 2 for value in values) / max(1, len(values) - 1) if len(values) > 1 else 0.0
        row = existing or {field: "" for field in GROUP_REGISTRY_FIELDS}
        previous_status = row.get("status")
        row.update({
            "group_id": group_id, "local_group_id": local_id, "group_label": str(item.get("group_label") or local_id),
            "grouping_capability_id": node["capability_id"], "grouping_skill_name": node["skill_name"],
            "source_node_id": node["node_id"], "source_description_id": str(item.get("source_description_id") or ""),
            "source_description_node_id": source_description_nodes[0] if source_description_nodes else "",
            "source_grouping_node_ids": ";".join(source_grouping_nodes), "membership_semantics": grouping_semantics(node["capability_id"]),
            "compound_count": str(len(members)), "sample_fraction": str(len(members) / max(1, state["run"]["row_count"])),
            "endpoint_variance": str(variance), "activity_blind": str(bool(item.get("activity_blind", True))),
            "status": "deprioritized" if previous_status == "deprioritized" else "active",
            "membership_artifact": str(membership_path.resolve()), "definition_json": json.dumps(item.get("definition") or {}, ensure_ascii=False, sort_keys=True),
            "created_at": row.get("created_at") or utc_now(),
        })
        if existing is None:
            rows.append(row)
    node_membership_path = registry_file.parent / "by_node" / f"{node['node_id']}.csv"
    node_rows = []
    for compound in compounds:
        row: dict[str, Any] = {"compound_id": compound}
        for local_id, group_id in local_to_global.items():
            row[group_id] = str(compound in long_memberships.get(local_id, set()))
        node_rows.append(row)
    write_csv_rows(node_membership_path, ["compound_id", *local_to_global.values()], node_rows)
    for row in rows:
        if row["source_node_id"] == node["node_id"]:
            row["node_membership_artifact"] = str(node_membership_path.resolve())
    write_csv_rows(registry_file, GROUP_REGISTRY_FIELDS, rows)
    node["global_membership_path"] = str(node_membership_path.resolve())
    group_index = state["indices"]["group"]
    group_index["by_node"][node["node_id"]] = str(node_membership_path.resolve())
    group_index["group_count"] = len(rows)
    group_index["active_group_count"] = sum(row.get("status") == "active" for row in rows)
    group_index["deprioritized_group_count"] = sum(row.get("status") == "deprioritized" for row in rows)
    group_index["updated_at"] = utc_now()
    rebuild_group_matrix_shards(state, rows, compounds)


def evidence_digest(evidence: dict[str, Any], node: dict[str, Any], path: Path) -> dict[str, Any]:
    scope = evidence.get("scope") or {}
    machine = evidence.get("machine_readable_summary") or {}
    comparison_keys = {
        "operator_id": evidence.get("operator_id"), "scope_mode": scope.get("mode", "global"),
        "target_group_id": evidence.get("target_group_id") or scope.get("target_group_id"),
        "comparison_group_id": scope.get("comparison_group_id"),
        "evaluation_representation": evidence.get("evaluation_representation"),
        "grouping_representation": evidence.get("grouping_representation"),
        "metric": machine.get("metric"),
    }
    digest = {
        "schema_version": "1.0.0", "evidence_id": evidence["evidence_id"], "source_node_id": node["node_id"],
        "round_id": node["round_id"], "operator_id": evidence["operator_id"], "scope_mode": scope.get("mode", "global"),
        "sample_count": int(evidence.get("sample_count") or scope.get("sample_count") or 0),
        "target_group_id": comparison_keys["target_group_id"], "evaluation_representation": evidence.get("evaluation_representation"),
        "grouping_representation": evidence.get("grouping_representation"), "metric": machine.get("metric"),
        "summary": evidence.get("human_readable_summary") or "", "warnings": evidence.get("warnings") or [],
        "key_statistics": {key: machine[key] for key in sorted(machine) if isinstance(machine[key], (int, float, bool, str)) and key not in {"scope"}},
        "artifact_path": str(path.resolve()), "comparison_keys": comparison_keys, "created_at": evidence.get("created_at") or utc_now(),
    }
    validate_json(digest, "evidence_digest.schema.json")
    return digest


def upsert_jsonl(path: Path, key: str, value: dict[str, Any]) -> None:
    values = read_jsonl(path)
    replaced = False
    for index, item in enumerate(values):
        if item.get(key) == value.get(key):
            values[index] = value
            replaced = True
            break
    if not replaced:
        values.append(value)
    write_jsonl(path, values)


def register_evidence(state: dict[str, Any], node: dict[str, Any], path: Path) -> None:
    evidence = read_json(path)
    if evidence.get("evidence_id") != node.get("evidence_id"):
        raise ValueError(f"Evidence ID must use the State reservation {node.get('evidence_id')}")
    digest = evidence_digest(evidence, node, path)
    digest_path = Path(state["indices"]["evidence_digest"]["path"])
    upsert_jsonl(digest_path, "evidence_id", digest)
    state["indices"]["evidence_digest"]["count"] = len(read_jsonl(digest_path))
    salience_path = Path(state["indices"]["salience"]["history_path"])
    if not any(item.get("evidence_id") == evidence["evidence_id"] for item in read_jsonl(salience_path)):
        append_jsonl(salience_path, {
            "event_id": allocate_id(state, "salience_event")[0], "evidence_id": evidence["evidence_id"],
            "attention_class": "untriaged", "scientific_role": "inconclusive", "human_pinned": False,
            "reason": "New Evidence registered", "round_id": node["round_id"], "created_at": utc_now(),
        })
    rebuild_salience_view(state)


def register_interpretation(state: dict[str, Any], node: dict[str, Any], path: Path) -> None:
    value = read_json(path)
    if value.get("run_id") != state["run"]["run_id"] or value.get("interpretation_id") != node["node_id"]:
        raise ValueError("Interpretation identity does not match State reservation")
    if value.get("report_status") != "agent_interpreted" or not (value.get("agent_review") or {}).get("completed"):
        raise ValueError("Only a dedicated-Agent finalized Interpretation can be recorded as succeeded")
    reservation_path = Path(node.get("id_reservation_path") or (Path(node["output_dir"]) / "id_reservation.json"))
    if not reservation_path.is_file():
        raise ValueError("Interpretation ID reservation is missing")
    reservation = read_json(reservation_path)
    revisable = reservation.get("revisable_ids") or {}
    allowed = {
        "notable_findings": set(reservation["finding_ids"]) | set(revisable.get("finding_ids") or []),
        "hypotheses": set(reservation["hypothesis_ids"]) | set(revisable.get("hypothesis_ids") or []),
        "questions": set(reservation["question_ids"]) | set(revisable.get("question_ids") or []),
        "evidence_relations": set(reservation["relation_ids"]) | set(revisable.get("relation_ids") or []),
        "analysis_requests": set(reservation["request_ids"]) | set(revisable.get("request_ids") or []),
    }
    keys = {"notable_findings": "finding_id", "hypotheses": "hypothesis_id", "questions": "question_id", "evidence_relations": "relation_id", "analysis_requests": "request_id"}
    for collection, key in keys.items():
        for item in value.get(collection) or []:
            identifier = item.get(key)
            if identifier not in allowed[collection]:
                raise ValueError(f"{identifier} is outside the Interpretation ID reservation")
    ledger_map = {
        "notable_findings": ("findings", "finding_id"), "hypotheses": ("hypotheses", "hypothesis_id"),
        "questions": ("questions", "question_id"), "evidence_relations": ("relations", "relation_id"),
        "analysis_requests": ("requests", "request_id"),
    }
    known_groups = {row["group_id"] for row in read_csv_rows(Path(state["indices"]["group"]["registry_path"]))}
    for question in value.get("questions") or []:
        unknown_groups = set(question.get("target_group_ids") or []) - known_groups
        if unknown_groups:
            raise ValueError(f"Question references unknown Run-global Group IDs: {sorted(unknown_groups)}")
    for collection, (index_name, entity_key) in ledger_map.items():
        ledger_path = Path(state["indices"][index_name]["path"])
        latest = latest_entity_view(ledger_path, entity_key)
        for raw in value.get(collection) or []:
            item = dict(raw)
            item.setdefault("revision", 1)
            item.setdefault("origin_round_id", node["round_id"])
            item["last_updated_round_id"] = node["round_id"]
            previous = latest.get(item[entity_key])
            if previous and int(item["revision"]) <= int(previous.get("revision", 1)):
                raise ValueError(f"{item[entity_key]} revision must increase beyond {previous.get('revision', 1)}")
            append_jsonl(ledger_path, item)
        state["indices"][index_name]["count"] = len(latest_entity_view(ledger_path, entity_key))
    node["interpretation_entities"] = {name: [item[keys[name]] for item in value.get(name) or []] for name in keys}


def set_downstream_stale(state: dict[str, Any], source: str) -> list[str]:
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in state["execution_graph"]["edges"]:
        adjacency[edge["source"]].append(edge["target"])
    visited: set[str] = set()
    queue = deque(adjacency[source])
    nodes = state_nodes(state)
    while queue:
        node_id = queue.popleft()
        if node_id in visited:
            continue
        visited.add(node_id)
        if nodes[node_id]["status"] == "succeeded":
            nodes[node_id]["status"] = "stale"
        queue.extend(adjacency[node_id])
    return sorted(visited)


def node_readiness_error(state: dict[str, Any], node: dict[str, Any]) -> str | None:
    gate_error = package_gate_error(state)
    if gate_error:
        return gate_error
    if node["human_approval"] in {"bundle_pending", "required"}:
        return "Human approval is required"
    if node["human_approval"] == "rejected":
        return "Human approval was rejected"
    if node["stage"] != "interpretation" and round_time_status(state)["status"] in {"interpretation_reserve", "expired"}:
        return "Round time control permits only Interpretation and close activities"
    nodes = state_nodes(state)
    for dependency in node["dependencies"]:
        status = nodes[dependency]["status"]
        if status != "succeeded":
            return f"Dependency {dependency} is {status}"
    return None


def round_time_status(state: dict[str, Any]) -> dict[str, Any]:
    item = active_round(state, required=False)
    if item is None:
        return {"status": "no_active_round", "remaining_minutes": 0, "reserve_minutes": 0, "deadline_at": None}
    control = item.get("execution_control") or {}
    deadline = parse_timestamp(control.get("deadline_at"))
    remaining = ((deadline - datetime.now(timezone.utc)).total_seconds() / 60.0) if deadline else float("inf")
    reserve = int(control.get("interpretation_reserve_minutes") or 0)
    status = "available"
    if remaining <= 0:
        status = "expired"
    elif remaining <= reserve:
        status = "interpretation_reserve"
    return {
        "status": status, "remaining_minutes": max(0.0, round(remaining, 2)),
        "reserve_minutes": reserve, "deadline_at": control.get("deadline_at"),
    }


def interpretation_gate(state: dict[str, Any], round_id: str | None = None) -> dict[str, Any]:
    item = active_round(state, required=False)
    selected_round = round_id or (item or {}).get("round_id")
    if not selected_round:
        return {"status": "not_applicable", "reason_codes": ["NO_ACTIVE_ROUND"], "analysis_node_ids": [], "interpretation_node_ids": []}
    analysis = [
        node for node in state["execution_graph"]["nodes"]
        if node["round_id"] == selected_round and node["stage"] == "analysis" and node["status"] == "succeeded"
    ]
    interpretations = [
        node for node in state["execution_graph"]["nodes"]
        if node["round_id"] == selected_round and node["stage"] == "interpretation" and node["status"] == "succeeded"
    ]
    artifact_valid: list[dict[str, Any]] = []
    valid: list[str] = []
    missing_artifacts: list[str] = []
    stale_interpretations: list[str] = []
    for node in interpretations:
        output = Path(node["output_dir"])
        expected = [output / "interpretation.json", output / "interpretation.md", output / "interpretation.html"]
        if all(path.is_file() and path.stat().st_size > 0 for path in expected):
            artifact_valid.append(node)
        else:
            missing_artifacts.append(node["node_id"])
    analysis_times = [
        timestamp for timestamp in
        (parse_timestamp(node.get("finished_at") or node.get("started_at") or node.get("requested_at")) for node in analysis)
        if timestamp is not None
    ]
    latest_analysis_at = max(analysis_times, default=None)
    for node in artifact_valid:
        interpretation_at = parse_timestamp(node.get("finished_at") or node.get("started_at") or node.get("requested_at"))
        if latest_analysis_at is not None and (interpretation_at is None or interpretation_at < latest_analysis_at):
            stale_interpretations.append(node["node_id"])
        else:
            valid.append(node["node_id"])
    reasons: list[str] = []
    status = "satisfied"
    if analysis and not valid:
        status = "blocked"
        reasons.append("INTERPRETATION_REQUIRED")
    if missing_artifacts:
        status = "blocked"
        reasons.append("INTERPRETATION_ARTIFACTS_MISSING")
    if stale_interpretations:
        status = "blocked"
        reasons.append("INTERPRETATION_PRECEDES_LATEST_OPERATOR")
    if not analysis:
        reasons.append("NO_NEW_OPERATOR_EVIDENCE")
    return {
        "status": status, "reason_codes": reasons,
        "analysis_node_ids": [node["node_id"] for node in analysis],
        "interpretation_node_ids": [node["node_id"] for node in interpretations],
        "valid_interpretation_node_ids": valid,
        "invalid_interpretation_node_ids": missing_artifacts,
        "stale_interpretation_node_ids": stale_interpretations,
    }


def runnable_nodes(state: dict[str, Any]) -> list[dict[str, Any]]:
    running = sum(node["status"] == "running" for node in state["execution_graph"]["nodes"])
    available = max(0, state["run"]["parallel_limit"] - running)
    phase_order = {"basic_compute": 0, "initial_global": 1, "initial_local": 2, "additional_exploration": 3, "deep_dive": 4, "human_directed": 5}
    stage_order = {"description": 0, "grouping": 1, "analysis": 2, "interpretation": 3}
    time_status = round_time_status(state)
    result = [node for node in state["execution_graph"]["nodes"] if node["status"] in {"pending", "stale"} and node_readiness_error(state, node) is None]
    if time_status["status"] in {"interpretation_reserve", "expired"}:
        result = [node for node in result if node["stage"] == "interpretation"]
    result.sort(key=lambda node: (phase_order[node["phase"]], stage_order[node["stage"]], node["node_id"]))
    return result[:available]


def cmd_start(args: argparse.Namespace) -> int:
    state_path = Path(args.state).resolve()
    with state_lock(state_path):
        state = read_json(state_path)
        controller_mutation(state, args)
        node = state_nodes(state).get(args.node_id)
        if node is None:
            raise ValueError(f"Unknown Node: {args.node_id}")
        retryable = node["status"] in {"failed", "unavailable"} and args.retry
        if node["status"] not in {"pending", "stale"} and not retryable:
            raise ValueError(f"Node is not startable: {node['status']}")
        error = node_readiness_error(state, node)
        if error:
            raise ValueError(error)
        running = [item["node_id"] for item in state["execution_graph"]["nodes"] if item["status"] == "running"]
        if len(running) >= int(state["run"]["parallel_limit"]):
            raise ValueError(f"Parallel limit reached ({state['run']['parallel_limit']}): {running}")
        attempt_number = len(node.get("execution_attempts") or []) + 1
        attempt_id = f"{node['node_id']}-TRY{attempt_number:03d}"
        attempt = {"attempt_id": attempt_id, "number": attempt_number, "status": "running", "started_at": utc_now(), "finished_at": None}
        node.setdefault("execution_attempts", []).append(attempt)
        node["current_attempt_id"] = attempt_id
        node["status"] = "running"; node["started_at"] = attempt["started_at"]
        append_history(state, "node_started", node_id=node["node_id"], attempt_id=attempt_id)
        update_coverage_index(state_path, state); write_state(state_path, state)
    return 0


def cmd_mark_terminal(args: argparse.Namespace) -> int:
    state_path = Path(args.state).resolve()
    with state_lock(state_path):
        state = read_json(state_path)
        controller_mutation(state, args)
        node = state_nodes(state).get(args.node_id)
        if node is None:
            raise ValueError(f"Unknown Node: {args.node_id}")
        node["status"] = args.status; node["terminal_reason"] = args.reason; node["finished_at"] = utc_now()
        for attempt in reversed(node.get("execution_attempts") or []):
            if attempt.get("attempt_id") == node.get("current_attempt_id"):
                attempt.update({"status": args.status, "finished_at": node["finished_at"], "reason": args.reason})
                break
        node["current_attempt_id"] = None
        cascaded = cascade_terminal_dependencies(state)
        append_history(state, "node_marked_terminal", node_id=node["node_id"], status=args.status, reason=args.reason, cascaded_node_ids=cascaded)
        update_coverage_index(state_path, state); write_state(state_path, state)
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    state_path = Path(args.state).resolve(); event_path = Path(args.event).resolve()
    event = read_json(event_path); validate_json(event, "execution_event.schema.json")
    with state_lock(state_path):
        state = read_json(state_path)
        controller_mutation(state, args)
        node = state_nodes(state).get(event["node_id"])
        if node is None:
            raise ValueError(f"Event Node is not planned: {event['node_id']}")
        for key, expected in [("run_id", state["run"]["run_id"]), ("project", state["run"]["project"]), ("capability_id", node["capability_id"]), ("skill_name", node["skill_name"])]:
            if event.get(key) != expected:
                raise ValueError(f"Event {key} does not match State")
        if node["stage"] in {"analysis", "interpretation"} and event.get("round_id") != node["round_id"]:
            raise ValueError("Event round_id does not match the planned Node")
        if node["status"] != "running":
            raise ValueError("Only a running Node can record an event")
        mismatches = {key: {"expected": value, "actual": event.get("configuration", {}).get(key, "<missing>")} for key, value in node["parameters"].items() if key not in event.get("configuration", {}) or event["configuration"][key] != value}
        if mismatches:
            raise ValueError(f"Event configuration does not match planned parameters: {mismatches}")
        artifacts: list[dict[str, Any]] = []
        group_membership = group_registry = evidence_path = interpretation_path = None
        for raw in event.get("artifacts") or []:
            artifact = dict(raw); path = (event_path.parent / str(artifact["path"])).resolve()
            if not path.is_file():
                raise FileNotFoundError(path)
            if artifact.get("sha256") and file_hash(path) != artifact["sha256"]:
                raise ValueError(f"Artifact hash mismatch: {path}")
            artifact["resolved_path"] = str(path); artifacts.append(artifact)
            if artifact["type"] == "group_membership": group_membership = path
            if artifact["type"] == "group_registry": group_registry = path
            if artifact["type"] == "evidence": evidence_path = path
            if artifact["type"] == "interpretation" and path.name == "interpretation.json": interpretation_path = path
        previous_hashes = (node.get("input_hash"), node.get("config_hash"))
        node.update({"status": event["status"], "input_hash": event["input_hash"], "config_hash": event["config_hash"], "configuration": event["configuration"], "artifacts": artifacts, "warnings": event.get("warnings") or [], "started_at": event.get("started_at"), "finished_at": event.get("finished_at")})
        for attempt in reversed(node.get("execution_attempts") or []):
            if attempt.get("attempt_id") == node.get("current_attempt_id"):
                attempt.update({"status": event["status"], "finished_at": event.get("finished_at"), "event_path": str(event_path)})
                break
        node["current_attempt_id"] = None
        if node["stage"] == "grouping" and event["status"] == "succeeded":
            if not group_membership or not group_registry:
                raise ValueError("Successful Grouping requires membership and registry artifacts")
            update_group_index(state_path, state, node, group_membership, group_registry)
        if node["stage"] == "analysis" and event["status"] == "succeeded":
            artifact_types = {item["type"] for item in artifacts}
            required_types = {"operator_result", "operator_report", "evidence", "evidence_digest"}
            if required_types - artifact_types:
                raise ValueError(f"Successful Operator is missing artifacts: {sorted(required_types - artifact_types)}")
            if event.get("configuration", {}).get("evidence_id") != node.get("evidence_id"):
                raise ValueError("Operator event does not use the reserved Evidence ID")
            register_evidence(state, node, evidence_path)
        if node["stage"] == "interpretation" and event["status"] == "succeeded":
            if interpretation_path is None:
                raise ValueError("Successful Interpretation requires interpretation.json")
            register_interpretation(state, node, interpretation_path)
        cascaded = cascade_terminal_dependencies(state) if event["status"] != "succeeded" else []
        changed = any(old and old != new for old, new in zip(previous_hashes, (event["input_hash"], event["config_hash"])))
        invalidated = set_downstream_stale(state, node["node_id"]) if changed else []
        append_history(state, "event_recorded", node_id=node["node_id"], status=node["status"], invalidated=invalidated, cascaded_node_ids=cascaded)
        update_coverage_index(state_path, state); write_state(state_path, state)
    return 0


def update_coverage_index(state_path: Path, state: dict[str, Any]) -> None:
    cells = []
    for node in state["execution_graph"]["nodes"]:
        cells.append({
            "node_id": node["node_id"], "capability_id": node["capability_id"], "stage": node["stage"],
            "phase": node["phase"], "round_id": node["round_id"], "status": node["status"],
            "description_node_id": (binding_node_ids(node["input_bindings"], "description") or [None])[0],
            "grouping_node_id": (binding_node_ids(node["input_bindings"], "grouping") or [None])[0],
            "scope_mode": node["parameters"].get("scope_mode"), "target_group_id": node["parameters"].get("target_group"),
            "analysis_signature": node["analysis_signature"], "reason": node.get("terminal_reason") or node.get("selection_reason"),
        })
    write_json(Path(state["indices"]["coverage"]["path"]), {"schema_version": "1.0.0", "cells": cells, "updated_at": utc_now()})


def compact_rounds(state: dict[str, Any]) -> list[dict[str, Any]]:
    return bounded(({
        "round_id": item["round_id"], "status": item["status"], "started_at": item["started_at"],
        "ended_at": item.get("ended_at"), "stop_reason": (item.get("execution_control") or {}).get("stop_reason"),
    } for item in state["round_control"]["rounds"]), 5)


def build_state_summary(state: dict[str, Any]) -> dict[str, Any]:
    status_counts: dict[str, int] = defaultdict(int)
    phase_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for node in state["execution_graph"]["nodes"]:
        status_counts[node["status"]] += 1; phase_counts[node["phase"]][node["status"]] += 1
    questions = list(latest_entity_view(Path(state["indices"]["questions"]["path"]), "question_id").values())
    salience = read_jsonl(Path(state["indices"]["salience"]["view_path"]))
    priority = [item for item in salience if item.get("attention_class") == "priority" or item.get("human_pinned")]
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION, "run": {key: state["run"][key] for key in ["run_id", "project", "input", "endpoint", "higher_is_better", "row_count", "profile_id"]},
        "package_change_gate": state["run"].get("package_change_gate"),
        "round_control": {"active_round_id": state["round_control"]["active_round_id"], "next_round_number": state["round_control"]["next_round_number"], "rounds": compact_rounds(state)},
        "node_count": len(state["execution_graph"]["nodes"]), "status_counts": dict(status_counts),
        "phase_counts": {phase: dict(counts) for phase, counts in phase_counts.items()},
        "runnable_node_ids": [node["node_id"] for node in runnable_nodes(state)][:SUMMARY_LIMIT],
        "runnable_count": len([node for node in state["execution_graph"]["nodes"] if node["status"] in {"pending", "stale"} and node_readiness_error(state, node) is None]),
        "group_index": {key: state["indices"]["group"].get(key) for key in ["group_count", "active_group_count", "deprioritized_group_count", "registry_path"]},
        "evidence_count": state["indices"]["evidence_digest"]["count"],
        "priority_evidence": priority[-SUMMARY_LIMIT:],
        "active_questions": bounded((item for item in questions if item.get("status") in {"open", "in_progress"} and item.get("human_decision") != "skip"), SUMMARY_LIMIT),
        "human_skipped_question_count": sum(item.get("human_decision") == "skip" for item in questions),
        "failed_or_unavailable": bounded(({"node_id": node["node_id"], "capability_id": node["capability_id"], "status": node["status"], "reason": node.get("terminal_reason")} for node in state["execution_graph"]["nodes"] if node["status"] in {"failed", "unavailable"}), SUMMARY_LIMIT),
        "time_budget": round_time_status(state),
        "interpretation_gate": interpretation_gate(state),
        "updated_at": state["updated_at"],
    }


def required_control_actions(state: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    gate = state["run"].get("package_change_gate") or {}
    if gate.get("status") != "clear":
        return [{"code": "PACKAGE_APPROVAL_REQUIRED", "blocking": True}]
    current = active_round(state, required=False)
    if current is None:
        handoff = (state.get("orchestration_control") or {}).get("migration_handoff") or {}
        if handoff.get("status") == "awaiting_human_start":
            return [{"code": "MIGRATION_HANDOFF_REQUIRED", "blocking": True, "next_round_id": f"RND{state['round_control']['next_round_number']:04d}", "reason": "EXPLICIT_HUMAN_START_REQUIRED"}]
        return [{"code": "START_NEXT_ROUND", "blocking": True, "next_round_id": f"RND{state['round_control']['next_round_number']:04d}"}]
    nodes = state["execution_graph"]["nodes"]
    control = current.get("execution_control") or {}
    if not control.get("basic_plan_complete"):
        return [{"code": "PLAN_BASIC", "blocking": True}]
    bundle = state["run"].get("high_cost_bundle") or {}
    if bundle.get("status") == "pending" and any(node.get("human_approval") == "bundle_pending" for node in nodes):
        actions.append({"code": "REQUEST_BASIC_BUNDLE_APPROVAL", "blocking": True})
    running = [node["node_id"] for node in nodes if node["status"] == "running"]
    if running:
        actions.append({"code": "WAIT_OR_RECONCILE_RUNNING", "blocking": True, "node_ids": running[:SUMMARY_LIMIT]})
    runnable = runnable_nodes(state)
    if runnable:
        actions.append({"code": "EXECUTE_RUNNABLE_BATCH", "blocking": False, "node_ids": [node["node_id"] for node in runnable]})
    basic_done = phase_terminal(state, "basic_compute")
    global_done = phase_terminal(state, "initial_global") or bool(control.get("initial_global_plan_complete") and not any(node["phase"] == "initial_global" and node["status"] not in TERMINAL_STATUSES for node in nodes))
    local_done = phase_terminal(state, "initial_local") or bool(control.get("initial_local_plan_complete") and not any(node["phase"] == "initial_local" and node["status"] not in TERMINAL_STATUSES for node in nodes))
    planning_action = False
    if not running and not runnable and basic_done and not control.get("initial_global_plan_complete"):
        actions.append({"code": "PLAN_INITIAL_GLOBAL", "blocking": True}); planning_action = True
    elif not running and not runnable and global_done and not control.get("initial_local_plan_complete"):
        actions.append({"code": "PLAN_INITIAL_LOCAL_BATCH", "blocking": True, "batch_size": 120}); planning_action = True
    elif not running and not runnable and global_done and local_done and round_time_status(state)["status"] == "available":
        additional_limit = int(current.get("resource_envelope", {}).get("max_additional_nodes") or 0)
        additional_count = int(control.get("additional_nodes_planned") or 0)
        if additional_count < additional_limit and not control.get("additional_candidate_pool_exhausted"):
            actions.append({"code": "PLAN_BALANCED_ADDITIONAL", "blocking": False, "remaining_budget": additional_limit - additional_count}); planning_action = True
    interpretation = interpretation_gate(state)
    if interpretation["status"] == "blocked" and ((not running and not runnable and not planning_action) or round_time_status(state)["status"] != "available"):
        pending_i = [node["node_id"] for node in nodes if node["round_id"] == current["round_id"] and node["stage"] == "interpretation" and node["status"] in {"pending", "running", "failed", "stale"}]
        actions.append({"code": "CREATE_OR_COMPLETE_INTERPRETATION", "blocking": True, "node_ids": pending_i[:SUMMARY_LIMIT]})
    if not running and not runnable and not planning_action and interpretation["status"] == "satisfied":
        actions.append({"code": "ROUND_CLOSE_READY", "blocking": False})
    if round_time_status(state)["status"] in {"interpretation_reserve", "expired"}:
        actions.append({"code": "STOP_SCIENTIFIC_EXPANSION", "blocking": True})
    return actions


def scientific_decision_card(state: dict[str, Any]) -> dict[str, Any]:
    questions = list(latest_entity_view(Path(state["indices"]["questions"]["path"]), "question_id").values())
    candidates = [item for item in questions if item.get("status") in {"open", "in_progress"} and item.get("human_decision") not in {"skip", "defer"}]
    return {
        "code": "SELECT_DEEP_DIVE_OR_BALANCED_ADDITION" if candidates else "SELECT_BALANCED_ADDITION_OR_CLOSE",
        "candidate_question_ids": [item["question_id"] for item in candidates[:SUMMARY_LIMIT]],
        "instruction": "Choose scientific priority from compact candidates; deterministic runtime will validate and register the chosen action.",
    }


def build_orchestrator_brief(state_path: Path, state: dict[str, Any]) -> dict[str, Any]:
    lease = dict((state.get("orchestration_control") or {}).get("lease") or {})
    lease.pop("token_hash", None)
    return {
        "schema_version": "1.0.0", "run_id": state["run"]["run_id"], "state_path": str(state_path.resolve()),
        "active_round_id": state["round_control"]["active_round_id"], "controller_lease": lease,
        "required_control_action": required_control_actions(state),
        "scientific_decision": scientific_decision_card(state),
        "time_budget": round_time_status(state), "interpretation_gate": interpretation_gate(state),
        "counts": build_state_summary(state)["status_counts"], "updated_at": state["updated_at"],
    }


def refresh_state_summary(state_path: Path, state: dict[str, Any]) -> None:
    summary_root = state_path.parent / "summaries"
    write_json(summary_root / "state_summary.json", build_state_summary(state))
    write_json(summary_root / "orchestrator_brief.json", build_orchestrator_brief(state_path, state))


def round_node_delta(state: dict[str, Any], round_id: str) -> list[dict[str, Any]]:
    return [{"node_id": node["node_id"], "capability_id": node["capability_id"], "phase": node["phase"], "status": node["status"]} for node in state["execution_graph"]["nodes"] if node["round_id"] == round_id]


def write_round_handoff(state_path: Path, state: dict[str, Any], round_item: dict[str, Any]) -> None:
    round_root = state_path.parent / "rounds" / round_item["round_id"]
    node_delta = round_node_delta(state, round_item["round_id"])
    questions = list(latest_entity_view(Path(state["indices"]["questions"]["path"]), "question_id").values())
    all_digests = read_jsonl(Path(state["indices"]["evidence_digest"]["path"]))
    round_digests = [item for item in all_digests if item.get("round_id") == round_item["round_id"]]
    salience_view = read_jsonl(Path(state["indices"]["salience"]["view_path"]))
    salience_history = read_jsonl(Path(state["indices"]["salience"]["history_path"]))
    round_triage = [item for item in salience_history if item.get("round_id") == round_item["round_id"]]
    summary = {
        "schema_version": "1.0.0", "run_id": state["run"]["run_id"], "round_id": round_item["round_id"], "status": round_item["status"],
        "request": round_item["request"], "node_delta": node_delta,
        "new_or_active_questions": [item for item in questions if item.get("origin_round_id") == round_item["round_id"] or item.get("status") in {"open", "in_progress"}],
        "pending_approval": [node["node_id"] for node in state["execution_graph"]["nodes"] if node["human_approval"] in {"bundle_pending", "required"} and node["status"] == "pending"],
        "created_at": utc_now(),
    }
    write_json(round_root / "round_summary.json", summary)
    lines = [f"# {round_item['round_id']} Summary", "", f"- Status: {round_item['status']}", f"- Request: {round_item['request']}", "", "## Node delta", ""]
    lines.extend(f"- {item['node_id']} / {item['capability_id']} / {item['phase']} / {item['status']}" for item in node_delta)
    atomic_write_text(round_root / "round_summary.md", "\n".join(lines) + "\n")
    brief = {
        "schema_version": "1.0.0", "run_id": state["run"]["run_id"], "state_path": str(state_path.resolve()),
        "completed_round_id": round_item["round_id"], "next_round_id": f"RND{state['round_control']['next_round_number']:04d}",
        "mandatory_gaps": [item for item in build_state_summary(state)["failed_or_unavailable"]],
        "active_question_ids": [item["question_id"] for item in questions if item.get("status") in {"open", "in_progress"} and item.get("human_decision") != "skip"],
        "recommended_entry": "Read summaries/state_summary.json, this brief, active Question digests, then plan the next Round without rereading all Evidence.",
        "created_at": utc_now(),
    }
    write_json(round_root / "next_round_brief.json", brief)
    write_json(round_root / "evidence_set_manifest.json", {
        "schema_version": "1.0.0", "run_id": state["run"]["run_id"], "round_id": round_item["round_id"],
        "evidence_count": len(round_digests), "evidence": round_digests, "created_at": utc_now(),
    })
    write_json(round_root / "triage_updates.json", {
        "schema_version": "1.0.0", "run_id": state["run"]["run_id"], "round_id": round_item["round_id"],
        "events": round_triage, "current_view": salience_view, "created_at": utc_now(),
    })
    artifact_names = [
        "round_request.md", "round_summary.json", "round_summary.md", "evidence_set_manifest.json",
        "triage_updates.json", "next_round_brief.json",
    ]
    artifacts = []
    for name in artifact_names:
        path = round_root / name
        if path.is_file():
            artifacts.append({"name": name, "path": str(path.resolve()), "sha256": file_hash(path), "bytes": path.stat().st_size})
    write_json(round_root / "round_manifest.json", {
        "schema_version": "1.0.0", "run_id": state["run"]["run_id"], "round_id": round_item["round_id"],
        "status": round_item["status"], "artifacts": artifacts, "created_at": utc_now(),
    })


def cmd_round_start(args: argparse.Namespace) -> int:
    state_path = Path(args.state).resolve()
    with state_lock(state_path):
        state = read_json(state_path)
        controller_mutation(state, args)
        handoff = (state.get("orchestration_control") or {}).get("migration_handoff") or {}
        if handoff.get("status") == "awaiting_human_start" and not args.accept_migration:
            raise ValueError("Starting the first post-migration Round requires --accept-migration after an explicit human instruction")
        if args.accept_migration and handoff.get("status") != "awaiting_human_start":
            raise ValueError("--accept-migration is valid only for a pending Migration handoff")
        gate = detect_package_change(state, find_workspace())
        if gate["status"] != "clear":
            append_history(state, "package_change_detected", differences=gate["differences"])
            write_state(state_path, state)
            raise ValueError("Package differs from the Run snapshot; approve or reject the package change before starting a Round")
        expected = f"RND{state['round_control']['next_round_number']:04d}"
        if args.round_id != expected:
            active_id = state["round_control"]["active_round_id"]
            if args.round_id == active_id:
                item = active_round(state); item["status"] = "active"
                append_history(state, "round_resumed", round_id=args.round_id)
                write_state(state_path, state); return 0
            raise ValueError(f"Requested Round must be {expected}; State was not changed")
        envelope = {"walltime_minutes": args.walltime_minutes, "max_additional_nodes": args.max_additional_nodes, "interpretation_iterations": args.interpretation_iterations}
        created_round = create_round(state, state_path.parent, args.request, envelope)
        if handoff.get("status") == "awaiting_human_start":
            handoff.update({"status": "accepted", "accepted_at": utc_now(), "accepted_round_id": created_round["round_id"]})
            append_history(state, "migration_handoff_accepted", round_id=created_round["round_id"])
        write_state(state_path, state)
    return 0


def cmd_round_end(args: argparse.Namespace) -> int:
    state_path = Path(args.state).resolve()
    with state_lock(state_path):
        state = read_json(state_path)
        controller_mutation(state, args)
        item = active_round(state)
        if item["round_id"] != args.round_id:
            raise ValueError("Round ID does not match the active Round")
        running = [node["node_id"] for node in state["execution_graph"]["nodes"] if node["round_id"] == args.round_id and node["status"] == "running"]
        if running:
            raise ValueError(f"Round has running Nodes: {running}")
        close_gate = interpretation_gate(state, args.round_id)
        item["close_gate"] = {**close_gate, "checked_at": utc_now()}
        if args.status in {"checkpoint", "completed"} and close_gate["status"] == "blocked":
            write_state(state_path, state)
            raise ValueError(f"Round close is blocked: {close_gate['reason_codes']}; complete and record Interpretation first")
        item["status"] = args.status; item["ended_at"] = utc_now(); item["end_reason"] = args.reason
        item.setdefault("execution_control", {})["stop_reason"] = args.stop_reason or args.reason
        if args.status in {"completed", "checkpoint"}:
            state["round_control"]["active_round_id"] = None
        append_history(state, "round_ended", round_id=args.round_id, status=args.status, reason=args.reason)
        write_round_handoff(state_path, state, item); write_state(state_path, state)
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    state_path = Path(args.state).resolve(); capabilities = catalog_by_id()
    capability = capabilities.get(args.capability_id)
    if capability is None:
        raise ValueError(f"Capability is not in Catalog: {args.capability_id}")
    parameters = json.loads(args.parameters_json) if args.parameters_json else {}
    if not isinstance(parameters, dict):
        raise ValueError("--parameters-json must be an object")
    dependencies = [value for value in (args.depends_on or "").split(",") if value]
    with state_lock(state_path):
        state = read_json(state_path)
        controller_mutation(state, args)
        node, created = plan_node(state, capabilities, state_path.parent, args.capability_id, dependencies, "human_directed", args.reason, parameters)
        append_history(state, "human_directed_node_requested", node_id=node["node_id"], created=created, reason=args.reason)
        update_coverage_index(state_path, state); write_state(state_path, state)
    print(json.dumps({"node": node, "created": created}, ensure_ascii=False, indent=2))
    return 0


def cmd_add_interpretation(args: argparse.Namespace) -> int:
    state_path = Path(args.state).resolve(); capabilities = catalog_by_id()
    with state_lock(state_path):
        state = read_json(state_path)
        controller_mutation(state, args)
        if args.evidence_node:
            dependencies = [value for value in args.evidence_node.split(",") if value]
        else:
            evidence_to_node = {
                node.get("evidence_id"): node["node_id"] for node in state["execution_graph"]["nodes"]
                if node["stage"] == "analysis" and node["status"] == "succeeded" and node.get("evidence_id")
            }
            current_round = active_round(state)
            selected = {
                node["node_id"] for node in state["execution_graph"]["nodes"]
                if node["stage"] == "analysis" and node["status"] == "succeeded" and node["round_id"] == current_round["round_id"]
            }
            for item in read_jsonl(Path(state["indices"]["salience"]["view_path"])):
                if item.get("human_pinned") or item.get("attention_class") in {"priority", "candidate"}:
                    if item.get("evidence_id") in evidence_to_node:
                        selected.add(evidence_to_node[item["evidence_id"]])
            for item in latest_entity_view(Path(state["indices"]["questions"]["path"]), "question_id").values():
                if item.get("status") in {"open", "in_progress"} and item.get("human_decision") != "skip":
                    selected.update(evidence_to_node[eid] for eid in item.get("evidence_ids") or [] if eid in evidence_to_node)
            if not selected:
                fallback = [
                    node["node_id"] for node in state["execution_graph"]["nodes"]
                    if node["stage"] == "analysis" and node["status"] == "succeeded"
                ]
                selected.update(fallback[-args.max_full_evidence:])
            dependencies = sorted(selected)[:args.max_full_evidence]
        interpretation_parameters = {"interpretation_focus": args.focus} if args.focus else {}
        node, created = plan_node(state, capabilities, state_path.parent, "I001", dependencies, args.phase, args.reason, interpretation_parameters)
        if created:
            reserve_interpretation_ids(state, node, {"finding": args.findings, "hypothesis": args.hypotheses, "question": args.questions, "relation": args.relations, "request": args.requests})
        append_history(state, "interpretation_planned", node_id=node["node_id"], created=created)
        update_coverage_index(state_path, state); write_state(state_path, state)
    print(json.dumps({"node": node, "created": created}, ensure_ascii=False, indent=2))
    return 0


def cmd_deprioritize_group(args: argparse.Namespace) -> int:
    state_path = Path(args.state).resolve(); requested = {value for value in args.group_id.split(",") if value}
    with state_lock(state_path):
        state = read_json(state_path)
        controller_mutation(state, args)
        path = Path(state["indices"]["group"]["registry_path"]); rows = read_csv_rows(path)
        known = {row["group_id"] for row in rows}
        if requested - known:
            raise ValueError(f"Unknown Group IDs: {sorted(requested - known)}")
        for row in rows:
            if row["group_id"] in requested:
                row["status"] = "deprioritized"; row["deprioritize_reason"] = args.reason; row["deprioritized_at"] = utc_now()
        write_csv_rows(path, GROUP_REGISTRY_FIELDS, rows)
        state["indices"]["group"]["active_group_count"] = sum(row["status"] == "active" for row in rows)
        state["indices"]["group"]["deprioritized_group_count"] = sum(row["status"] == "deprioritized" for row in rows)
        append_history(state, "groups_deprioritized", group_ids=sorted(requested), reason=args.reason); write_state(state_path, state)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    state = read_json(Path(args.state)); print(json.dumps(build_state_summary(state), ensure_ascii=False, indent=2)); return 0


def cmd_runnable(args: argparse.Namespace) -> int:
    state = read_json(Path(args.state)); print(json.dumps(runnable_nodes(state), ensure_ascii=False, indent=2)); return 0


def audit_state(state_path: Path, state: dict[str, Any], mode: str = "quick") -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(code: str, passed: bool, detail: Any = None, severity: str = "error") -> None:
        checks.append({"code": code, "passed": bool(passed), "severity": severity, "detail": detail})

    try:
        validate_dag(state)
        check("DAG_ACYCLIC", True)
    except Exception as exc:
        check("DAG_ACYCLIC", False, str(exc))
    node_ids = [node["node_id"] for node in state["execution_graph"]["nodes"]]
    check("NODE_IDS_UNIQUE", len(node_ids) == len(set(node_ids)), {"count": len(node_ids), "unique": len(set(node_ids))})
    signatures = [node["analysis_signature"] for node in state["execution_graph"]["nodes"] if node["status"] != "stale"]
    check("ACTIVE_SIGNATURES_UNIQUE", len(signatures) == len(set(signatures)), {"count": len(signatures), "unique": len(set(signatures))})
    running = [node for node in state["execution_graph"]["nodes"] if node["status"] == "running"]
    check("PARALLEL_LIMIT", len(running) <= int(state["run"]["parallel_limit"]), {"running": len(running), "limit": state["run"]["parallel_limit"]})
    orphan_running = [node["node_id"] for node in running if not node.get("current_attempt_id")]
    check("RUNNING_HAS_ATTEMPT", not orphan_running, orphan_running)
    lease = (state.get("orchestration_control") or {}).get("lease") or {}
    live = lease_is_live(state)
    check("LEASE_WELL_FORMED", not lease.get("token_hash") or bool(lease.get("owner_id") and lease.get("expires_at")), {"owner_id": lease.get("owner_id"), "live": live})
    handoff = (state.get("orchestration_control") or {}).get("migration_handoff") or {}
    if handoff.get("status") == "awaiting_human_start":
        post_migration_nodes = [node["node_id"] for node in state["execution_graph"]["nodes"] if node.get("round_id") != "RND0001"]
        check("MIGRATION_HANDOFF_SAFE", state["round_control"].get("active_round_id") is None and not post_migration_nodes, {"active_round_id": state["round_control"].get("active_round_id"), "post_migration_nodes": post_migration_nodes})
    gate = interpretation_gate(state)
    check("INTERPRETATION_CLOSE_GATE", gate["status"] != "blocked", gate, severity="warning")
    if mode == "full":
        missing: list[dict[str, str]] = []
        hash_mismatches: list[dict[str, str]] = []
        for node in state["execution_graph"]["nodes"]:
            if node["status"] != "succeeded":
                continue
            for artifact in node.get("artifacts") or []:
                path_value = artifact.get("resolved_path")
                if not path_value:
                    continue
                path = Path(path_value)
                if not path.is_file():
                    missing.append({"node_id": node["node_id"], "path": str(path)})
                elif artifact.get("sha256") and file_hash(path) != artifact["sha256"]:
                    hash_mismatches.append({"node_id": node["node_id"], "path": str(path)})
        check("SUCCEEDED_ARTIFACTS_EXIST", not missing, missing)
        check("SUCCEEDED_ARTIFACT_HASHES", not hash_mismatches, hash_mismatches)
    errors = [item for item in checks if not item["passed"] and item["severity"] == "error"]
    warnings = [item for item in checks if not item["passed"] and item["severity"] == "warning"]
    return {
        "schema_version": "1.0.0", "mode": mode, "run_id": state["run"]["run_id"],
        "state_path": str(state_path.resolve()), "status": "fail" if errors else ("warning" if warnings else "pass"),
        "error_count": len(errors), "warning_count": len(warnings), "checks": checks, "created_at": utc_now(),
    }


def write_audit_result(state_path: Path, result: dict[str, Any]) -> Path:
    output = state_path.parent / "audit" / timestamp_id()
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "audit.json", result)
    lines = [f"# CONDUCTOR {result['mode'].title()} Audit", "", f"- Status: {result['status']}", f"- Run: {result['run_id']}", "", "## Checks", ""]
    for item in result["checks"]:
        mark = "PASS" if item["passed"] else item["severity"].upper()
        lines.append(f"- [{mark}] `{item['code']}` — {json.dumps(item.get('detail'), ensure_ascii=False)}")
    atomic_write_text(output / "audit.md", "\n".join(lines) + "\n")
    return output


def cmd_bootstrap(args: argparse.Namespace) -> int:
    state_path = Path(args.state).resolve()
    with state_lock(state_path):
        state = read_json(state_path)
        control = state.get("orchestration_control")
        if not control:
            raise ValueError("v4.3.0 State cannot be bootstrapped directly; use the migration Skill")
        lease = control["lease"]
        live = lease_is_live(state)
        supplied_matches = bool(args.lease_token and token_hash(args.lease_token) == lease.get("token_hash"))
        if live and not supplied_matches and not args.force_takeover:
            brief = build_orchestrator_brief(state_path, state)
            print(json.dumps({"lease_acquired": False, "reason_code": "LEASE_HELD_BY_OTHER_CONTROLLER", "brief": brief}, ensure_ascii=False, indent=2))
            return 0
        if live and args.force_takeover and not args.takeover_reason:
            raise ValueError("--force-takeover requires --takeover-reason")
        token = args.lease_token if supplied_matches else secrets.token_urlsafe(32)
        previous_owner = lease.get("owner_id")
        control["controller_epoch"] = int(control.get("controller_epoch") or 0) + (0 if supplied_matches else 1)
        now = datetime.now(timezone.utc)
        duration = max(5, int(args.lease_minutes))
        lease.update({
            "owner_id": args.owner_id, "token_hash": token_hash(token), "epoch": control["controller_epoch"],
            "acquired_at": lease.get("acquired_at") if supplied_matches else now.isoformat(),
            "heartbeat_at": now.isoformat(), "expires_at": (now + timedelta(minutes=duration)).isoformat(),
            "duration_minutes": duration,
        })
        control["last_bootstrap_at"] = now.isoformat()
        gate = detect_package_change(state, find_workspace())
        action = "controller_lease_renewed" if supplied_matches else ("controller_lease_taken_over" if previous_owner else "controller_lease_acquired")
        append_history(state, action, owner_id=args.owner_id, previous_owner_id=previous_owner, epoch=lease["epoch"], reason=args.takeover_reason)
        audit = audit_state(state_path, state, "quick")
        audit_path = write_audit_result(state_path, audit)
        control["last_audit_path"] = str(audit_path.resolve())
        write_state(state_path, state)
        result = {"lease_acquired": True, "lease_token": token, "audit": audit, "brief": build_orchestrator_brief(state_path, state)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_heartbeat(args: argparse.Namespace) -> int:
    state_path = Path(args.state).resolve()
    with state_lock(state_path):
        state = read_json(state_path)
        controller_mutation(state, args)
        append_history(state, "controller_heartbeat", owner_id=state["orchestration_control"]["lease"].get("owner_id"))
        write_state(state_path, state)
    print(json.dumps(build_orchestrator_brief(state_path, state), ensure_ascii=False, indent=2))
    return 0


def cmd_release_lease(args: argparse.Namespace) -> int:
    state_path = Path(args.state).resolve()
    with state_lock(state_path):
        state = read_json(state_path)
        require_controller(state, args)
        owner = state["orchestration_control"]["lease"].get("owner_id")
        append_history(state, "controller_lease_released", owner_id=owner, reason=args.reason)
        state["orchestration_control"]["lease"] = {
            "owner_id": None, "token_hash": None, "epoch": state["orchestration_control"]["controller_epoch"],
            "acquired_at": None, "heartbeat_at": None, "expires_at": None, "duration_minutes": DEFAULT_LEASE_MINUTES,
        }
        write_state(state_path, state)
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    state = read_json(Path(args.state).resolve())
    identifiers = [value for value in (args.ids or "").split(",") if value]
    if args.kind == "brief":
        value: Any = build_orchestrator_brief(Path(args.state).resolve(), state)
    elif args.kind == "node":
        nodes = state_nodes(state)
        value = [nodes[item] for item in identifiers if item in nodes]
    elif args.kind == "question":
        latest = latest_entity_view(Path(state["indices"]["questions"]["path"]), "question_id")
        value = [latest[item] for item in identifiers if item in latest] if identifiers else bounded(latest.values(), args.limit)
    elif args.kind == "evidence":
        rows = {item["evidence_id"]: item for item in read_jsonl(Path(state["indices"]["evidence_digest"]["path"]))}
        value = [rows[item] for item in identifiers if item in rows] if identifiers else bounded(rows.values(), args.limit)
    else:
        value = {
            "runnable": runnable_nodes(state)[:args.limit],
            "questions": bounded(latest_entity_view(Path(state["indices"]["questions"]["path"]), "question_id").values(), args.limit),
            "priority_evidence": build_state_summary(state)["priority_evidence"][:args.limit],
        }
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    state_path = Path(args.state).resolve()
    with state_lock(state_path):
        state = read_json(state_path)
        controller_mutation(state, args)
        input_hash = file_hash(Path(state["run"]["input"]))
        if input_hash != state["run"]["input_hash"]:
            for node in state["execution_graph"]["nodes"]:
                if node["status"] == "succeeded": node["status"] = "stale"
            state["run"]["input_hash"] = input_hash; append_history(state, "input_changed_all_nodes_stale")
        gate = detect_package_change(state, find_workspace())
        package_changed = gate["status"] != "clear"
        append_history(state, "resumed", package_changed=package_changed, differences=gate["differences"])
        update_coverage_index(state_path, state); write_state(state_path, state)
    print(json.dumps({"package_changed": package_changed, "package_change_gate": gate, "runnable": runnable_nodes(state)}, ensure_ascii=False, indent=2))
    return 0


def cmd_approve_package_change(args: argparse.Namespace) -> int:
    state_path = Path(args.state).resolve()
    workspace = find_workspace()
    with state_lock(state_path):
        state = read_json(state_path)
        controller_mutation(state, args)
        gate = detect_package_change(state, workspace)
        if not gate["differences"]:
            raise ValueError("The active package already matches the Run snapshot")
        if not args.approve:
            gate.update({"status": "rejected", "decided_at": utc_now(), "decision_rationale": args.rationale})
            append_history(state, "package_change_rejected", differences=gate["differences"], rationale=args.rationale)
            write_state(state_path, state)
            print(json.dumps(gate, ensure_ascii=False, indent=2))
            return 0
        if current_package_hashes(workspace) != gate["current_hashes"]:
            raise ValueError("Package changed again after inspection; run resume and review the new differences")
        previous = state["run"]["package_snapshot"]
        state["run"].setdefault("package_snapshot_history", []).append(previous)
        label = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        profile = load_profile(workspace)
        state["run"]["package_snapshot"] = snapshot_package(workspace, state_path.parent, profile, label)
        state["run"]["profile_id"] = profile["profile_id"]
        bundle = state["run"]["high_cost_bundle"]
        updated_scope = dict(bundle.get("scope") or {})
        updated_scope.update({
            "profile_id": profile["profile_id"],
            "profile_hash": file_hash(workspace / "CONDUCTOR_modules" / "catalog" / "analysis_profile.json"),
            "catalog_hash": file_hash(workspace / "CONDUCTOR_modules" / "catalog" / "catalog.json"),
            "capability_ids": profile["basic_compute"]["high_cost_bundle"],
        })
        updated_scope_hash = value_hash(updated_scope)
        if updated_scope_hash != bundle.get("scope_hash"):
            bundle.update({
                "capability_ids": profile["basic_compute"]["high_cost_bundle"],
                "status": "pending", "scope": updated_scope, "scope_hash": updated_scope_hash,
            })
            bundle.pop("decided_scope_hash", None)
            for node in state["execution_graph"]["nodes"]:
                if node["phase"] == "basic_compute" and node["status"] == "pending" and node["capability_id"] in bundle["capability_ids"]:
                    node["human_approval"] = "bundle_pending"
        gate.update({
            "status": "clear", "decided_at": utc_now(), "decision": "approved",
            "decision_rationale": args.rationale,
            "accepted_snapshot_hash": state["run"]["package_snapshot"]["snapshot_hash"],
        })
        append_history(state, "package_change_approved", differences=gate["differences"], rationale=args.rationale)
        write_state(state_path, state)
    print(json.dumps(gate, ensure_ascii=False, indent=2))
    return 0


def cmd_rebuild_indices(args: argparse.Namespace) -> int:
    state_path = Path(args.state).resolve()
    with state_lock(state_path):
        state = read_json(state_path)
        controller_mutation(state, args)
        write_jsonl(Path(state["indices"]["evidence_digest"]["path"]), [])
        state["indices"]["evidence_digest"]["count"] = 0
        for node in state["execution_graph"]["nodes"]:
            if node["stage"] == "analysis" and node["status"] == "succeeded":
                path = Path(node["output_dir"]) / "evidence.json"
                if path.is_file(): register_evidence(state, node, path)
        update_coverage_index(state_path, state); rebuild_salience_view(state)
        append_history(state, "indices_rebuilt"); write_state(state_path, state)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage a CONDUCTOR 4.3.1 multi-Round State DAG.")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init"); init.add_argument("--input", required=True); init.add_argument("--endpoint", required=True); init.add_argument("--higher-is-better", action=argparse.BooleanOptionalAction, required=True); init.add_argument("--project", required=True); init.add_argument("--parallel-limit", type=int, required=True); init.add_argument("--assay-column"); init.add_argument("--run-id"); init.add_argument("--output-dir"); init.add_argument("--request"); init.add_argument("--walltime-minutes", type=int, default=480); init.add_argument("--max-additional-nodes", type=int, default=300); init.add_argument("--interpretation-iterations", type=int, default=3); init.set_defaults(func=cmd_init)
    bootstrap = sub.add_parser("bootstrap"); bootstrap.add_argument("--state", required=True); bootstrap.add_argument("--owner-id", required=True); bootstrap.add_argument("--lease-token"); bootstrap.add_argument("--lease-minutes", type=int, default=DEFAULT_LEASE_MINUTES); bootstrap.add_argument("--force-takeover", action="store_true"); bootstrap.add_argument("--takeover-reason"); bootstrap.set_defaults(func=cmd_bootstrap)
    heartbeat = sub.add_parser("heartbeat"); heartbeat.add_argument("--state", required=True); heartbeat.set_defaults(func=cmd_heartbeat)
    release = sub.add_parser("release-lease"); release.add_argument("--state", required=True); release.add_argument("--reason", required=True); release.set_defaults(func=cmd_release_lease)
    query = sub.add_parser("query"); query.add_argument("--state", required=True); query.add_argument("--kind", choices=["brief", "node", "question", "evidence", "batch"], required=True); query.add_argument("--ids"); query.add_argument("--limit", type=int, default=20); query.set_defaults(func=cmd_query)
    plan_basic = sub.add_parser("plan-basic"); plan_basic.add_argument("--state", required=True); plan_basic.set_defaults(func=cmd_plan_basic)
    approve = sub.add_parser("approve-basic-bundle"); approve.add_argument("--state", required=True); choice = approve.add_mutually_exclusive_group(required=True); choice.add_argument("--approve", action="store_true"); choice.add_argument("--reject", dest="approve", action="store_false"); approve.add_argument("--rationale", required=True); approve.set_defaults(func=cmd_approve_basic_bundle)
    global_plan = sub.add_parser("plan-initial-global"); global_plan.add_argument("--state", required=True); global_plan.add_argument("--override-gate", action="store_true"); global_plan.set_defaults(func=cmd_plan_initial_global)
    local_plan = sub.add_parser("plan-initial-local"); local_plan.add_argument("--state", required=True); local_plan.add_argument("--override-gate", action="store_true"); local_plan.add_argument("--batch-size", type=int, default=120); local_plan.set_defaults(func=cmd_plan_initial_local)
    additional = sub.add_parser("plan-additional"); additional.add_argument("--state", required=True); additional.add_argument("--count", type=int, required=True); additional.add_argument("--seed", type=int, required=True); additional.add_argument("--override-gate", action="store_true"); additional.set_defaults(func=cmd_plan_additional)
    qadd = sub.add_parser("question-add"); qadd.add_argument("--state", required=True); qadd.add_argument("--title", required=True); qadd.add_argument("--rationale", required=True); qadd.add_argument("--deep-dive-potential", action=argparse.BooleanOptionalAction, default=True); qadd.add_argument("--priority", choices=["low", "medium", "high"], default="medium"); qadd.add_argument("--target-group"); qadd.add_argument("--evidence"); qadd.add_argument("--operator"); qadd.set_defaults(func=cmd_question_add)
    qdecision = sub.add_parser("question-decision"); qdecision.add_argument("--state", required=True); qdecision.add_argument("--question-id", required=True); qdecision.add_argument("--decision", choices=["unreviewed", "allow", "skip", "defer"], required=True); qdecision.add_argument("--rationale", required=True); qdecision.set_defaults(func=cmd_question_decision)
    deep = sub.add_parser("plan-deep-dive"); deep.add_argument("--state", required=True); deep.add_argument("--question-id", required=True); deep.set_defaults(func=cmd_plan_deep_dive)
    salience = sub.add_parser("salience-set"); salience.add_argument("--state", required=True); salience.add_argument("--evidence-id", required=True); salience.add_argument("--attention-class", choices=["untriaged", "routine", "candidate", "priority"], required=True); salience.add_argument("--scientific-role", choices=["signal", "no_signal", "support", "contradiction", "falsification", "control", "exception", "inconclusive"], required=True); salience.add_argument("--human-pin", action=argparse.BooleanOptionalAction, default=False); salience.add_argument("--reason", required=True); salience.set_defaults(func=cmd_salience_set)
    add = sub.add_parser("add"); add.add_argument("--state", required=True); add.add_argument("--capability-id", required=True); add.add_argument("--depends-on"); add.add_argument("--parameters-json"); add.add_argument("--reason", required=True); add.set_defaults(func=cmd_add)
    interpretation = sub.add_parser("add-interpretation"); interpretation.add_argument("--state", required=True); interpretation.add_argument("--evidence-node"); interpretation.add_argument("--phase", choices=["initial_local", "additional_exploration", "deep_dive", "human_directed"], default="human_directed"); interpretation.add_argument("--reason", required=True); interpretation.add_argument("--focus", help="Optional concise perspective; different focuses may create distinct Interpretation Nodes in one Round."); interpretation.add_argument("--max-full-evidence", type=int, default=200); interpretation.add_argument("--findings", type=int, default=200); interpretation.add_argument("--hypotheses", type=int, default=50); interpretation.add_argument("--questions", type=int, default=200); interpretation.add_argument("--relations", type=int, default=1000); interpretation.add_argument("--requests", type=int, default=200); interpretation.set_defaults(func=cmd_add_interpretation)
    reserve = sub.add_parser("reserve-interpretation-ids"); reserve.add_argument("--state", required=True); reserve.add_argument("--node-id", required=True); reserve.add_argument("--findings", type=int, default=200); reserve.add_argument("--hypotheses", type=int, default=50); reserve.add_argument("--questions", type=int, default=200); reserve.add_argument("--relations", type=int, default=1000); reserve.add_argument("--requests", type=int, default=200); reserve.set_defaults(func=cmd_reserve_interpretation_ids)
    start = sub.add_parser("start"); start.add_argument("--state", required=True); start.add_argument("--node-id", required=True); start.add_argument("--retry", action="store_true"); start.set_defaults(func=cmd_start)
    terminal = sub.add_parser("mark-terminal"); terminal.add_argument("--state", required=True); terminal.add_argument("--node-id", required=True); terminal.add_argument("--status", choices=["failed", "unavailable", "waived", "not_applicable", "skipped"], required=True); terminal.add_argument("--reason", required=True); terminal.set_defaults(func=cmd_mark_terminal)
    record = sub.add_parser("record"); record.add_argument("--state", required=True); record.add_argument("--event", required=True); record.set_defaults(func=cmd_record)
    runnable = sub.add_parser("runnable"); runnable.add_argument("--state", required=True); runnable.set_defaults(func=cmd_runnable)
    status = sub.add_parser("status"); status.add_argument("--state", required=True); status.set_defaults(func=cmd_status)
    degroup = sub.add_parser("deprioritize-group"); degroup.add_argument("--state", required=True); degroup.add_argument("--group-id", required=True); degroup.add_argument("--reason", required=True); degroup.set_defaults(func=cmd_deprioritize_group)
    round_start = sub.add_parser("round-start"); round_start.add_argument("--state", required=True); round_start.add_argument("--round-id", required=True); round_start.add_argument("--request", required=True); round_start.add_argument("--walltime-minutes", type=int, default=480); round_start.add_argument("--max-additional-nodes", type=int, default=300); round_start.add_argument("--interpretation-iterations", type=int, default=3); round_start.add_argument("--accept-migration", action="store_true", help="Required only for the first post-migration Round after an explicit human instruction."); round_start.set_defaults(func=cmd_round_start)
    round_end = sub.add_parser("round-end"); round_end.add_argument("--state", required=True); round_end.add_argument("--round-id", required=True); round_end.add_argument("--status", choices=["paused", "checkpoint", "completed"], required=True); round_end.add_argument("--reason", required=True); round_end.add_argument("--stop-reason", choices=["budget_exhausted", "no_eligible_work", "human_checkpoint", "completed_scope", "abnormal_interruption", "other"]); round_end.set_defaults(func=cmd_round_end)
    resume = sub.add_parser("resume"); resume.add_argument("--state", required=True); resume.set_defaults(func=cmd_resume)
    package = sub.add_parser("approve-package-change"); package.add_argument("--state", required=True); package_choice = package.add_mutually_exclusive_group(required=True); package_choice.add_argument("--approve", action="store_true"); package_choice.add_argument("--reject", dest="approve", action="store_false"); package.add_argument("--rationale", required=True); package.set_defaults(func=cmd_approve_package_change)
    rebuild = sub.add_parser("rebuild-indices"); rebuild.add_argument("--state", required=True); rebuild.set_defaults(func=cmd_rebuild_indices)
    for command_parser in [
        heartbeat, release, plan_basic, approve, global_plan, local_plan, additional, qadd, qdecision,
        deep, salience, add, interpretation, reserve, start, terminal, record, degroup, round_start,
        round_end, resume, package, rebuild,
    ]:
        add_lease_argument(command_parser)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    for name in ["parallel_limit", "walltime_minutes", "max_additional_nodes", "interpretation_iterations", "count", "findings", "hypotheses", "questions", "relations", "requests", "lease_minutes", "batch_size", "limit"]:
        if hasattr(args, name) and getattr(args, name) is not None and getattr(args, name) < 1:
            raise ValueError(f"--{name.replace('_', '-')} must be >= 1")
    if hasattr(args, "seed") and args.seed < 0:
        raise ValueError("--seed must be >= 0")
    return args.func(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
