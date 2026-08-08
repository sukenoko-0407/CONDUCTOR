from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def dag_error(state: dict[str, Any]) -> str | None:
    nodes = {node["node_id"] for node in state.get("execution_graph", {}).get("nodes", [])}
    adjacency = {node_id: [] for node_id in nodes}
    indegree = {node_id: 0 for node_id in nodes}
    for edge in state.get("execution_graph", {}).get("edges", []):
        source, target = edge.get("source"), edge.get("target")
        if source not in nodes or target not in nodes:
            return f"unknown edge endpoint: {source}->{target}"
        adjacency[source].append(target)
        indegree[target] += 1
    queue = deque(node_id for node_id, degree in indegree.items() if degree == 0)
    visited = 0
    while queue:
        source = queue.popleft(); visited += 1
        for target in adjacency[source]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    return None if visited == len(nodes) else "cycle detected"


def audit(state_path: Path, mode: str) -> dict[str, Any]:
    state = read_json(state_path)
    checks: list[dict[str, Any]] = []

    def add(code: str, passed: bool, detail: Any = None, severity: str = "error") -> None:
        checks.append({"code": code, "passed": bool(passed), "severity": severity, "detail": detail})

    add("STATE_VERSION", state.get("conductor_version") == "4.3.1" and state.get("schema_version") == "2.1.0", {"conductor": state.get("conductor_version"), "schema": state.get("schema_version")})
    error = dag_error(state); add("DAG_ACYCLIC", error is None, error)
    nodes = state.get("execution_graph", {}).get("nodes", [])
    ids = [node.get("node_id") for node in nodes]
    add("NODE_IDS_UNIQUE", len(ids) == len(set(ids)), {"count": len(ids), "unique": len(set(ids))})
    active_signatures = [node.get("analysis_signature") for node in nodes if node.get("status") != "stale"]
    add("ACTIVE_SIGNATURES_UNIQUE", len(active_signatures) == len(set(active_signatures)), {"count": len(active_signatures), "unique": len(set(active_signatures))})
    edges = {(edge.get("source"), edge.get("target")) for edge in state.get("execution_graph", {}).get("edges", [])}
    dependency_mismatches = [node.get("node_id") for node in nodes if any((dep, node.get("node_id")) not in edges for dep in node.get("dependencies", []))]
    add("DEPENDENCIES_MATCH_EDGES", not dependency_mismatches, dependency_mismatches)
    running = [node for node in nodes if node.get("status") == "running"]
    limit = int(state.get("run", {}).get("parallel_limit") or 0)
    add("PARALLEL_LIMIT", len(running) <= limit, {"running": len(running), "limit": limit})
    add("RUNNING_HAS_ATTEMPT", all(node.get("current_attempt_id") for node in running), [node.get("node_id") for node in running if not node.get("current_attempt_id")])
    active_round = state.get("round_control", {}).get("active_round_id")
    rounds = state.get("round_control", {}).get("rounds", [])
    active_records = [item.get("round_id") for item in rounds if item.get("status") == "active"]
    add("SINGLE_ACTIVE_ROUND", len(active_records) <= 1 and (not active_records or active_records[0] == active_round), {"pointer": active_round, "active": active_records})
    handoff = state.get("orchestration_control", {}).get("migration_handoff") or {}
    if handoff.get("status") == "awaiting_human_start":
        post_migration_nodes = [node.get("node_id") for node in nodes if node.get("round_id") != "RND0001"]
        add("MIGRATION_HANDOFF_SAFE", active_round is None and not post_migration_nodes, {"active_round_id": active_round, "post_migration_nodes": post_migration_nodes})
    max_by_prefix = {"description_node": ("ND", 0), "grouping_node": ("NG", 0), "operator_node": ("NO", 0), "interpretation_node": ("NI", 0)}
    for key, (prefix, _value) in list(max_by_prefix.items()):
        maximum = max((int(match.group(1)) for node_id in ids if (match := re.fullmatch(prefix + r"(\d+)", str(node_id)))), default=0)
        max_by_prefix[key] = (prefix, maximum)
    stale_counters = {key: {"counter": state.get("id_counters", {}).get(key), "minimum": maximum} for key, (_prefix, maximum) in max_by_prefix.items() if int(state.get("id_counters", {}).get(key) or 0) < maximum}
    add("NODE_COUNTERS_COVER_IDS", not stale_counters, stale_counters)
    successful_analysis = [node for node in nodes if node.get("round_id") == active_round and node.get("stage") == "analysis" and node.get("status") == "succeeded"]
    successful_interpretation = [node for node in nodes if node.get("round_id") == active_round and node.get("stage") == "interpretation" and node.get("status") == "succeeded"]
    latest_analysis_at = max(
        (value for value in (parse_time(node.get("finished_at") or node.get("started_at") or node.get("requested_at")) for node in successful_analysis) if value is not None),
        default=None,
    )
    valid_interpretation = []
    stale_interpretation = []
    for node in successful_interpretation:
        root = Path(node["output_dir"])
        if all((root / name).is_file() for name in ["interpretation.json", "interpretation.md", "interpretation.html"]):
            completed_at = parse_time(node.get("finished_at") or node.get("started_at") or node.get("requested_at"))
            if latest_analysis_at is not None and (completed_at is None or completed_at < latest_analysis_at):
                stale_interpretation.append(node["node_id"])
            else:
                valid_interpretation.append(node["node_id"])
    add("INTERPRETATION_CLOSE_GATE", not successful_analysis or bool(valid_interpretation), {"analysis": [node["node_id"] for node in successful_analysis], "valid_interpretation": valid_interpretation, "stale_interpretation": stale_interpretation}, "warning")
    if mode == "full":
        missing: list[dict[str, str]] = []; mismatch: list[dict[str, str]] = []
        for node in nodes:
            if node.get("status") != "succeeded":
                continue
            for artifact in node.get("artifacts") or []:
                raw = artifact.get("resolved_path")
                if not raw:
                    continue
                path = Path(raw)
                if not path.is_file():
                    missing.append({"node_id": node["node_id"], "path": str(path)})
                elif artifact.get("sha256") and sha256(path) != artifact["sha256"]:
                    mismatch.append({"node_id": node["node_id"], "path": str(path)})
        add("SUCCEEDED_ARTIFACTS_EXIST", not missing, missing)
        add("SUCCEEDED_ARTIFACT_HASHES", not mismatch, mismatch)
        index_paths = []
        for index_name, value in state.get("indices", {}).items():
            if isinstance(value, dict):
                if index_name == "group" and int(value.get("group_count") or 0) == 0:
                    continue
                index_paths.extend(Path(raw) for key, raw in value.items() if key.endswith("path") and isinstance(raw, str))
        absent_indices = [str(path) for path in index_paths if not path.is_file()]
        add("REFERENCED_INDICES_EXIST", not absent_indices, absent_indices)
        for name in ["state_summary.json", "orchestrator_brief.json"]:
            path = state_path.parent / "summaries" / name
            try:
                read_json(path); valid = True; detail = None
            except Exception as exc:
                valid = False; detail = str(exc)
            add(f"{name.upper().replace('.', '_')}_VALID", valid, detail)
    errors = [item for item in checks if not item["passed"] and item["severity"] == "error"]
    warnings = [item for item in checks if not item["passed"] and item["severity"] == "warning"]
    return {"schema_version": "1.0.0", "mode": mode, "run_id": state.get("run", {}).get("run_id"), "state_path": str(state_path), "status": "fail" if errors else ("warning" if warnings else "pass"), "error_count": len(errors), "warning_count": len(warnings), "checks": checks, "created_at": now()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only CONDUCTOR Run audit")
    parser.add_argument("--state", required=True)
    parser.add_argument("--mode", choices=["quick", "full"], default="quick")
    args = parser.parse_args()
    state_path = Path(args.state).expanduser().resolve()
    if not state_path.is_file():
        raise FileNotFoundError(state_path)
    result = audit(state_path, args.mode)
    output = state_path.parent / "audit" / stamp()
    output.mkdir(parents=True, exist_ok=False)
    atomic_write(output / "audit.json", json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    lines = [f"# CONDUCTOR {args.mode.title()} Audit", "", f"- Status: {result['status']}", f"- Run: {result['run_id']}", "", "## Checks", ""]
    for item in result["checks"]:
        label = "PASS" if item["passed"] else item["severity"].upper()
        lines.append(f"- [{label}] `{item['code']}` — {json.dumps(item.get('detail'), ensure_ascii=False)}")
    atomic_write(output / "audit.md", "\n".join(lines) + "\n")
    print(json.dumps({"output_dir": str(output), **result}, ensure_ascii=False, indent=2))
    return 1 if result["status"] == "fail" else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=__import__("sys").stderr)
        raise SystemExit(2)
