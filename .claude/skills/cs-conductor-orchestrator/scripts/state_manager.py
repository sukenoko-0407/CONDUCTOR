from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


SKILL_DIR = Path(__file__).resolve().parents[1]


def find_workspace() -> Path:
    for candidate in [Path.cwd(), *Path.cwd().parents, SKILL_DIR, *SKILL_DIR.parents]:
        if (candidate / "catalog" / "catalog.json").exists() and (candidate / ".claude").exists():
            return candidate
    raise RuntimeError("CONDUCTOR workspace could not be located")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_id_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def write_state(path: Path, value: dict[str, Any]) -> None:
    value["updated_at"] = utc_now()
    validate_state(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def validate_state(value: dict[str, Any]) -> None:
    try:
        import jsonschema
    except ImportError as exc:
        raise RuntimeError("jsonschema is required") from exc
    schema = read_json(SKILL_DIR / "schemas" / "state.schema.json")
    jsonschema.validate(value, schema)


def validate_event(value: dict[str, Any]) -> None:
    try:
        import jsonschema
    except ImportError as exc:
        raise RuntimeError("jsonschema is required") from exc
    schema = read_json(SKILL_DIR / "schemas" / "execution_event.schema.json")
    jsonschema.validate(value, schema)


def catalog_by_id(workspace: Path) -> dict[str, dict[str, Any]]:
    catalog = read_json(workspace / "catalog" / "catalog.json")
    return {entry["capability_id"]: entry for entry in catalog["capabilities"]}


def state_nodes(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {node["node_id"]: node for node in state["execution_graph"]["nodes"]}


def append_history(state: dict[str, Any], action: str, **details: Any) -> None:
    state["history"].append({"timestamp": utc_now(), "action": action, **details})


def cmd_init(args: argparse.Namespace) -> int:
    workspace = find_workspace()
    input_path = Path(args.input).resolve()
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    with input_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames or []
        rows = list(reader) if args.assay_column else []
    if args.endpoint not in header:
        raise ValueError(f"Endpoint column not found: {args.endpoint}")
    if args.assay_column and args.assay_column not in header:
        raise ValueError(f"Assay column not found: {args.assay_column}")
    assay_levels = sorted({str(row.get(args.assay_column, "")).strip() for row in rows if str(row.get(args.assay_column, "")).strip()}) if args.assay_column else []
    run_id = args.run_id or run_id_now()
    outdir = Path(args.output_dir) if args.output_dir else workspace / "results" / "CONDUCTOR" / args.project / run_id
    state_path = outdir / "state.json"
    if state_path.exists() and not args.overwrite:
        raise FileExistsError(f"State exists; use --overwrite or resume it: {state_path}")
    state = {
        "schema_version": "1.0.0",
        "conductor_version": "4.0.0",
        "run": {"run_id": run_id, "project": args.project, "input": str(input_path), "input_hash": file_hash(input_path), "endpoint": args.endpoint, "higher_is_better": args.higher_is_better, "parallel_limit": args.parallel_limit, "assay_column": args.assay_column, "assay_level_count": len(assay_levels), "created_at": utc_now()},
        "execution_graph": {"nodes": [], "edges": []},
        "domain_graph": {"nodes": [], "edges": []},
        "evidence_graph": {"nodes": [], "edges": []},
        "history": [],
        "updated_at": utc_now(),
    }
    append_history(state, "initialized")
    write_state(state_path, state)
    print(state_path)
    return 0


def add_node(
    state: dict[str, Any],
    capability: dict[str, Any],
    dependencies: list[str] | None = None,
    reason: str = "",
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    existing = [node for node in state["execution_graph"]["nodes"] if node["capability_id"] == capability["capability_id"]]
    node_id = f"{capability['capability_id']}:{len(existing) + 1:03d}"
    approval = "required" if capability["cost"].get("human_approval_required") else "not_required"
    selected_parameters = dict(capability.get("default_parameters") or {})
    selected_parameters.update(parameters or {})
    node = {"node_id": node_id, "capability_id": capability["capability_id"], "skill_name": capability["skill_name"], "stage": capability["stage"], "status": "pending", "dependencies": dependencies or [], "human_approval": approval, "selection_reason": reason, "parameters": selected_parameters, "cost": capability["cost"], "artifacts": [], "warnings": []}
    state["execution_graph"]["nodes"].append(node)
    for dependency in dependencies or []:
        state["execution_graph"]["edges"].append({"source": dependency, "target": node_id, "relation": "depends_on"})
    append_history(state, "node_added", node_id=node_id, capability_id=capability["capability_id"])
    return node


def cmd_plan_wide(args: argparse.Namespace) -> int:
    state_path = Path(args.state)
    workspace = find_workspace()
    capabilities = catalog_by_id(workspace)
    with state_lock(state_path):
        state = read_json(state_path)
        existing = {node["capability_id"] for node in state["execution_graph"]["nodes"]}
        planned = []
        description_nodes = [node["node_id"] for node in state["execution_graph"]["nodes"] if node["stage"] == "description"]
        grouping_nodes = [node["node_id"] for node in state["execution_graph"]["nodes"] if node["stage"] == "grouping"]
        stage_order = {"description": 0, "grouping": 1, "analysis": 2, "interpretation": 3, "orchestration": 4}
        ordered_capabilities = sorted(
            capabilities.values(),
            key=lambda capability: (stage_order.get(capability["stage"], 99), capability["capability_id"]),
        )
        for capability in ordered_capabilities:
            assay_grouping = capability["capability_id"] == "C017" and state["run"].get("assay_level_count", 0) > 1
            if (not capability.get("default_wide_shallow") and not assay_grouping) or capability["capability_id"] in existing:
                continue
            dependencies: list[str] = []
            required = capability.get("dependencies") or []
            if "description" in required:
                dependencies = description_nodes[:1]
            elif "grouping" in required:
                dependencies = grouping_nodes[:1]
            elif "evidence" in required:
                continue
            reason = "Multiple assay conditions detected; plan assay-specific Grouping" if assay_grouping else "Catalog default_wide_shallow; broad representation-family coverage"
            node = add_node(state, capability, dependencies, reason)
            if assay_grouping:
                node["parameters"] = {"columns": state["run"]["assay_column"]}
            planned.append(node["node_id"])
            if capability["stage"] == "description":
                description_nodes.append(node["node_id"])
            elif capability["stage"] == "grouping":
                grouping_nodes.append(node["node_id"])
        append_history(state, "wide_plan_created", node_ids=planned)
        write_state(state_path, state)
    print(json.dumps({"planned_nodes": planned}, indent=2))
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    state_path = Path(args.state)
    capability = catalog_by_id(find_workspace()).get(args.capability_id)
    if capability is None:
        raise ValueError(f"Capability is not in the human-curated Catalog: {args.capability_id}")
    if capability["stage"] == "orchestration":
        raise ValueError("The Orchestrator capability coordinates the run and cannot be added as an execution node")
    parameters: dict[str, Any] = {}
    if args.parameters_json:
        parsed = json.loads(args.parameters_json)
        if not isinstance(parsed, dict):
            raise ValueError("--parameters-json must decode to a JSON object")
        parameters = parsed
    with state_lock(state_path):
        state = read_json(state_path)
        dependencies = [value.strip() for value in (args.depends_on or "").split(",") if value.strip()]
        unknown = [value for value in dependencies if value not in state_nodes(state)]
        if unknown:
            raise ValueError(f"Unknown dependency nodes: {unknown}")
        node = add_node(state, capability, dependencies, args.reason or "Human or Orchestrator selected deep-dive", parameters)
        if args.require_approval and node["human_approval"] == "not_required":
            node["human_approval"] = "required"
            append_history(state, "dynamic_approval_required", node_id=node["node_id"], reason=args.reason or "Dataset-scale or runtime-specific cost")
        write_state(state_path, state)
    print(json.dumps(node, ensure_ascii=False, indent=2))
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    state_path = Path(args.state)
    with state_lock(state_path):
        state = read_json(state_path)
        node = state_nodes(state).get(args.node_id)
        if node is None:
            raise ValueError(f"Unknown node: {args.node_id}")
        if node["human_approval"] != "required":
            raise ValueError(f"Node is not awaiting approval: {args.node_id}")
        node["human_approval"] = "approved" if args.approve else "rejected"
        if not args.approve:
            node["status"] = "skipped"
        append_history(state, "approval_recorded", node_id=args.node_id, decision=node["human_approval"], rationale=args.rationale)
        write_state(state_path, state)
    return 0


def node_readiness_error(state: dict[str, Any], node: dict[str, Any]) -> str | None:
    if node["human_approval"] in {"required", "rejected"}:
        return f"Node is not approved for execution: {node['node_id']}"
    nodes = state_nodes(state)
    incomplete = [dependency for dependency in node["dependencies"] if nodes[dependency]["status"] != "succeeded"]
    if incomplete:
        return f"Dependencies are not complete: {incomplete}"
    return None


def cmd_start(args: argparse.Namespace) -> int:
    state_path = Path(args.state)
    with state_lock(state_path):
        state = read_json(state_path)
        node = state_nodes(state).get(args.node_id)
        if node is None:
            raise ValueError(f"Unknown node: {args.node_id}")
        if node["status"] not in {"pending", "stale"}:
            raise ValueError(f"Node cannot start from status {node['status']}: {args.node_id}")
        readiness_error = node_readiness_error(state, node)
        if readiness_error:
            raise ValueError(readiness_error)
        running_count = sum(item["status"] == "running" for item in state["execution_graph"]["nodes"])
        if running_count >= int(state["run"]["parallel_limit"]):
            raise ValueError("Parallel limit has been reached")
        node["status"] = "running"
        node["started_at"] = utc_now()
        append_history(state, "node_started", node_id=args.node_id)
        write_state(state_path, state)
    return 0


def cmd_fail(args: argparse.Namespace) -> int:
    state_path = Path(args.state)
    with state_lock(state_path):
        state = read_json(state_path)
        node = state_nodes(state).get(args.node_id)
        if node is None:
            raise ValueError(f"Unknown node: {args.node_id}")
        if node["status"] != "running":
            raise ValueError(f"Only a running node can be marked failed: {args.node_id}")
        node["status"] = "failed"
        node["finished_at"] = utc_now()
        node["error"] = args.reason
        append_history(state, "node_failed", node_id=args.node_id, reason=args.reason)
        write_state(state_path, state)
    return 0


def downstream(state: dict[str, Any], source: str) -> set[str]:
    edges = state["execution_graph"]["edges"]
    found: set[str] = set()
    frontier = [source]
    while frontier:
        current = frontier.pop()
        for edge in edges:
            if edge["source"] == current and edge["target"] not in found:
                found.add(edge["target"]); frontier.append(edge["target"])
    return found


def set_derived_graph_status(state: dict[str, Any], source_node_ids: set[str], status: str) -> None:
    for graph_name in ["domain_graph", "evidence_graph"]:
        for item in state[graph_name].setdefault("nodes", []):
            if item.get("source_node_id") in source_node_ids:
                item["status"] = status


def cmd_record(args: argparse.Namespace) -> int:
    state_path = Path(args.state)
    event_path = Path(args.event).resolve()
    event = read_json(event_path)
    validate_event(event)
    with state_lock(state_path):
        state = read_json(state_path)
        if event["project"] != state["run"]["project"]:
            raise ValueError("Event project does not match State")
        if event["run_id"] != state["run"]["run_id"]:
            raise ValueError("Event run_id does not match State")
        node = state_nodes(state).get(event["node_id"])
        if node is None:
            raise ValueError(f"Event node is not planned: {event['node_id']}")
        if node["capability_id"] != event["capability_id"]:
            raise ValueError("Event capability does not match planned node")
        if node["skill_name"] != event["skill_name"]:
            raise ValueError("Event Skill does not match planned node")
        if node["status"] != "running":
            raise ValueError(f"Only a running node can record an execution event: {node['node_id']}")
        expected_parameters = node.get("parameters") or {}
        configuration = event["configuration"]
        parameter_mismatches = {
            key: {"expected": expected, "actual": configuration.get(key, "<missing>")}
            for key, expected in expected_parameters.items()
            if key not in configuration or configuration[key] != expected
        }
        if parameter_mismatches:
            raise ValueError(f"Event configuration does not match planned node parameters: {parameter_mismatches}")
        readiness_error = node_readiness_error(state, node)
        if readiness_error:
            raise ValueError(readiness_error)
        previous_input = node.get("input_hash")
        previous_config = node.get("config_hash")
        changed = (previous_input and previous_input != event["input_hash"]) or (previous_config and previous_config != event["config_hash"])
        artifacts = []
        set_derived_graph_status(state, {node["node_id"]}, "stale")
        for artifact in event.get("artifacts") or []:
            artifact = dict(artifact)
            artifact_path = (event_path.parent / str(artifact.get("path", ""))).resolve()
            if not artifact_path.is_file():
                raise FileNotFoundError(f"Event artifact was not found: {artifact_path}")
            declared_hash = artifact.get("sha256")
            if declared_hash and file_hash(artifact_path) != declared_hash:
                raise ValueError(f"Event artifact hash mismatch: {artifact_path}")
            artifact["resolved_path"] = str(artifact_path)
            artifacts.append(artifact)
            if artifact.get("type") == "group_registry" and artifact_path.exists():
                known_groups = {item.get("group_id"): item for item in state["domain_graph"].setdefault("nodes", [])}
                for group in read_json(artifact_path):
                    graph_node = {"group_id": group.get("group_id"), "group_label": group.get("group_label"), "grouping_capability_id": group.get("grouping_capability_id"), "source_node_id": node["node_id"], "status": "active"}
                    existing_group = known_groups.get(group.get("group_id"))
                    if existing_group:
                        existing_group.update(graph_node)
                    else:
                        state["domain_graph"]["nodes"].append(graph_node)
            if artifact.get("type") == "evidence" and artifact_path.exists():
                evidence = read_json(artifact_path)
                evidence_nodes = state["evidence_graph"].setdefault("nodes", [])
                graph_node = {"evidence_id": evidence.get("evidence_id"), "operator_id": evidence.get("operator_id"), "target_group_id": evidence.get("target_group_id"), "grouping_representation": evidence.get("grouping_representation"), "evaluation_representation": evidence.get("evaluation_representation"), "source_node_id": node["node_id"], "artifact_path": str(artifact_path), "status": "active"}
                existing_evidence = next((item for item in evidence_nodes if item.get("evidence_id") == evidence.get("evidence_id")), None)
                if existing_evidence:
                    existing_evidence.update(graph_node)
                else:
                    evidence_nodes.append(graph_node)
                    state["evidence_graph"].setdefault("edges", []).append({"source": node["node_id"], "target": evidence.get("evidence_id"), "relation": "produces_evidence"})
        node.update({"status": event["status"], "input_hash": event["input_hash"], "config_hash": event["config_hash"], "configuration": configuration, "artifacts": artifacts, "warnings": event.get("warnings") or [], "started_at": event.get("started_at"), "finished_at": event.get("finished_at")})
        if changed:
            downstream_ids = downstream(state, node["node_id"])
            for node_id in downstream_ids:
                target = state_nodes(state)[node_id]
                if target["status"] == "succeeded":
                    target["status"] = "stale"
            set_derived_graph_status(state, downstream_ids, "stale")
        append_history(state, "event_recorded", node_id=node["node_id"], status=node["status"], downstream_invalidated=bool(changed))
        write_state(state_path, state)
    return 0


def runnable_nodes(state: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = state_nodes(state)
    result = []
    for node in nodes.values():
        if node["status"] not in {"pending", "stale"}:
            continue
        if node["human_approval"] in {"required", "rejected"}:
            continue
        if all(nodes[dependency]["status"] == "succeeded" for dependency in node["dependencies"]):
            result.append(node)
    limit = int(state["run"]["parallel_limit"])
    running_count = sum(node["status"] == "running" for node in nodes.values())
    return result[:max(0, limit - running_count)]


def cmd_runnable(args: argparse.Namespace) -> int:
    state = read_json(Path(args.state))
    print(json.dumps(runnable_nodes(state), ensure_ascii=False, indent=2))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    state = read_json(Path(args.state))
    counts: dict[str, int] = {}
    for node in state["execution_graph"]["nodes"]:
        counts[node["status"]] = counts.get(node["status"], 0) + 1
    print(json.dumps({"run": state["run"], "status_counts": counts, "runnable": [node["node_id"] for node in runnable_nodes(state)], "updated_at": state["updated_at"]}, ensure_ascii=False, indent=2))
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    state_path = Path(args.state)
    with state_lock(state_path):
        state = read_json(state_path)
        input_path = Path(state["run"]["input"])
        current_hash = file_hash(input_path)
        changed = current_hash != state["run"].get("input_hash")
        if changed:
            state["run"]["input_hash"] = current_hash
            for node in state["execution_graph"]["nodes"]:
                if node["status"] == "succeeded":
                    node["status"] = "stale"
            set_derived_graph_status(state, {node["node_id"] for node in state["execution_graph"]["nodes"]}, "stale")
            append_history(state, "input_changed_on_resume", input_hash=current_hash)
        else:
            append_history(state, "resumed", input_hash=current_hash)
        write_state(state_path, state)
        runnable = runnable_nodes(state)
    print(json.dumps({"input_changed": changed, "runnable": runnable}, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage a CONDUCTOR v4 run State DAG.")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--input", required=True); init.add_argument("--endpoint", required=True); init.add_argument("--higher-is-better", action=argparse.BooleanOptionalAction, required=True)
    init.add_argument("--project", required=True); init.add_argument("--parallel-limit", type=int, required=True); init.add_argument("--assay-column"); init.add_argument("--run-id"); init.add_argument("--output-dir"); init.add_argument("--overwrite", action="store_true"); init.set_defaults(func=cmd_init)
    plan = sub.add_parser("plan-wide"); plan.add_argument("--state", required=True); plan.set_defaults(func=cmd_plan_wide)
    add = sub.add_parser("add"); add.add_argument("--state", required=True); add.add_argument("--capability-id", required=True); add.add_argument("--depends-on"); add.add_argument("--reason"); add.add_argument("--parameters-json", help="JSON object of Skill CLI parameter destinations, for example {\"include_chirality\":true}."); add.add_argument("--require-approval", action="store_true", help="Require human approval because run-specific scale makes this execution expensive."); add.set_defaults(func=cmd_add)
    approve = sub.add_parser("approve"); approve.add_argument("--state", required=True); approve.add_argument("--node-id", required=True); decision = approve.add_mutually_exclusive_group(required=True); decision.add_argument("--approve", action="store_true"); decision.add_argument("--reject", dest="approve", action="store_false"); approve.add_argument("--rationale", required=True); approve.set_defaults(func=cmd_approve)
    start = sub.add_parser("start"); start.add_argument("--state", required=True); start.add_argument("--node-id", required=True); start.set_defaults(func=cmd_start)
    fail = sub.add_parser("fail"); fail.add_argument("--state", required=True); fail.add_argument("--node-id", required=True); fail.add_argument("--reason", required=True); fail.set_defaults(func=cmd_fail)
    record = sub.add_parser("record"); record.add_argument("--state", required=True); record.add_argument("--event", required=True); record.set_defaults(func=cmd_record)
    runnable = sub.add_parser("runnable"); runnable.add_argument("--state", required=True); runnable.set_defaults(func=cmd_runnable)
    status = sub.add_parser("status"); status.add_argument("--state", required=True); status.set_defaults(func=cmd_status)
    resume = sub.add_parser("resume"); resume.add_argument("--state", required=True); resume.set_defaults(func=cmd_resume)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if getattr(args, "parallel_limit", 1) < 1:
        raise ValueError("--parallel-limit must be >= 1")
    return args.func(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
