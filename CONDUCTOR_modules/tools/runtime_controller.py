from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable


VERSION = "0.1.9"
PROTOCOL_VERSION = "0.1.9"
NODE_STATES = {"pending", "running", "succeeded", "failed", "cancelled"}
DEFAULT_CPU_CORES = 8
DEFAULT_LEASE_MINUTES = 360
HIGH_COST = {"D016", "D019", "D020"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def process_alive(pid: int) -> bool:
    """Return whether a local process still exists without sending a signal."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            return exit_code.value == 259
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def project_root() -> Path:
    here = Path(__file__).resolve()
    for path in [here.parent, *here.parents, Path.cwd(), *Path.cwd().parents]:
        if (path / ".claude" / "skills").is_dir() and (path / "CONDUCTOR_modules").is_dir():
            return path
    raise FileNotFoundError("CONDUCTOR project root was not found")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def value_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def resolve_root(value: str | Path) -> Path:
    root = Path(value).resolve()
    if not (root / "conductor_control.json").is_file():
        raise FileNotFoundError(f"CONDUCTOR Run root is invalid: {root}")
    return root


def control_path(root: Path) -> Path:
    return root / "conductor_control.json"


def dag_path(root: Path) -> Path:
    return root / "runtime" / "dag.json"


def state_transaction_path(root: Path) -> Path:
    return root / "runtime" / "state_transaction.json"


@contextmanager
def writer_lock(root: Path, timeout: float = 30.0):
    lock = root / "runtime" / ".writer.lock"
    started = time.monotonic()
    lock_token = uuid.uuid4().hex
    def recover_stale_lock() -> bool:
        try:
            owner = read_json(lock / "owner.json")
            created = parse_time(str(owner.get("created_at", "")))
            same_host = owner.get("host") == socket.gethostname()
            owner_alive = same_host and process_alive(int(owner.get("pid", -1)))
            # A live local owner always wins.  Age-only eviction of a live lock
            # can create concurrent state writers during a long HPC operation.
            stale = (same_host and not owner_alive) or bool(
                not same_host
                and created
                and datetime.now(timezone.utc) - created > timedelta(hours=8)
            )
        except Exception:
            # Runtime state writes are short transactions.  Missing/corrupt
            # ownership metadata must not block a Run for an entire HPC lease.
            try:
                stale = time.time() - lock.stat().st_mtime > 5 * 60
            except OSError:
                return False
        if stale:
            shutil.rmtree(lock, ignore_errors=True)
        return stale
    while True:
        try:
            lock.mkdir(parents=False)
            atomic_json(lock / "owner.json", {
                "pid": os.getpid(), "host": socket.gethostname(),
                "created_at": now(), "lock_token": lock_token,
            })
            break
        except FileExistsError:
            if recover_stale_lock():
                continue
            if time.monotonic() - started > timeout:
                raise TimeoutError(f"Runtime writer lock is busy: {lock}")
            time.sleep(0.1)
    try:
        yield
    finally:
        # Never remove a replacement writer's lock if ownership changed while
        # this process was unwinding from an exception.
        try:
            owner = read_json(lock / "owner.json")
            if owner.get("lock_token") == lock_token:
                shutil.rmtree(lock, ignore_errors=True)
        except Exception:
            pass


def load_state(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    transaction = state_transaction_path(root)
    if transaction.is_file():
        pending = read_json(transaction)
        control = pending.get("control")
        dag = pending.get("dag")
        if not isinstance(control, dict) or not isinstance(dag, dict):
            raise RuntimeError(f"Runtime state transaction is invalid: {transaction}")
    else:
        control, dag = read_json(control_path(root)), read_json(dag_path(root))
    if control.get("revision") != dag.get("revision"):
        raise RuntimeError(
            f"Runtime state revision mismatch: control={control.get('revision')}, dag={dag.get('revision')}"
        )
    return control, dag


def save_state(root: Path, control: dict[str, Any], dag: dict[str, Any], event: str, payload: dict[str, Any] | None = None) -> None:
    dag["revision"] = int(dag.get("revision", 0)) + 1
    control["revision"] = dag["revision"]
    control["updated_at"] = now()
    # control and DAG are one logical state.  The transaction record is written
    # first so a process death between the two atomic file replacements cannot
    # expose an old Node counter beside a newer DAG (or vice versa).  load_state
    # treats a surviving record as the authoritative complete pair.
    transaction = state_transaction_path(root)
    atomic_json(transaction, {"schema_version": "1.0.0", "control": control, "dag": dag})
    atomic_json(control_path(root), control)
    atomic_json(dag_path(root), dag)
    transaction.unlink(missing_ok=True)
    append_jsonl(root / "runtime" / "events.jsonl", {
        "revision": dag["revision"], "timestamp": now(), "event": event, "round_id": control.get("active_round_id"), "payload": payload or {}
    })


@lru_cache(maxsize=1)
def included_skill_names() -> tuple[str, ...]:
    selection_path = project_root() / "CONDUCTOR_modules" / "catalog" / "included_skills.json"
    selection = read_json(selection_path)
    names: list[str] = []
    for key in ("description_skills", "clustering_skills", "analysis_skills", "interpretation_skills", "support_skills"):
        values = selection.get(key)
        if not isinstance(values, list):
            raise ValueError(f"included_skills.json field {key!r} must be an array")
        names.extend(str(value) for value in values)
    if len(names) != len(set(names)):
        raise ValueError("included_skills.json contains duplicate Skill names")
    return tuple(names)


@lru_cache(maxsize=1)
def capabilities() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    skill_root = project_root() / ".claude" / "skills"
    for skill_name in included_skill_names():
        path = skill_root / skill_name / "capability.json"
        if not path.is_file():
            raise FileNotFoundError(f"Selected Skill is missing capability.json: {path}")
        value = read_json(path)
        capability_id = str(value.get("capability_id", ""))
        if not capability_id:
            raise ValueError(f"Selected Skill has no capability_id: {path}")
        if value.get("skill_name") != skill_name:
            raise ValueError(f"Selected Skill name mismatch: directory={skill_name}, capability={value.get('skill_name')!r}")
        if value.get("version") != VERSION:
            raise ValueError(f"Selected Skill {skill_name} has version={value.get('version')!r}; expected {VERSION}")
        if capability_id in result:
            raise ValueError(f"Duplicate capability_id: {capability_id}")
        value["_skill_dir"] = str(path.parent.resolve())
        result[capability_id] = value
    return result


@lru_cache(maxsize=1)
def profile() -> dict[str, Any]:
    return read_json(project_root() / "CONDUCTOR_modules" / "catalog" / "analysis_profile.json")


def safe_path_component(value: str, option: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{option} must not be blank")
    if text in {".", ".."} or "/" in text or "\\" in text or "\x00" in text:
        raise ValueError(f"{option} must be one path component without path separators and must not be '.' or '..': {value!r}")
    return text


def infer_column(columns: list[str], candidates: list[str]) -> str | None:
    normalized = {"".join(ch for ch in str(column).lower() if ch.isalnum()): str(column) for column in columns}
    for candidate in candidates:
        key = "".join(ch for ch in candidate.lower() if ch.isalnum())
        if key in normalized:
            return normalized[key]
    return None


def nodes(dag: dict[str, Any]) -> list[dict[str, Any]]:
    return dag.setdefault("nodes", [])


def lookup(dag: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(node["node_id"]): node for node in nodes(dag)}


def by_capability(dag: dict[str, Any], capability_id: str, *, status: str | None = None) -> list[dict[str, Any]]:
    return [node for node in nodes(dag) if node["capability_id"] == capability_id and (status is None or node["status"] == status)]


def latest(dag: dict[str, Any], capability_id: str, *, status: str | None = None, round_id: str | None = None) -> dict[str, Any] | None:
    values = [
        node for node in by_capability(dag, capability_id, status=status)
        if round_id is None or node.get("round_id") == round_id
    ]
    return sorted(values, key=lambda item: item["node_id"])[-1] if values else None


def next_id(control: dict[str, Any], key: str, prefix: str, width: int) -> str:
    number = int(control[key])
    control[key] = number + 1
    return f"{prefix}{number:0{width}d}"


def node_signature(capability_id: str, dependencies: list[str], parameters: dict[str, Any], round_id: str) -> str:
    return value_hash({"capability_id": capability_id, "dependencies": dependencies, "parameters": parameters, "round_id": round_id})


def add_node(control: dict[str, Any], dag: dict[str, Any], capability_id: str, dependencies: list[str], wave: str, parameters: dict[str, Any] | None = None) -> tuple[dict[str, Any], bool]:
    caps = capabilities()
    if capability_id not in caps:
        raise ValueError(f"Capability is not installed: {capability_id}")
    if control.get("round_status") != "ACTIVE" or not control.get("active_round_id"):
        raise ValueError("Scientific Nodes can be added only to the current ACTIVE Round")
    if wave not in {"basic", "standard", "interpretation"}:
        raise ValueError(f"Unsupported Node wave: {wave}")
    if len(dependencies) != len(set(dependencies)):
        raise ValueError(f"Node dependencies must be unique: {dependencies}")
    round_id = str(control["active_round_id"])
    table = lookup(dag)
    missing_dependencies = sorted(set(dependencies) - set(table))
    if missing_dependencies:
        raise ValueError(f"Node dependencies do not exist: {missing_dependencies}")
    foreign_dependencies = [
        node_id for node_id in dependencies
        if str(table[node_id].get("round_id")) != round_id
    ]
    if foreign_dependencies:
        raise ValueError(f"Cross-Round dependencies are not allowed in 0.1.9: {foreign_dependencies}")
    cap = caps[capability_id]
    # Store the complete effective parameter contract in the Node.  Runtime
    # overrides remain explicit, while untouched values come from the selected
    # capability metadata instead of being hidden inside a scientific kernel.
    effective_parameters = dict(cap.get("default_parameters") or {})
    effective_parameters.update(parameters or {})
    parameters = effective_parameters
    signature = node_signature(capability_id, dependencies, parameters, round_id)
    for existing in nodes(dag):
        if existing.get("signature") == signature:
            return existing, False
    node = {
        "node_id": next_id(control, "next_node_number", "N", 6),
        "capability_id": capability_id,
        "skill_name": cap["skill_name"],
        "stage": cap["stage"],
        "wave": wave,
        "round_id": round_id,
        "dependencies": dependencies,
        "parameters": parameters,
        "signature": signature,
        "status": "pending",
        "attempts": [],
        "result": None,
        "error": None,
        "waived": False,
        "created_at": now(),
        "updated_at": now(),
    }
    nodes(dag).append(node)
    return node, True


def dependency_satisfied(node: dict[str, Any], table: dict[str, dict[str, Any]]) -> bool:
    for node_id in node.get("dependencies", []):
        parent = table.get(node_id)
        if not parent or parent["status"] not in {"succeeded", "cancelled"}:
            return False
        if parent["status"] == "cancelled" and not parent.get("waived"):
            return False
    return True


def runnable(dag: dict[str, Any], round_id: str | None = None) -> list[dict[str, Any]]:
    table = lookup(dag)
    return [
        node for node in nodes(dag)
        if node["status"] == "pending"
        and (round_id is None or node.get("round_id") == round_id)
        and dependency_satisfied(node, table)
    ]


def live_lease(control: dict[str, Any]) -> bool:
    lease = control.get("lease") or {}
    expires = parse_time(lease.get("expires_at"))
    return bool(lease.get("token") and expires and expires > datetime.now(timezone.utc))


def require_lease(control: dict[str, Any], token: str | None) -> None:
    if not live_lease(control) or token != (control.get("lease") or {}).get("token"):
        raise PermissionError("A live Runtime lease token is required; run resume-round first")


def walltime_expired(control: dict[str, Any]) -> bool:
    deadline = parse_time(control.get("round_deadline"))
    return bool(deadline and deadline <= datetime.now(timezone.utc))


def primary_path(node: dict[str, Any]) -> Path:
    result = node.get("result") or {}
    value = result.get("primary_path")
    if not value:
        raise FileNotFoundError(f"Node has no primary artifact: {node['node_id']}")
    return Path(value)


def series_gate(root: Path, control: dict[str, Any], dag: dict[str, Any]) -> dict[str, Any] | None:
    c012 = latest(dag, "C012", status="succeeded", round_id=control.get("active_round_id"))
    if not c012:
        return None
    summary_path = Path((c012.get("result") or {}).get("result_dir", "")) / "series_summary.json"
    if not summary_path.is_file():
        return None
    summary = read_json(summary_path)
    # The confirmed 0.1.9 contract gates accepted Series only.  Fallback
    # Clusters remain visible as analysis units, but do not introduce an
    # additional approval gate (including the zero-Series fallback case).
    count = int(summary.get("accepted_series_count", summary.get("series_count", 0)))
    analysis_unit_count = int(summary.get("analysis_unit_count", count))
    limit = int(profile()["basic_compute"]["max_series_for_auto_standard"])
    if count > limit and control.get("series_gate_revision") != c012["node_id"]:
        return {
            "accepted_series_count": count,
            "analysis_unit_count": analysis_unit_count,
            "limit": limit,
            "c012_node_id": c012["node_id"],
        }
    return None


def required_action(root: Path, control: dict[str, Any], dag: dict[str, Any]) -> dict[str, Any]:
    status = control.get("round_status")
    if status in {None, "NONE", "CLOSED"}:
        return {"code": "AWAIT_HUMAN_ROUND"}
    if status == "PREPARED":
        return {"code": "AUTHORIZE_ROUND", "request_file": control.get("pending_round_request")}
    if status == "AWAITING_HUMAN_REVIEW":
        return {"code": "AWAIT_HUMAN_REVIEW", "round_id": control.get("active_round_id")}
    if status == "PAUSED":
        return {"code": "ROUND_PAUSED", "round_id": control.get("active_round_id")}
    failed = [node for node in nodes(dag) if node["round_id"] == control.get("active_round_id") and node["status"] == "failed" and not node.get("waived")]
    running = [node for node in nodes(dag) if node["round_id"] == control.get("active_round_id") and node["status"] == "running"]
    if running:
        return {"code": "WAIT_RUNNING", "node_ids": [node["node_id"] for node in running]}
    if walltime_expired(control):
        return {"code": "PAUSE_ROUND", "round_id": control.get("active_round_id")}
    basic = [node for node in nodes(dag) if node["round_id"] == control.get("active_round_id") and node["wave"] == "basic"]
    if not basic:
        return {"code": "PLAN_BASIC"}
    if not control.get("high_cost_approved") and any(node["capability_id"] in HIGH_COST and node["status"] == "pending" for node in basic):
        return {"code": "HUMAN_APPROVAL_REQUIRED", "bundle": sorted(HIGH_COST)}
    ready = runnable(dag, control.get("active_round_id"))
    if ready:
        return {"code": "EXECUTE_RUNNABLE_BATCH", "runnable_count": len(ready), "node_ids": [node["node_id"] for node in ready[:20]]}
    if failed:
        node = failed[0]
        return {"code": "FAILED_NODE_REPAIR_REQUIRED", "node_id": node["node_id"], "capability_id": node["capability_id"], "diagnostic": node.get("error"), "remaining_failed_count": len(failed)}
    if any(node["status"] not in {"succeeded", "cancelled"} for node in basic):
        return {"code": "BLOCKED_BASIC", "message": "Basic nodes are incomplete but none are runnable"}
    gate = series_gate(root, control, dag)
    if gate:
        return {"code": "HUMAN_SERIES_REVIEW_REQUIRED", **gate}
    standard = [node for node in nodes(dag) if node["round_id"] == control.get("active_round_id") and node["wave"] == "standard"]
    if not standard:
        return {"code": "PLAN_STANDARD"}
    if any(node["status"] not in {"succeeded", "cancelled"} for node in standard):
        return {"code": "BLOCKED_STANDARD", "message": "Standard nodes are incomplete but none are runnable"}
    interpretation = [node for node in nodes(dag) if node["round_id"] == control.get("active_round_id") and node["wave"] == "interpretation"]
    if not interpretation:
        return {"code": "PREPARE_INTERPRETATION"}
    interpretation_node = interpretation[-1]
    if interpretation_node["status"] == "pending":
        return {"code": "WRITE_INTERPRETATION", "node_id": interpretation_node["node_id"], "context_path": interpretation_node["parameters"]["context_path"], "draft_path": interpretation_node["parameters"]["draft_path"]}
    if interpretation_node["status"] != "succeeded":
        return {"code": "INTERPRETATION_BLOCKED", "node_id": interpretation_node["node_id"]}
    if control.get("audited_round_id") != control.get("active_round_id"):
        return {"code": "RUN_FULL_AUDIT"}
    return {"code": "COMPLETE_FINALIZING"}


def response(root: Path, control: dict[str, Any], dag: dict[str, Any], **extra: Any) -> dict[str, Any]:
    counts = {state: 0 for state in NODE_STATES}
    for node in nodes(dag):
        counts[node["status"]] += 1
    value = {
        "protocol_version": PROTOCOL_VERSION,
        "run_root": str(root),
        "run_id": control["run_id"],
        "round_id": control.get("active_round_id"),
        "round_status": control.get("round_status"),
        "revision": control.get("revision", 0),
        "node_counts": counts,
        "required_action": required_action(root, control, dag),
    }
    value.update(extra)
    return value


def emit(root: Path, control: dict[str, Any], dag: dict[str, Any], **extra: Any) -> int:
    print(json.dumps(response(root, control, dag, **extra), ensure_ascii=False, indent=2))
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    if args.parallel_limit < 1:
        raise ValueError("--parallel-limit must be at least 1")
    if args.available_cpu_cores < 1:
        raise ValueError("--available-cpu-cores must be at least 1")
    if args.parallel_limit > args.available_cpu_cores:
        raise ValueError("--parallel-limit must not exceed --available-cpu-cores")
    input_path = Path(args.input).resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"Input CSV does not exist: {input_path}")
    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        columns = next(csv.reader(handle))
    if args.endpoint not in columns:
        raise ValueError(f"Endpoint column was not found: {args.endpoint}. Available columns: {columns}")
    id_column = args.id_column or infer_column(columns, ["compound_id", "compoundid", "molecule_id", "id", "chembl_id"])
    smiles_column = args.smiles_column or infer_column(columns, ["smiles", "canonical_smiles", "isomeric_smiles", "structure"])
    if not id_column:
        raise ValueError("Compound ID column could not be inferred; specify --id-column")
    if not smiles_column:
        raise ValueError("SMILES column could not be inferred; specify --smiles-column")
    if len(columns) != len(set(columns)):
        raise ValueError(f"Input CSV contains duplicate column names: {columns}")
    missing_configured = [column for column in (id_column, smiles_column) if column not in columns]
    if missing_configured:
        raise ValueError(f"Configured input columns were not found: {missing_configured}. Available columns: {columns}")
    if len({id_column, smiles_column, args.endpoint}) != 3:
        raise ValueError(
            "Compound ID, SMILES, and Endpoint must be three distinct CSV columns: "
            f"id={id_column!r}, smiles={smiles_column!r}, endpoint={args.endpoint!r}"
        )
    seen_ids: set[str] = set()
    row_count = 0
    endpoint_valid_count = 0
    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for line_number, row in enumerate(reader, 2):
            row_count += 1
            raw_compound_id = str(row.get(id_column) or "")
            compound_id = raw_compound_id.strip()
            if not compound_id:
                raise ValueError(f"Compound ID is blank at CSV line {line_number}: column={id_column}")
            if raw_compound_id != compound_id:
                raise ValueError(
                    f"Compound ID has leading or trailing whitespace at CSV line {line_number}: "
                    f"{raw_compound_id!r}. Normalize IDs before starting CONDUCTOR."
                )
            if compound_id in seen_ids:
                raise ValueError(f"Duplicate compound ID at CSV line {line_number}: {compound_id}")
            seen_ids.add(compound_id)
            raw_endpoint = str(row.get(args.endpoint) or "").strip()
            if raw_endpoint:
                try:
                    numeric_endpoint = float(raw_endpoint)
                except ValueError:
                    numeric_endpoint = math.nan
                if math.isfinite(numeric_endpoint):
                    endpoint_valid_count += 1
    if row_count == 0:
        raise ValueError("Input CSV contains no compound rows")
    if endpoint_valid_count == 0:
        raise ValueError(f"Endpoint column has no finite numeric values: {args.endpoint}")
    project = safe_path_component(args.project, "--project")
    run_id = safe_path_component(args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"), "--run-id")
    root = Path(args.output_dir).resolve() if args.output_dir else (project_root() / "results" / "CONDUCTOR" / project / run_id).resolve()
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"Run root is not empty: {root}")
    (root / "runtime").mkdir(parents=True, exist_ok=True)
    for directory in ("description", "clustering", "analysis", "interpretation", "on_demand", "state"):
        (root / directory).mkdir(exist_ok=True)
    control_key = secrets.token_urlsafe(32)
    authority_path = root / "runtime" / "control_authority.key"
    authority_path.write_text(control_key + "\n", encoding="utf-8")
    if os.name != "nt":
        authority_path.chmod(0o600)
    control = {
        "schema_version": "1.0.0", "protocol_version": PROTOCOL_VERSION, "conductor_version": VERSION,
        "project": project, "run_id": run_id, "run_root": str(root), "input_path": str(input_path), "input_sha256": sha256(input_path),
        "input_compound_count": row_count, "endpoint_valid_count": endpoint_valid_count,
        "columns": {"compound_id": id_column, "smiles": smiles_column, "endpoint": args.endpoint},
        "higher_is_better": bool(args.higher_is_better), "endpoint_unit": args.endpoint_unit,
        "parallel_limit": args.parallel_limit, "available_cpu_cores": args.available_cpu_cores,
        "round_status": "NONE", "active_round_id": None, "next_round_number": 1, "next_node_number": 1,
        "revision": 0, "lease": None, "high_cost_approved": False, "series_gate_revision": None,
        "audited_round_id": None, "created_at": now(), "updated_at": now(),
    }
    dag = {"schema_version": "1.0.0", "conductor_version": VERSION, "revision": 0, "nodes": []}
    atomic_json(control_path(root), control)
    atomic_json(dag_path(root), dag)
    append_jsonl(root / "runtime" / "events.jsonl", {"revision": 0, "timestamp": now(), "event": "RUN_INITIALIZED", "payload": {"input": str(input_path)}})
    return emit(root, control, dag, control_key_path=str(root / "runtime" / "control_authority.key"))


def require_control_key(root: Path, value: str) -> None:
    expected = (root / "runtime" / "control_authority.key").read_text(encoding="utf-8").strip()
    if not secrets.compare_digest(expected, value):
        raise PermissionError("Invalid control authority key")


def cmd_prepare_round(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    if args.walltime_minutes < 1:
        raise ValueError("--walltime-minutes must be at least 1")
    if args.parallel_limit is not None and args.parallel_limit < 1:
        raise ValueError("--parallel-limit must be at least 1")
    if args.available_cpu_cores is not None and args.available_cpu_cores < 1:
        raise ValueError("--available-cpu-cores must be at least 1")
    if args.min_ff_evaluate < 5:
        raise ValueError("--min-ff-evaluate must be at least 5 (Cluster registration minimum)")
    if args.leiden_resolution <= 0:
        raise ValueError("--leiden-resolution must be greater than 0")
    with writer_lock(root):
        control, dag = load_state(root)
        if control["round_status"] not in {"NONE", "CLOSED"}:
            raise ValueError(f"Cannot prepare a new Round while status={control['round_status']}")
        effective_parallel = int(args.parallel_limit or control["parallel_limit"])
        effective_cpu_cores = int(args.available_cpu_cores or control["available_cpu_cores"])
        if effective_parallel > effective_cpu_cores:
            raise ValueError("Round parallel_limit must not exceed available_cpu_cores")
        round_id = next_id(control, "next_round_number", "RND", 4)
        token = secrets.token_urlsafe(24)
        request = {
            "schema_version": "1.0.0", "round_id": round_id, "objective": args.objective,
            "walltime_minutes": args.walltime_minutes, "parallel_limit": effective_parallel,
            "available_cpu_cores": effective_cpu_cores,
            "min_ff_evaluate": args.min_ff_evaluate, "leiden_resolution": args.leiden_resolution,
            "approve_high_cost": bool(args.approve_high_cost), "authorization_token": token, "created_at": now(),
        }
        path = root / "runtime" / "rounds" / round_id / "request.json"
        atomic_json(path, request)
        control.update({"round_status": "PREPARED", "active_round_id": round_id, "pending_round_request": str(path), "lease": None})
        save_state(root, control, dag, "ROUND_PREPARED", {"round_id": round_id})
    return emit(root, control, dag, authorization_token=token, request_file=str(path))


def cmd_authorize_round(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    require_control_key(root, args.control_key)
    with writer_lock(root):
        control, dag = load_state(root)
        if control["round_status"] != "PREPARED":
            raise ValueError("No PREPARED Round exists")
        request = read_json(Path(control["pending_round_request"]))
        if not secrets.compare_digest(str(request["authorization_token"]), args.authorization_token):
            raise PermissionError("Invalid Round authorization token")
        control.update({
            "round_status": "ACTIVE", "round_deadline": (datetime.now(timezone.utc) + timedelta(minutes=int(request["walltime_minutes"]))).isoformat(),
            "parallel_limit": int(request["parallel_limit"]), "available_cpu_cores": int(request["available_cpu_cores"]),
            "high_cost_approved": bool(request["approve_high_cost"]), "current_parameters": {
                "min_ff_evaluate": int(request["min_ff_evaluate"]), "leiden_resolution": float(request["leiden_resolution"])
            }, "pending_round_request": None, "audited_round_id": None,
        })
        save_state(root, control, dag, "ROUND_AUTHORIZED", {"round_id": control["active_round_id"]})
    return emit(root, control, dag)


def cmd_resume_round(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    if args.lease_minutes < 1:
        raise ValueError("--lease-minutes must be at least 1")
    require_control_key(root, args.control_key)
    with writer_lock(root):
        control, dag = load_state(root)
        if control["round_status"] != "ACTIVE":
            if control["round_status"] == "PAUSED":
                raise ValueError("PAUSED Round requires continue-round with additional Wall Time before resume-round")
            raise ValueError(f"Round cannot be resumed from {control['round_status']}")
        if live_lease(control):
            raise RuntimeError("A live Orchestrator lease already exists; do not start another Orchestrator")
        running_nodes = [
            node for node in nodes(dag)
            if node.get("round_id") == control.get("active_round_id") and node.get("status") == "running"
        ]
        active_local: list[str] = []
        uncertain: list[str] = []
        for node in running_nodes:
            attempt = node.get("attempts", [])[-1] if node.get("attempts") else {}
            host = str(attempt.get("runtime_host", ""))
            pid = int(attempt.get("runtime_pid", -1))
            if host == socket.gethostname() and process_alive(pid):
                active_local.append(node["node_id"])
            elif not host or host != socket.gethostname():
                uncertain.append(node["node_id"])
        if active_local:
            raise RuntimeError(
                "Cannot acquire a replacement lease while local Runtime processes are still executing Nodes: "
                + ", ".join(active_local)
            )
        if uncertain and not bool(getattr(args, "confirm_interrupted_running", False)):
            raise RuntimeError(
                "Running Nodes belong to an unknown or different host. Confirm that the prior Runtime is no longer "
                "active, then repeat resume-round with --confirm-interrupted-running: " + ", ".join(uncertain)
            )
        interrupted = []
        for node in running_nodes:
            node["status"] = "failed"; node["updated_at"] = now()
            node["error"] = {"code":"INTERRUPTED_ATTEMPT","message":"The prior Runtime process ended without committing this running Node.","remediation":"Confirm no prior process is still active, then retry the same Node ID."}
            if node.get("attempts") and node["attempts"][-1].get("status") == "running":
                node["attempts"][-1].update({"status":"failed","finished_at":now(),"message":"Interrupted before terminal commit"})
            interrupted.append(node["node_id"])
        token = secrets.token_urlsafe(32)
        control["lease"] = {"token": token, "owner_id": args.owner_id, "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=args.lease_minutes)).isoformat()}
        save_state(root, control, dag, "LEASE_ACQUIRED", {"owner_id": args.owner_id, "interrupted_node_ids": interrupted})
    return emit(root, control, dag, lease_token=token)


def cmd_release_lease(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    with writer_lock(root):
        control, dag = load_state(root)
        require_lease(control, args.lease_token)
        control["lease"] = None
        save_state(root, control, dag, "LEASE_RELEASED", {"reason": args.reason})
    return emit(root, control, dag)


def cmd_continue_round(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    if args.additional_walltime_minutes < 1:
        raise ValueError("--additional-walltime-minutes must be at least 1")
    require_control_key(root, args.control_key)
    with writer_lock(root):
        control, dag = load_state(root)
        if control["round_status"] not in {"ACTIVE", "PAUSED"}:
            raise ValueError("Only the active paused Round can be continued")
        control["round_status"] = "ACTIVE"
        control["round_deadline"] = (datetime.now(timezone.utc) + timedelta(minutes=args.additional_walltime_minutes)).isoformat()
        save_state(root, control, dag, "ROUND_CONTINUED", {"reason": args.reason})
    return emit(root, control, dag)


def cmd_approve_high_cost(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    require_control_key(root, args.control_key)
    with writer_lock(root):
        control, dag = load_state(root)
        if control.get("round_status") != "ACTIVE" or not control.get("active_round_id"):
            raise ValueError("A high-cost decision requires an ACTIVE Round")
        current_round = control["active_round_id"]
        approved = bool(args.approve)
        control["high_cost_approved"] = approved
        omitted: list[str] = []
        if not approved:
            for node in nodes(dag):
                if node.get("round_id") == current_round and node["capability_id"] in HIGH_COST and node["status"] == "pending":
                    node["status"] = "cancelled"
                    node["waived"] = True
                    node["waiver_reason"] = f"high-cost bundle declined: {args.rationale}"
                    node["updated_at"] = now()
                    omitted.append(node["node_id"])
            declined_descriptions = set(omitted)
            # Only the vector-Clustering Nodes that directly consume a declined
            # Description are impossible.  A001/A002/C012 deliberately retain
            # the remaining Cluster results and must not be transitively waived.
            for child in nodes(dag):
                if (
                    child.get("round_id") == current_round
                    and child["status"] == "pending"
                    and child.get("stage") == "clustering"
                    and any(parent in declined_descriptions for parent in child.get("dependencies", []))
                ):
                    child["status"] = "cancelled"
                    child["waived"] = True
                    child["waiver_reason"] = "required high-cost Description was declined"
                    child["updated_at"] = now()
                    omitted.append(child["node_id"])
            if clustering_nodes_terminal(dag, current_round):
                rebuild_cluster_registry(root, control, dag, current_round)
        save_state(root, control, dag, "HIGH_COST_DECISION", {"approved": approved, "rationale": args.rationale, "omitted_node_ids": omitted})
    return emit(root, control, dag)


def cmd_approve_series(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    require_control_key(root, args.control_key)
    with writer_lock(root):
        control, dag = load_state(root)
        if control.get("round_status") != "ACTIVE":
            raise ValueError("Series approval requires an ACTIVE Round")
        c012 = latest(dag, "C012", status="succeeded", round_id=control.get("active_round_id"))
        if not c012:
            raise ValueError("No succeeded C012 Node exists")
        control["series_gate_revision"] = c012["node_id"]
        save_state(root, control, dag, "SERIES_GATE_APPROVED", {"c012_node_id": c012["node_id"]})
    return emit(root, control, dag)


def cmd_revise_series(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    require_control_key(root, args.control_key)
    if args.min_ff_evaluate < 5:
        raise ValueError("--min-ff-evaluate must be at least 5")
    if args.leiden_resolution <= 0:
        raise ValueError("--leiden-resolution must be greater than 0")
    with writer_lock(root):
        control, dag = load_state(root); require_lease(control, args.lease_token)
        current_round = control.get("active_round_id")
        if control.get("round_status") != "ACTIVE":
            raise ValueError("Series revision requires the active Round")
        if any(node["round_id"] == current_round and node["wave"] == "standard" for node in nodes(dag)):
            raise ValueError("Series parameters cannot be revised after standard analysis was planned; start a new Run if scientific scope must change")
        if any(node["round_id"] == current_round and node["status"] == "running" for node in nodes(dag)):
            raise ValueError("Series parameters cannot be revised while Nodes are running")
        current_parameters = control.get("current_parameters") or {}
        if (
            int(current_parameters.get("min_ff_evaluate", -1)) == int(args.min_ff_evaluate)
            and float(current_parameters.get("leiden_resolution", -1.0)) == float(args.leiden_resolution)
        ):
            raise ValueError("Series revision parameters are unchanged; no new scientific Node would be created")
        clustering_nodes = [
            node["node_id"] for node in nodes(dag)
            if node["round_id"] == current_round and node["capability_id"] in {"C001", "C002", "C003", "C004", "C005", "C006", "C007", "C008", "C009", "C010"}
        ]
        if not clustering_nodes or any(lookup(dag)[node_id]["status"] not in {"succeeded", "cancelled"} for node_id in clustering_nodes):
            raise ValueError("All planned C001-C010 Nodes must be terminal before revising Series parameters")
        parameters = {
            "min_ff_evaluate": int(args.min_ff_evaluate),
            "favorable_fraction_threshold": float(profile()["basic_compute"]["favorable_fraction_threshold"]),
            "high_quantile": 0.8, "low_quantile": 0.2,
        }
        a001, _ = add_node(control, dag, "A001", clustering_nodes, "basic", parameters)
        a002, _ = add_node(control, dag, "A002", clustering_nodes, "basic", parameters)
        c012, _ = add_node(control, dag, "C012", [a001["node_id"], a002["node_id"]], "basic", {
            "min_ff_evaluate": parameters["min_ff_evaluate"],
            "favorable_fraction_threshold": parameters["favorable_fraction_threshold"],
            "leiden_resolution": float(args.leiden_resolution),
            "random_seed": profile()["basic_compute"]["leiden_seed"],
        })
        control["current_parameters"] = {"min_ff_evaluate": int(args.min_ff_evaluate), "leiden_resolution": float(args.leiden_resolution)}
        control["series_gate_revision"] = None
        save_state(root, control, dag, "SERIES_REVISION_PLANNED", {"a001_node_id": a001["node_id"], "a002_node_id": a002["node_id"], "c012_node_id": c012["node_id"], "reason": args.reason})
    return emit(root, control, dag, revised_node_ids=[a001["node_id"], a002["node_id"], c012["node_id"]])


def cmd_plan_basic(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    with writer_lock(root):
        control, dag = load_state(root)
        require_lease(control, args.lease_token)
        if required_action(root, control, dag)["code"] != "PLAN_BASIC":
            raise ValueError("Runtime is not requesting PLAN_BASIC")
        prof = profile(); basic = prof["basic_compute"]
        created: list[str] = []
        description_nodes: dict[str, str] = {}
        for capability_id in basic["description_capabilities"]:
            node, added = add_node(control, dag, capability_id, [], "basic")
            description_nodes[capability_id] = node["node_id"]
            if added: created.append(node["node_id"])
        clustering_nodes: list[str] = []
        for capability_id in basic["direct_structure_clustering"]:
            node, added = add_node(control, dag, capability_id, [], "basic", {"min_cluster_size": basic["min_cluster_size"]})
            clustering_nodes.append(node["node_id"])
            if added: created.append(node["node_id"])
        for capability_id in basic["vector_clustering_capabilities"]:
            for representation in basic["vector_clustering_representations"]:
                node, added = add_node(control, dag, capability_id, [description_nodes[representation]], "basic", {
                    "input_representation": representation, "min_cluster_size": basic["min_cluster_size"]
                })
                clustering_nodes.append(node["node_id"])
                if added: created.append(node["node_id"])
        parameters = {
            "min_ff_evaluate": int(control["current_parameters"]["min_ff_evaluate"]),
            "favorable_fraction_threshold": float(basic["favorable_fraction_threshold"]),
            "high_quantile": 0.8, "low_quantile": 0.2,
        }
        a001, added = add_node(control, dag, "A001", clustering_nodes, "basic", parameters)
        if added: created.append(a001["node_id"])
        a002, added = add_node(control, dag, "A002", clustering_nodes, "basic", parameters)
        if added: created.append(a002["node_id"])
        c012, added = add_node(control, dag, "C012", [a001["node_id"], a002["node_id"]], "basic", {
            "min_ff_evaluate": parameters["min_ff_evaluate"], "favorable_fraction_threshold": parameters["favorable_fraction_threshold"],
            "leiden_resolution": float(control["current_parameters"]["leiden_resolution"]), "random_seed": basic["leiden_seed"]
        })
        if added: created.append(c012["node_id"])
        save_state(root, control, dag, "BASIC_PLANNED", {"created_node_ids": created})
    return emit(root, control, dag, created_node_ids=created)


def cmd_plan_standard(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    with writer_lock(root):
        control, dag = load_state(root); require_lease(control, args.lease_token)
        if required_action(root, control, dag)["code"] != "PLAN_STANDARD":
            raise ValueError("Runtime is not requesting PLAN_STANDARD")
        prof = profile()["standard_analysis"]
        current_round = control.get("active_round_id")
        c012 = latest(dag, "C012", status="succeeded", round_id=current_round)
        a001 = latest(dag, "A001", status="succeeded", round_id=current_round); a002 = latest(dag, "A002", status="succeeded", round_id=current_round)
        if not all((c012, a001, a002)): raise ValueError("A001, A002, and C012 must be complete")
        d = {capability_id: latest(dag, capability_id, status="succeeded", round_id=current_round) for capability_id in profile()["basic_compute"]["description_capabilities"]}
        created: list[str] = []
        specifications=[]
        if d.get("D001"):
            specifications.append(("A003", [d["D001"]["node_id"], c012["node_id"], a001["node_id"], a002["node_id"]], {"description_id": "D001"}))
        if d.get("D002"):
            specifications.extend([
                ("A004", [d["D002"]["node_id"], c012["node_id"]], {"description_id": "D002", "random_seed": 61453}),
                ("A006", [d["D002"]["node_id"], c012["node_id"]], {"description_id": "D002", "metric": "tanimoto"}),
            ])
        if all(d.get(item) for item in prof["model_description_panel"]):
            specifications.append(("A005", [*[d[item]["node_id"] for item in prof["model_description_panel"]], c012["node_id"]], {"min_local_samples": prof["minimum_local_model_samples"], "random_seed": 61453}))
        specifications.extend([
            ("A007", [c012["node_id"]], {}),
            ("A008", [c012["node_id"]], {"role": "type-i", "top_k": prof["mmp_type_i_top_k"], "cuts": 1, "radius_min": 0, "radius_max": 2}),
        ])
        standard_ids: list[str] = []
        for capability_id, dependencies, parameters in specifications:
            node, added = add_node(control, dag, capability_id, dependencies, "standard", parameters)
            standard_ids.append(node["node_id"])
            if added: created.append(node["node_id"])
        report, added = add_node(control, dag, "A009", [a001["node_id"], a002["node_id"], c012["node_id"], *standard_ids], "standard")
        if added: created.append(report["node_id"])
        save_state(root, control, dag, "STANDARD_PLANNED", {"created_node_ids": created})
    return emit(root, control, dag, created_node_ids=created)


def artifact(role: str, path: Path, node: dict[str, Any] | None = None) -> dict[str, Any]:
    resolved = path.resolve()
    digest = sha256(resolved)
    value = {"role": role, "artifact_type": role, "path": str(resolved), "sha256": digest}
    if node:
        value.update({"source_node_id": node["node_id"], "source_capability_id": node["capability_id"]})
        result = node.get("result") or {}
        recorded_primary = Path(str(result.get("primary_path", "")))
        if recorded_primary.is_file() and recorded_primary.resolve() == resolved and result.get("primary_sha256") != digest:
            raise ValueError(f"Upstream primary artifact hash changed after Node completion: {node['node_id']}")
        result_path = Path(str(result.get("description_result_path", "")))
        if role == "description" and result_path.is_file():
            result_digest = sha256(result_path)
            if result.get("description_result_sha256") != result_digest:
                raise ValueError(f"Description Result hash changed after Node completion: {node['node_id']}")
            value.update({"result_path": str(result_path.resolve()), "result_sha256": result_digest})
    return value


def create_description_result(
    result_dir: Path,
    node: dict[str, Any],
    capability: dict[str, Any],
    primary: Path,
    expected_compound_ids: list[str] | None = None,
) -> Path:
    """Bind a Description payload to the canonical Vector-Clustering contract.

    Description Skills retain their stable scientific CSV/Parquet and manifest
    formats.  The Runtime owns this small cross-Skill sidecar so all six vector
    Clustering Skills receive one deterministic, validated representation
    contract without duplicating orchestration logic in eighteen kernels.
    """
    manifest_path = result_dir / "description_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Description Node did not produce description_manifest.json: {node['node_id']}")
    manifest = read_json(manifest_path)
    required = ("row_count", "feature_count", "feature_columns", "value_semantics", "natural_metric", "created_at")
    missing = [key for key in required if key not in manifest]
    if missing:
        raise ValueError(f"Description manifest is missing canonical contract fields {missing}: {node['node_id']}")
    if str(manifest.get("capability_id")) != str(node["capability_id"]):
        raise ValueError(f"Description manifest capability_id does not match Node {node['node_id']}")
    expected_attempt_id = str((node.get("attempts") or [{}])[-1].get("attempt_id", ""))
    manifest_identity_errors = {
        key: {"expected": expected, "actual": manifest.get(key)}
        for key, expected in {
            "schema_version": "2.0.0",
            "conductor_version": VERSION,
            "artifact_stage": "description",
            "node_id": node["node_id"],
            "attempt_id": expected_attempt_id,
            "skill_name": node["skill_name"],
        }.items()
        if manifest.get(key) != expected
    }
    if manifest_identity_errors:
        raise ValueError(f"Description manifest identity/version mismatch: {manifest_identity_errors}")
    feature_columns = [str(value) for value in manifest.get("feature_columns", [])]
    feature_count = int(manifest.get("feature_count", 0))
    if feature_count < 1 or len(feature_columns) != feature_count or len(feature_columns) != len(set(feature_columns)):
        raise ValueError(
            f"Description {node['node_id']} has an unusable feature contract: "
            f"feature_count={feature_count}, unique_feature_columns={len(set(feature_columns))}"
        )
    semantics = str(manifest.get("value_semantics") or capability.get("value_semantics") or "")
    metric = str(manifest.get("natural_metric") or capability.get("natural_metric") or "")
    permitted = {
        "binary_fingerprint": "tanimoto",
        "sparse_count": "cosine",
        "dense_continuous": "euclidean",
        "dense_shape_moment": "manhattan",
        "dense_embedding": "cosine",
    }
    if semantics not in permitted or metric != permitted[semantics]:
        raise ValueError(
            f"Description {node['node_id']} declares incompatible value_semantics/natural_metric: "
            f"{semantics!r}/{metric!r}"
        )
    expected_semantics = str(capability.get("value_semantics") or "")
    expected_metric = str(capability.get("natural_metric") or "")
    if semantics != expected_semantics or metric != expected_metric:
        raise ValueError(
            f"Description manifest representation contract differs from capability metadata: "
            f"manifest={semantics!r}/{metric!r}, capability={expected_semantics!r}/{expected_metric!r}"
        )
    declared_output = str(manifest.get("output", ""))
    if declared_output != primary.name:
        raise ValueError(
            f"Description manifest output {declared_output!r} does not match primary payload {primary.name!r}"
        )
    import pandas as pd
    if primary.suffix.lower() == ".parquet":
        payload = pd.read_parquet(primary)
    else:
        header = pd.read_csv(primary, nrows=0)
        payload = pd.read_csv(primary, dtype={"compound_id": "string"} if "compound_id" in header.columns else None)
    if "compound_id" not in payload.columns:
        raise ValueError(f"Description payload has no compound_id column: {node['node_id']}")
    payload_ids = payload["compound_id"].astype("string")
    if payload_ids.isna().any() or payload_ids.str.strip().eq("").any() or payload_ids.duplicated().any():
        raise ValueError(f"Description payload compound_id values are null, blank, or duplicated: {node['node_id']}")
    if len(payload) != int(manifest["row_count"]):
        raise ValueError(
            f"Description manifest row_count={manifest['row_count']} does not match payload rows={len(payload)}: {node['node_id']}"
        )
    missing_payload_features = sorted(set(feature_columns) - set(payload.columns))
    if missing_payload_features:
        raise ValueError(
            f"Description payload is missing manifest feature columns {missing_payload_features[:10]}: {node['node_id']}"
        )
    non_numeric_features = [
        column for column in feature_columns
        if not pd.api.types.is_numeric_dtype(payload[column])
    ]
    if non_numeric_features:
        raise ValueError(
            f"Description payload has non-numeric feature columns {non_numeric_features[:10]}: {node['node_id']}"
        )
    finite_features = payload[feature_columns].replace([float("inf"), float("-inf")], pd.NA)
    if not finite_features.notna().to_numpy().any():
        raise ValueError(
            f"Description payload contains no finite feature value and cannot be clustered: {node['node_id']}"
        )
    if expected_compound_ids is not None and payload_ids.astype(str).tolist() != expected_compound_ids:
        raise ValueError(
            f"Description payload compound_id order/content does not match the initialized Run input: {node['node_id']}"
        )
    quality_flags = [str(value) for value in manifest.get("warnings", [])]
    errors = manifest.get("errors") or []
    if errors:
        quality_flags.append(f"row_level_errors:{len(errors)}")
    sidecar = result_dir / "description_result.json"
    atomic_json(sidecar, {
        "document_type": "description_result",
        "schema_version": "1.0.0",
        "node_id": node["node_id"],
        "capability_id": node["capability_id"],
        "payload": primary.name,
        "row_count": int(manifest["row_count"]),
        "feature_count": feature_count,
        "value_semantics": semantics,
        "natural_metric": metric,
        "feature_columns": feature_columns,
        "quality_flags": quality_flags,
        "created_at": str(manifest["created_at"]),
    })
    return sidecar


def runtime_artifacts(root: Path) -> dict[str, Path]:
    return {
        "cluster_membership_matrix": root / "runtime" / "cluster_membership" / "Cpd_Cluster_matrix_C000001_099999.csv",
        "cluster_membership_long": root / "runtime" / "cluster_membership_long.csv",
        "cluster_registry": root / "runtime" / "cluster_registry.csv",
    }


def execution_request(root: Path, control: dict[str, Any], dag: dict[str, Any], node: dict[str, Any], attempt_id: str, scratch: Path) -> dict[str, Any]:
    caps = capabilities(); cap = caps[node["capability_id"]]; table = lookup(dag)
    dataset_path = Path(control["input_path"])
    if not dataset_path.is_file() or sha256(dataset_path) != control.get("input_sha256"):
        raise ValueError("Run input CSV changed after initialization; restore it or start a new Run")
    input_values = [artifact("dataset", dataset_path)]
    dependencies = [table[item] for item in node.get("dependencies", [])]
    capability_id = node["capability_id"]
    if cap["stage"] == "clustering" and cap.get("family") == "description_vector":
        source = dependencies[0]; input_values.append(artifact("description", primary_path(source), source))
    runtime_files = runtime_artifacts(root)
    if capability_id in {"A001", "A002"}:
        input_values.append(artifact("clustering", runtime_files["cluster_membership_matrix"]))
        input_values.append(artifact("cluster_registry", runtime_files["cluster_registry"]))
    elif capability_id == "C012":
        input_values.extend([
            artifact("cluster_membership_matrix", runtime_files["cluster_membership_matrix"]),
            artifact("cluster_registry", runtime_files["cluster_registry"]),
            artifact("cluster_profile", primary_path(dependencies[0]), dependencies[0]),
            artifact("cluster_enrichment", primary_path(dependencies[1]), dependencies[1]),
        ])
    elif capability_id in {"A003", "A004", "A005", "A006", "A007", "A008", "A009"}:
        for source in dependencies:
            if source.get("status") != "succeeded":
                continue
            # A008 remains an A009 dependency so the deterministic standard
            # workflow waits for MMP Type-I.  MMP has a dedicated report and is
            # intentionally not integrated into the standard Series report;
            # do not load its potentially large pair table merely to discard it.
            if capability_id == "A009" and source.get("capability_id") == "A008":
                continue
            role = "source"
            if source["capability_id"].startswith("D"): role = "description"
            elif source["capability_id"] == "C012": role = "series"
            elif source["capability_id"] == "A001": role = "cluster_profile"
            elif source["capability_id"] == "A002": role = "cluster_enrichment"
            input_values.append(artifact(role, primary_path(source), source))
        for role, name in (("cluster_registry", "cluster_registry.csv"), ("series_registry", "series_registry.csv"), ("analysis_unit_membership", "analysis_unit_membership.csv"), ("analysis_unit_registry", "analysis_unit_registry.csv"), ("series_cluster_membership", "series_cluster_membership.csv"), ("compound_series_support", "compound_series_support.csv")):
            path = root / "runtime" / name
            if path.is_file(): input_values.append(artifact(role, path))
    available_cpu = int(control["available_cpu_cores"])
    node_cpu = available_cpu if capability_id == "D019" else max(1, available_cpu // max(1, int(control["parallel_limit"])))
    skill_options: dict[str, Any] = {}
    if capability_id == "D019":
        cores_per_compound = min(4, node_cpu)
        skill_options = {"available_cpu_cores": node_cpu, "cores_per_compound": cores_per_compound, "compound_workers": max(1, node_cpu // cores_per_compound)}
    elif capability_id == "D016":
        skill_options = {"available_cpu_cores": node_cpu, "compound_workers": min(8, node_cpu)}
    elif capability_id == "D020":
        skill_options = {"cpu_threads": node_cpu}
    request = {
        "schema_version": "1.0.0",
        "identity": {"project": control["project"], "run_id": control["run_id"], "round_id": node["round_id"], "node_id": node["node_id"], "attempt_id": attempt_id, "capability_id": capability_id, "skill_name": node["skill_name"]},
        "inputs": input_values,
        "columns": control["columns"],
        "endpoint": {"higher_is_better": control["higher_is_better"]},
        "subject": {"mode": "batch" if capability_id.startswith("A") or capability_id == "C012" else "global"},
        "parameters": node.get("parameters", {}),
        "resources": {"available_cpu_cores": available_cpu, "node_cpu_cores": node_cpu, "native_thread_limit": 1, "skill_options": skill_options},
        "output": {"directory": str((scratch / "skill_output").resolve()), "overwrite": False},
        "created_at": now(),
    }
    required_roles = set(cap.get("conductor_request", {}).get("required_input_roles", []))
    supplied_roles = {str(item.get("role")) for item in input_values}
    missing_roles = sorted(required_roles - supplied_roles)
    if missing_roles:
        raise ValueError(
            f"Runtime could not prepare required input role(s) for {capability_id}: "
            + ", ".join(missing_roles)
        )
    return request


def choose_primary(result_dir: Path, capability: dict[str, Any]) -> Path:
    output = capability.get("output") or {}
    candidates = [output.get(key) for key in ("filename", "membership", "table", "summary")]
    basename = output.get("basename")
    if basename: candidates.extend([f"{basename}.csv", f"{basename}.parquet"])
    for name in candidates:
        if name and (result_dir / str(name)).is_file(): return result_dir / str(name)
    csvs = sorted(path for path in result_dir.rglob("*.csv") if "manifest" not in path.name and "warning" not in path.name)
    if csvs: return csvs[0]
    jsons = sorted(path for path in result_dir.rglob("*.json") if path.name not in {"execution_event.json"})
    if jsons: return jsons[0]
    raise FileNotFoundError(f"No primary artifact was produced in {result_dir}")


def clustering_nodes_terminal(dag: dict[str, Any], round_id: str) -> bool:
    relevant = [
        node for node in nodes(dag)
        if node.get("round_id") == round_id
        and node.get("stage") == "clustering"
        and node.get("capability_id") != "C012"
    ]
    return bool(relevant) and all(node["status"] in {"succeeded", "cancelled"} for node in relevant)


def rebuild_cluster_registry(root: Path, control: dict[str, Any], dag: dict[str, Any], round_id: str) -> None:
    import pandas as pd
    caps = capabilities(); records: list[dict[str, Any]] = []; membership_rows: list[dict[str, Any]] = []; serial = 1
    input_frame = pd.read_csv(control["input_path"], dtype=str)
    id_column = control["columns"]["compound_id"]
    if id_column not in input_frame.columns:
        raise ValueError(f"Configured compound ID column is absent from the input CSV: {id_column}")
    if input_frame[id_column].isna().any() or input_frame[id_column].astype(str).duplicated().any():
        raise ValueError("Input compound IDs must be non-null and unique before Cluster Registry construction")
    input_frame[id_column] = input_frame[id_column].astype(str)
    known_compounds = set(input_frame[id_column])
    for node in sorted(nodes(dag), key=lambda item: item["node_id"]):
        cap = caps.get(node["capability_id"], {})
        if node.get("round_id") != round_id or node["status"] != "succeeded" or cap.get("stage") != "clustering" or node["capability_id"] == "C012": continue
        path = primary_path(node)
        frame = pd.read_csv(path, dtype={"compound_id": "string", "cluster_id": "string"})
        missing_columns = sorted({"compound_id", "cluster_id", "membership_value"} - set(frame.columns))
        if missing_columns:
            raise ValueError(
                f"Clustering result {node['node_id']} is missing required membership columns: {missing_columns}"
            )
        if frame["compound_id"].isna().any():
            raise ValueError(f"Clustering result has null compound_id values: {node['node_id']}")
        frame["compound_id"] = frame["compound_id"].astype(str)
        unknown = sorted(set(frame["compound_id"]) - known_compounds)
        if unknown:
            raise ValueError(f"Clustering result {node['node_id']} contains unknown compound IDs: {unknown[:10]}")
        missing_compounds = sorted(known_compounds - set(frame["compound_id"]))
        if missing_compounds:
            raise ValueError(
                f"Clustering result {node['node_id']} omits input compound IDs instead of recording explicit "
                f"unassigned rows: {missing_compounds[:10]}"
            )
        serialized_membership = frame["membership_value"].astype("string").str.strip().str.lower()
        numeric_membership = pd.to_numeric(frame["membership_value"], errors="coerce")
        valid_membership = serialized_membership.isin({"true", "false", "yes", "no"}) | numeric_membership.notna()
        if not bool(valid_membership.all()):
            examples = sorted(set(serialized_membership.loc[~valid_membership].dropna().astype(str)))[:10]
            raise ValueError(f"Clustering result {node['node_id']} has invalid membership_value entries: {examples}")
        active = serialized_membership.isin({"1", "1.0", "true", "yes"}) | numeric_membership.fillna(0).gt(0)
        frame = frame.loc[active]
        if frame["cluster_id"].isna().any() or frame["cluster_id"].astype(str).str.strip().eq("").any():
            raise ValueError(f"Active Clustering memberships have null/blank cluster_id values: {node['node_id']}")
        frame["cluster_id"] = frame["cluster_id"].astype(str)
        frame = frame.drop_duplicates(["compound_id", "cluster_id"])
        minimum_cluster_size = int(node.get("parameters", {}).get("min_cluster_size", 5))
        undersized = frame.groupby("cluster_id")["compound_id"].nunique()
        undersized = undersized.loc[undersized.lt(minimum_cluster_size)]
        if len(undersized):
            examples = {str(key): int(value) for key, value in undersized.head(10).items()}
            raise ValueError(
                f"Clustering result {node['node_id']} contains active Clusters below "
                f"min_cluster_size={minimum_cluster_size}: {examples}"
            )
        source_description = None
        for dependency in node.get("dependencies", []):
            parent = lookup(dag).get(dependency)
            if parent and parent["capability_id"].startswith("D"): source_description = parent["capability_id"]
        summary_path = Path((node.get("result") or {}).get("result_dir", "")) / "cluster_summary.csv"
        summary = pd.read_csv(summary_path) if summary_path.is_file() else pd.DataFrame()
        definition_columns = [
            column for column in (
                "scaffold_smiles", "mcs_smarts", "core_smarts", "fragment_smiles",
                "recap_smiles", "brics_smiles", "structure", "definition",
                "structure_definition", "cluster_label",
            ) if column in summary.columns
        ]
        for local_id, part in frame.groupby("cluster_id", sort=True):
            global_id = f"C{serial:06d}"; serial += 1
            members = sorted(set(part["compound_id"].dropna().astype(str)))
            definition = ""
            if len(summary) and "cluster_id" in summary.columns and definition_columns:
                matched = summary.loc[summary["cluster_id"].astype(str).eq(str(local_id))]
                if len(matched):
                    definition = next((str(matched.iloc[0][column]) for column in definition_columns if pd.notna(matched.iloc[0][column]) and str(matched.iloc[0][column]).strip()), "")
            records.append({"cluster_id": global_id, "source_cluster_id": str(local_id), "source_node_id": node["node_id"], "clustering_id": node["capability_id"], "clustering_name": cap.get("display_name", cap.get("skill_name", node["capability_id"])), "description_id": source_description or "", "description_name": caps.get(source_description or "", {}).get("display_name", ""), "input_kind": "description_vector" if source_description else "structure", "sample_count": len(members), "structure_definition": definition, "parameters_json": json.dumps(node.get("parameters", {}), ensure_ascii=False, sort_keys=True)})
            membership_rows.extend({"compound_id": compound_id, "cluster_id": global_id, "membership_value": True} for compound_id in members)
    record_columns = ["cluster_id", "source_cluster_id", "source_node_id", "clustering_id", "clustering_name", "description_id", "description_name", "input_kind", "sample_count", "structure_definition", "parameters_json"]
    runtime = root / "runtime"
    staging = runtime / f".cluster_registry_{uuid.uuid4().hex}"
    staging.mkdir(parents=True, exist_ok=False)
    pd.DataFrame(records, columns=record_columns).to_csv(staging / "cluster_registry.csv", index=False)
    long_frame = pd.DataFrame(membership_rows, columns=["compound_id", "cluster_id", "membership_value"])
    long_frame.to_csv(staging / "cluster_membership_long.csv", index=False)
    wide = pd.DataFrame({"compound_id": input_frame[id_column].astype(str)})
    if len(long_frame):
        matrix = long_frame.assign(value=True).pivot_table(index="compound_id", columns="cluster_id", values="value", aggfunc="max", fill_value=False).reset_index()
        wide = wide.merge(matrix, on="compound_id", how="left")
        for column in wide.columns[1:]: wide[column] = wide[column].eq(True)
    membership_staging = staging / "cluster_membership"; membership_staging.mkdir()
    staged_matrix = membership_staging / "Cpd_Cluster_matrix_C000001_099999.csv"; wide.to_csv(staged_matrix, index=False)
    atomic_json(membership_staging / "index.json", {"schema_version": "1.0.0", "shards": [{"path": staged_matrix.name, "first_cluster_id": records[0]["cluster_id"] if records else None, "last_cluster_id": records[-1]["cluster_id"] if records else None, "row_count": len(wide), "cluster_count": len(records), "sha256": sha256(staged_matrix)}]})
    directory = runtime / "cluster_membership"; directory.mkdir(exist_ok=True)
    promotions = [
        (staging / "cluster_registry.csv", runtime / "cluster_registry.csv"),
        (staging / "cluster_membership_long.csv", runtime / "cluster_membership_long.csv"),
        (staged_matrix, directory / staged_matrix.name),
        (membership_staging / "index.json", directory / "index.json"),
    ]
    try:
        for source, target in promotions:
            os.replace(source, target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def promote_series_runtime(root: Path, result_dir: Path) -> None:
    names = ("series_registry.csv", "series_cluster_membership.csv", "compound_series_support.csv", "analysis_unit_membership.csv", "analysis_unit_registry.csv", "series_summary.json")
    missing = [name for name in names if not (result_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"C012 is missing required Series artifacts: {missing}")
    runtime = root / "runtime"; staging = runtime / f".series_runtime_{uuid.uuid4().hex}"; staging.mkdir(exist_ok=False)
    try:
        for name in names: shutil.copy2(result_dir / name, staging / name)
        for name in names: os.replace(staging / name, runtime / name)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def run_node(root: Path, node_id: str) -> dict[str, Any]:
    with writer_lock(root):
        control, dag = load_state(root)
        node = lookup(dag).get(node_id)
        if node is None:
            raise KeyError(f"Execution packet references unknown Node: {node_id}")
        if node["status"] != "pending":
            return {"node_id": node_id, "status": node["status"]}
        attempt_id = f"ATT{len(node['attempts']) + 1:04d}"
        scratch = root / "runtime" / "scratch" / node_id / attempt_id
        request_path = scratch / "execution_request.json"
        log_path = scratch / "execution.log"
        node["status"] = "running"
        node["updated_at"] = now()
        node["attempts"].append({
            "attempt_id": attempt_id,
            "status": "running",
            "runtime_pid": os.getpid(),
            "runtime_host": socket.gethostname(),
            "request_path": str(request_path),
            "log_path": str(log_path),
            "started_at": now(),
        })
        save_state(root, control, dag, "NODE_STARTED", {"node_id": node_id, "attempt_id": attempt_id})
    final_dir: Path | None = None
    final_dir_created = False
    try:
        scratch.mkdir(parents=True, exist_ok=False)
        # Re-read the committed Node state so request construction is based on
        # the same revision that made the attempt visible to another session.
        control, dag = load_state(root)
        node = lookup(dag)[node_id]
        request = execution_request(root, control, dag, node, attempt_id, scratch)
        atomic_json(request_path, request)
        cap = capabilities()[node["capability_id"]]
        launcher = Path(cap["_skill_dir"]) / "scripts" / "launch.py"
        if not launcher.is_file():
            raise FileNotFoundError(f"Skill launcher does not exist: {launcher}")
        command = [sys.executable, str(launcher), "--conductor-request", str(request_path)]
        resources = request.get("resources", {})
        environment = os.environ.copy()
        environment.update({
            "PYTHONUNBUFFERED": "1",
            "CONDUCTOR_AVAILABLE_CPU_CORES": str(resources.get("available_cpu_cores", 1)),
            "CONDUCTOR_NODE_CPU_CORES": str(resources.get("node_cpu_cores", 1)),
            "CONDUCTOR_ATTEMPT_TMP": str((scratch / "tmp").resolve()),
        })
        with log_path.open("w", encoding="utf-8") as log:
            completed = subprocess.run(command, cwd=project_root(), env=environment, stdout=log, stderr=subprocess.STDOUT)
        output = scratch / "skill_output"
        event_path = output / "execution_event.json"
        if completed.returncode != 0:
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
            raise RuntimeError(f"Skill exited with code {completed.returncode}. {tail}")
        if not event_path.is_file():
            raise FileNotFoundError("Skill did not produce execution_event.json")
        event = read_json(event_path)
        if event.get("status") != "succeeded":
            raise RuntimeError(f"Skill event status is not succeeded: {event.get('status')}")
        expected_identity = request["identity"]
        identity_fields = ("project", "run_id", "round_id", "node_id", "attempt_id", "capability_id", "skill_name")
        mismatches = {
            field: {"expected": expected_identity[field], "actual": event.get(field)}
            for field in identity_fields if event.get(field) != expected_identity[field]
        }
        if mismatches:
            raise ValueError(f"Skill execution_event identity mismatch: {mismatches}")
        event_artifacts = event.get("artifacts")
        if not isinstance(event_artifacts, list) or not event_artifacts:
            raise ValueError("Skill execution_event must register at least one artifact")
        registered_artifacts: set[str] = set()
        output_root = output.resolve()
        for item in event_artifacts:
            if not isinstance(item, dict) or not item.get("path") or not item.get("sha256"):
                raise ValueError("Skill execution_event contains an incomplete artifact record")
            relative = Path(str(item["path"]))
            if relative.is_absolute():
                raise ValueError(f"Skill artifact path must be relative to its output directory: {relative}")
            source_artifact = (output_root / relative).resolve()
            try:
                normalized_relative = source_artifact.relative_to(output_root).as_posix()
            except ValueError as exc:
                raise ValueError(f"Skill artifact escapes its output directory: {relative}") from exc
            if normalized_relative in registered_artifacts:
                raise ValueError(f"Skill execution_event registers the same artifact twice: {normalized_relative}")
            if not source_artifact.is_file() or sha256(source_artifact) != str(item["sha256"]):
                raise ValueError(f"Skill artifact is missing or has a hash mismatch: {normalized_relative}")
            registered_artifacts.add(normalized_relative)
        final_dir = root / node["stage"] / node_id
        if final_dir.exists():
            raise FileExistsError(f"Final Node directory already exists: {final_dir}")
        shutil.copytree(output, final_dir)
        final_dir_created = True
        primary = choose_primary(final_dir, cap)
        primary_relative = primary.resolve().relative_to(final_dir.resolve()).as_posix()
        if primary_relative not in registered_artifacts:
            raise ValueError(
                f"Selected primary artifact was not registered by the Skill execution_event: {primary_relative}"
            )
        result_value = {
            "result_dir": str(final_dir),
            "primary_path": str(primary),
            "primary_sha256": sha256(primary),
            "execution_event": str(final_dir / "execution_event.json"),
            "execution_event_sha256": sha256(final_dir / "execution_event.json"),
        }
        if node["stage"] == "description":
            import pandas as pd
            input_id_column = control["columns"]["compound_id"]
            input_header = pd.read_csv(control["input_path"], nrows=0)
            input_ids = pd.read_csv(
                control["input_path"],
                usecols=[input_id_column],
                dtype={input_id_column: "string"} if input_id_column in input_header.columns else None,
            )[input_id_column].astype(str).tolist()
            description_result = create_description_result(final_dir, node, cap, primary, input_ids)
            result_value.update({
                "description_result_path": str(description_result),
                "description_result_sha256": sha256(description_result),
            })
        with writer_lock(root):
            control, dag = load_state(root)
            node = lookup(dag)[node_id]
            if node["status"] != "running":
                raise RuntimeError(f"Node {node_id} changed state during execution: {node['status']}")
            attempt = next((item for item in node["attempts"] if item.get("attempt_id") == attempt_id), None)
            if attempt is None:
                raise RuntimeError(f"Node {node_id} lost attempt record {attempt_id}")
            node["status"] = "succeeded"
            node["result"] = result_value
            node["error"] = None
            node["updated_at"] = now()
            attempt.update({"status": "succeeded", "finished_at": now()})
            if node["stage"] == "clustering" and node["capability_id"] != "C012" and clustering_nodes_terminal(dag, node["round_id"]):
                rebuild_cluster_registry(root, control, dag, node["round_id"])
            if node["capability_id"] == "C012":
                promote_series_runtime(root, final_dir)
            save_state(root, control, dag, "NODE_SUCCEEDED", {"node_id": node_id, "attempt_id": attempt_id})
        return {"node_id": node_id, "status": "succeeded"}
    except Exception as exc:
        if final_dir_created and final_dir is not None and final_dir.is_dir():
            shutil.rmtree(final_dir, ignore_errors=True)
        with writer_lock(root):
            control, dag = load_state(root)
            node = lookup(dag)[node_id]
            node["status"] = "failed"
            node["result"] = None
            node["error"] = {
                "code": "SKILL_EXECUTION_FAILED",
                "message": f"{type(exc).__name__}: {exc}",
                "phase": "prepare_or_execute_or_commit",
                "request_path": str(request_path),
                "log_path": str(log_path),
                "remediation": "Inspect the diagnostic and execution log, correct the contract or environment, then retry this same Node.",
            }
            node["updated_at"] = now()
            attempt = next((item for item in node["attempts"] if item.get("attempt_id") == attempt_id), None)
            if attempt is not None:
                attempt.update({"status": "failed", "finished_at": now(), "message": f"{type(exc).__name__}: {exc}"})
            save_state(root, control, dag, "NODE_FAILED", {"node_id": node_id, "attempt_id": attempt_id, "message": str(exc)})
        return {"node_id": node_id, "status": "failed", "error": str(exc)}


def cmd_prepare_execution_packet(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    with writer_lock(root):
        control, dag = load_state(root); require_lease(control, args.lease_token)
        if required_action(root, control, dag)["code"] != "EXECUTE_RUNNABLE_BATCH": raise ValueError("Runtime is not requesting execution")
        candidates = runnable(dag, control.get("active_round_id"))
        exclusive = [node for node in candidates if node["capability_id"] in {"D019"}]
        effective_parallel = min(int(control["parallel_limit"]), int(control["available_cpu_cores"]))
        selected = exclusive[:1] if exclusive else candidates[:effective_parallel]
        packet_id = f"PKT{uuid.uuid4().hex[:12].upper()}"; path = root / "runtime" / "packets" / f"{packet_id}.json"
        lease_token = str((control.get("lease") or {}).get("token", ""))
        packet = {
            "schema_version": "1.0.0", "packet_id": packet_id,
            "run_root": str(root), "round_id": control["active_round_id"],
            "lease_fingerprint": hashlib.sha256(lease_token.encode("utf-8")).hexdigest(),
            "node_ids": [node["node_id"] for node in selected],
            "parallel_limit": min(len(selected), int(control["parallel_limit"])),
            "status": "prepared", "created_at": now(),
        }
        atomic_json(path, packet); save_state(root, control, dag, "PACKET_PREPARED", {"packet_id": packet_id, "node_ids": packet["node_ids"]})
    return emit(root, control, dag, packet_path=str(path), packet_id=packet_id)


def cmd_execute_packet(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root); packet_path = Path(args.packet).resolve()
    packet_root = (root / "runtime" / "packets").resolve()
    if packet_path.parent != packet_root:
        raise ValueError(f"Packet must be directly inside {packet_root}")
    with writer_lock(root):
        control, dag = load_state(root); packet = read_json(packet_path)
        if Path(packet["run_root"]).resolve() != root: raise ValueError("Packet belongs to a different Run root")
        if packet["status"] == "terminal":
            return emit(root, control, dag, packet=packet)
        if packet["status"] != "prepared":
            raise RuntimeError(f"Packet is already {packet['status']}; do not execute it again")
        if control.get("round_status") != "ACTIVE" or packet.get("round_id") != control.get("active_round_id"):
            raise RuntimeError("Packet is stale because its Round is not the active Round")
        current_lease = control.get("lease") or {}
        current_fingerprint = hashlib.sha256(str(current_lease.get("token", "")).encode("utf-8")).hexdigest()
        if not live_lease(control) or packet.get("lease_fingerprint") != current_fingerprint:
            raise RuntimeError(
                "Packet is stale because its originating Runtime lease is no longer current; "
                "acquire/resume the same Round and prepare a new packet"
            )
        if walltime_expired(control):
            raise RuntimeError("Round wall time expired before packet execution; pause the same Round")
        packet["status"] = "running"; packet["started_at"] = now(); atomic_json(packet_path, packet)
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, int(packet["parallel_limit"]))) as pool:
        futures = {pool.submit(run_node, root, node_id): node_id for node_id in packet["node_ids"]}
        for future in as_completed(futures):
            try: results.append(future.result())
            except Exception as exc: results.append({"node_id": futures[future], "status": "failed", "error": str(exc)})
    packet.update({"status": "terminal", "finished_at": now(), "results": results}); atomic_json(packet_path, packet)
    control, dag = load_state(root); return emit(root, control, dag, packet=packet)


def cmd_retry_node(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    with writer_lock(root):
        control, dag = load_state(root); require_control_key(root, args.control_key); require_lease(control, args.lease_token)
        node = lookup(dag).get(args.node_id)
        if not node or node["status"] != "failed": raise ValueError("retry-node requires an existing failed Node")
        if control.get("round_status") != "ACTIVE" or node.get("round_id") != control.get("active_round_id"):
            raise ValueError("retry-node can modify only the ACTIVE Round")
        # A process can die after copying Skill output but before the terminal
        # state commit. Such an uncommitted directory is not a valid artifact and
        # would otherwise make the same-Node retry fail with FileExistsError.
        stale_final = root / str(node["stage"]) / str(node["node_id"])
        expected_parent = (root / str(node["stage"])).resolve()
        if stale_final.exists():
            if stale_final.resolve().parent != expected_parent or not stale_final.is_dir():
                raise RuntimeError(f"Unsafe or invalid stale Node output path: {stale_final}")
            shutil.rmtree(stale_final)
        node["status"] = "pending"; node["result"] = None; node["error"] = None; node["updated_at"] = now()
        save_state(root, control, dag, "NODE_RETRY_REQUESTED", {"node_id": args.node_id, "reason": args.reason})
    return emit(root, control, dag)


def cmd_waive_node(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    with writer_lock(root):
        control, dag = load_state(root); require_control_key(root, args.control_key)
        node = lookup(dag).get(args.node_id)
        if not node or node["status"] != "failed": raise ValueError("waive-node requires an existing failed Node")
        if control.get("round_status") != "ACTIVE" or node.get("round_id") != control.get("active_round_id"):
            raise ValueError("waive-node can modify only the ACTIVE Round")
        if node["capability_id"] in {"A001", "A002", "C012", "A009", "I001"}:
            raise ValueError(f"{node['capability_id']} is a required control/report Node and cannot be waived; repair and retry it")
        node["status"] = "cancelled"; node["waived"] = True; node["waiver_reason"] = args.reason; node["updated_at"] = now()
        cascaded=[]
        if str(node["capability_id"]).startswith("D"):
            for child in nodes(dag):
                if child["status"]=="pending" and node["node_id"] in child.get("dependencies",[]):
                    child["status"]="cancelled"; child["waived"]=True; child["waiver_reason"]=f"required Description {node['node_id']} was waived"; child["updated_at"]=now(); cascaded.append(child["node_id"])
        current_round = str(control.get("active_round_id"))
        if clustering_nodes_terminal(dag, current_round):
            rebuild_cluster_registry(root, control, dag, current_round)
        save_state(root, control, dag, "NODE_WAIVED", {"node_id": args.node_id, "reason": args.reason, "cascaded_node_ids": cascaded})
    return emit(root, control, dag)


def cmd_pause_round(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    with writer_lock(root):
        control, dag = load_state(root); require_lease(control, args.lease_token)
        if control.get("round_status") != "ACTIVE":
            raise ValueError("Only an ACTIVE Round can be paused")
        if any(node["status"] == "running" for node in nodes(dag)): raise ValueError("Cannot pause while Nodes are running")
        control["round_status"] = "PAUSED"; control["lease"] = None
        save_state(root, control, dag, "ROUND_PAUSED", {"reason": args.reason})
    return emit(root, control, dag)


def cmd_prepare_interpretation(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    with writer_lock(root):
        control, dag = load_state(root); require_lease(control, args.lease_token)
        if required_action(root, control, dag)["code"] != "PREPARE_INTERPRETATION": raise ValueError("Runtime is not requesting Interpretation")
        report_node = latest(dag, "A009", status="succeeded", round_id=control.get("active_round_id"))
        if not report_node: raise ValueError("A009 report is required")
        directory = root / "interpretation" / control["active_round_id"]; directory.mkdir(parents=True, exist_ok=True)
        context_path = directory / "context.json"; draft_path = directory / "draft.json"
        context = {
            "schema_version": "1.0.0", "mode": "summary",
            "run_id": control["run_id"], "round_id": control["active_round_id"],
            "report_node_id": report_node["node_id"], "report_dir": report_node["result"]["result_dir"],
            "standard_summary": read_json(Path(report_node["result"]["primary_path"])),
            "allowed_sources": [report_node["result"]["primary_path"]],
            "draft_path": str(draft_path),
            "draft_contract": {
                "only_fields": [
                    "title", "executive_summary", "observations",
                    "global_series_contrasts", "on_demand_candidates", "limitations",
                ],
                "scalar_fields": ["title", "executive_summary"],
                "sentence_array_fields": [
                    "observations", "global_series_contrasts",
                    "on_demand_candidates", "limitations",
                ],
            },
            "instructions": "standard_summaryだけを用い、定型表を重複せず、GlobalとSeriesの変化、一致、不一致、On-demand候補を簡潔な日本語で記述する。",
        }
        atomic_json(context_path, context)
        node, _ = add_node(control, dag, "I001", [report_node["node_id"]], "interpretation", {"context_path": str(context_path), "draft_path": str(draft_path)})
        save_state(root, control, dag, "INTERPRETATION_PREPARED", {"node_id": node["node_id"]})
    return emit(root, control, dag, context_path=str(context_path), draft_path=str(draft_path), node_id=node["node_id"])


def render_interpretation(draft: dict[str, Any]) -> tuple[str, str]:
    title = str(draft.get("title") or "CONDUCTOR 定型解析の解釈")
    summary = str(draft.get("executive_summary") or "")
    observations = [str(item) for item in draft.get("observations", [])]
    contrasts = [str(item) for item in draft.get("global_series_contrasts", [])]
    requests = [str(item) for item in draft.get("on_demand_candidates", [])]
    limitations = [str(item) for item in draft.get("limitations", [])]
    def section(name: str, values: list[str]) -> str:
        return f"## {name}\n\n" + ("\n".join(f"- {value}" for value in values) if values else "該当なし") + "\n"
    markdown = f"# {title}\n\n{summary}\n\n" + section("主要な観察", observations) + section("GlobalとSeriesの対比", contrasts) + section("On-demand候補", requests) + section("限界", limitations)
    import html
    def cards(name: str, values: list[str]) -> str:
        body = "".join(f"<li>{html.escape(value)}</li>" for value in values) or "<li>該当なし</li>"
        return f"<section><h2>{html.escape(name)}</h2><ul>{body}</ul></section>"
    page = f"<!doctype html><html lang='ja'><head><meta charset='utf-8'><style>body{{margin:0;background:#edeae3;color:#26363d;font:15px/1.7 sans-serif}}main{{max-width:1050px;margin:32px auto;background:#fff;padding:46px}}h1,h2{{color:#314b57}}section{{border-top:1px solid #d8d4cb;padding-top:16px;margin-top:24px}}li{{margin:.55em 0}}</style></head><body><main><h1>{html.escape(title)}</h1><p>{html.escape(summary)}</p>{cards('主要な観察', observations)}{cards('GlobalとSeriesの対比', contrasts)}{cards('On-demand候補', requests)}{cards('限界', limitations)}</main></body></html>"
    return markdown, page


def cmd_commit_interpretation(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    with writer_lock(root):
        control, dag = load_state(root); require_lease(control, args.lease_token)
        node = lookup(dag).get(args.node_id)
        if not node or node["wave"] != "interpretation" or node["status"] != "pending": raise ValueError("Invalid pending Interpretation Node")
        if control.get("round_status") != "ACTIVE" or node.get("round_id") != control.get("active_round_id"):
            raise ValueError("Interpretation can be committed only to the current ACTIVE Round")
        expected_draft = Path(node["parameters"]["draft_path"]).resolve()
        draft_path = Path(args.draft or expected_draft).resolve()
        if draft_path != expected_draft:
            raise ValueError(f"Interpretation draft must use the Runtime-prepared path: {expected_draft}")
        if not draft_path.is_file(): raise FileNotFoundError(f"Interpretation draft is missing: {draft_path}")
        draft = read_json(draft_path)
        required = {"title", "executive_summary", "observations", "global_series_contrasts", "on_demand_candidates", "limitations"}
        missing = sorted(required - set(draft))
        if missing: raise ValueError(f"Interpretation draft is missing fields: {missing}")
        extra = sorted(set(draft) - required)
        if extra: raise ValueError(f"Interpretation draft has unsupported fields: {extra}")
        for field in ("title","executive_summary"):
            if not isinstance(draft[field],str) or not draft[field].strip(): raise ValueError(f"Interpretation {field} must be a non-empty string")
        for field in ("observations","global_series_contrasts","on_demand_candidates","limitations"):
            if not isinstance(draft[field],list) or any(not isinstance(item,str) or not item.strip() for item in draft[field]):
                raise ValueError(f"Interpretation {field} must be an array of non-empty strings")
            stripped = [item.strip() for item in draft[field]]
            if len(stripped) >= 3 and all(len(item) <= 2 for item in stripped):
                raise ValueError(
                    f"Interpretation {field} appears to be split into individual characters; "
                    "rewrite it as complete Japanese sentences"
                )
        markdown, page = render_interpretation(draft); directory = draft_path.parent
        md = directory / "interpretation.md"; html_path = directory / "interpretation.html"; canonical = directory / "interpretation.json"
        md.write_text(markdown, encoding="utf-8"); html_path.write_text(page, encoding="utf-8"); atomic_json(canonical, draft)
        node["status"] = "succeeded"; node["result"] = {
            "result_dir": str(directory),
            "primary_path": str(canonical), "primary_sha256": sha256(canonical),
            "markdown_path": str(md), "markdown_sha256": sha256(md),
            "html_path": str(html_path), "html_sha256": sha256(html_path),
        }; node["updated_at"] = now()
        save_state(root, control, dag, "INTERPRETATION_COMMITTED", {"node_id": node["node_id"]})
    return emit(root, control, dag, interpretation_html=str(html_path))


def audit_value(root: Path, control: dict[str, Any], dag: dict[str, Any], mode: str = "full") -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    def add(name: str, passed: bool, detail: str = "") -> None: checks.append({"name": name, "status": "PASS" if passed else "FAIL", "detail": detail})
    table = lookup(dag)
    def acyclic() -> bool:
        visiting: set[str] = set()
        complete: set[str] = set()
        def visit(node_id: str) -> bool:
            if node_id in complete:
                return True
            if node_id in visiting:
                return False
            visiting.add(node_id)
            node = table.get(node_id)
            if node is None or any(not visit(parent) for parent in node.get("dependencies", [])):
                return False
            visiting.remove(node_id)
            complete.add(node_id)
            return True
        return all(visit(node_id) for node_id in table)
    def primary_intact(node: dict[str, Any]) -> bool:
        result = node.get("result") or {}
        path = Path(str(result.get("primary_path", "")))
        return path.is_file() and bool(result.get("primary_sha256")) and sha256(path) == result["primary_sha256"]
    def description_contract_intact(node: dict[str, Any]) -> bool:
        if node.get("stage") != "description":
            return True
        result = node.get("result") or {}
        path = Path(str(result.get("description_result_path", "")))
        if not path.is_file() or sha256(path) != result.get("description_result_sha256"):
            return False
        try:
            contract = read_json(path)
            payload = (path.parent / str(contract["payload"])).resolve()
            return (
                contract.get("document_type") == "description_result"
                and contract.get("schema_version") == "1.0.0"
                and contract.get("node_id") == node["node_id"]
                and contract.get("capability_id") == node["capability_id"]
                and payload == Path(str(result["primary_path"])).resolve()
                and payload.is_file()
            )
        except (KeyError, OSError, ValueError, TypeError, json.JSONDecodeError):
            return False
    def event_artifacts_intact(node: dict[str, Any]) -> bool:
        if node.get("capability_id") == "I001":
            return True
        result = node.get("result") or {}
        directory = Path(str(result.get("result_dir", ""))).resolve()
        event_path = Path(str(result.get("execution_event", ""))).resolve()
        if (
            not directory.is_dir()
            or not event_path.is_file()
            or sha256(event_path) != result.get("execution_event_sha256")
        ):
            return False
        try:
            event = read_json(event_path)
            for key in ("round_id", "node_id", "capability_id", "skill_name"):
                if event.get(key) != node.get(key):
                    return False
            if event.get("project") != control.get("project") or event.get("run_id") != control.get("run_id"):
                return False
            succeeded_attempts = {
                item.get("attempt_id") for item in node.get("attempts", [])
                if item.get("status") == "succeeded"
            }
            if event.get("attempt_id") not in succeeded_attempts:
                return False
            artifacts = event.get("artifacts")
            if not isinstance(artifacts, list) or not artifacts:
                return False
            for item in artifacts:
                if not isinstance(item, dict) or not item.get("path") or not item.get("sha256"):
                    return False
                path = (directory / str(item["path"])).resolve()
                try:
                    path.relative_to(directory)
                except ValueError:
                    return False
                if not path.is_file() or sha256(path) != item["sha256"]:
                    return False
            return True
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return False
    def interpretation_contract_intact(node: dict[str, Any] | None) -> bool:
        if node is None:
            return False
        result = node.get("result") or {}
        checks = (
            ("primary_path", "primary_sha256"),
            ("markdown_path", "markdown_sha256"),
            ("html_path", "html_sha256"),
        )
        return all(
            Path(str(result.get(path_key, ""))).is_file()
            and sha256(Path(str(result[path_key]))) == result.get(hash_key)
            for path_key, hash_key in checks
        )
    def runtime_cluster_contract_intact() -> bool:
        try:
            import pandas as pd

            registry_path = root / "runtime" / "cluster_registry.csv"
            matrix_path = root / "runtime" / "cluster_membership" / "Cpd_Cluster_matrix_C000001_099999.csv"
            long_path = root / "runtime" / "cluster_membership_long.csv"
            if not all(path.is_file() for path in (registry_path, matrix_path, long_path)):
                return False
            registry = pd.read_csv(registry_path, dtype=str)
            matrix = pd.read_csv(matrix_path, dtype=str)
            long_frame = pd.read_csv(long_path, dtype=str)
            if not {"cluster_id", "sample_count"}.issubset(registry.columns):
                return False
            if not {"compound_id", "cluster_id", "membership_value"}.issubset(long_frame.columns):
                return False
            if "compound_id" not in matrix.columns:
                return False
            cluster_ids = registry["cluster_id"].dropna().astype(str).tolist()
            if len(cluster_ids) != len(set(cluster_ids)) or set(matrix.columns[1:]) != set(cluster_ids):
                return False
            input_frame = pd.read_csv(control["input_path"], dtype=str)
            input_ids = input_frame[control["columns"]["compound_id"]].astype(str).tolist()
            if matrix["compound_id"].astype(str).tolist() != input_ids:
                return False
            true_values = {"true", "1", "1.0", "yes"}
            false_values = {"false", "0", "0.0", "no"}
            for cluster_id in cluster_ids:
                values = matrix[cluster_id].astype(str).str.strip().str.lower()
                if not bool(values.isin(true_values | false_values).all()):
                    return False
                declared = pd.to_numeric(
                    registry.loc[registry["cluster_id"].astype(str).eq(cluster_id), "sample_count"],
                    errors="coerce",
                )
                if len(declared) != 1 or not math.isfinite(float(declared.iloc[0])):
                    return False
                matrix_members = set(matrix.loc[values.isin(true_values), "compound_id"].astype(str))
                long_members = set(
                    long_frame.loc[
                        long_frame["cluster_id"].astype(str).eq(cluster_id), "compound_id"
                    ].astype(str)
                )
                if len(matrix_members) != int(float(declared.iloc[0])) or matrix_members != long_members:
                    return False
            return set(long_frame["compound_id"].astype(str)).issubset(set(input_ids))
        except (KeyError, OSError, ValueError, TypeError):
            return False
    def runtime_series_contract_intact() -> bool:
        try:
            import pandas as pd

            unit_registry_path = root / "runtime" / "analysis_unit_registry.csv"
            membership_path = root / "runtime" / "analysis_unit_membership.csv"
            series_path = root / "runtime" / "series_registry.csv"
            relation_path = root / "runtime" / "series_cluster_membership.csv"
            if not all(path.is_file() for path in (unit_registry_path, membership_path, series_path, relation_path)):
                return False
            units = pd.read_csv(unit_registry_path, dtype=str)
            membership = pd.read_csv(membership_path, dtype=str)
            series = pd.read_csv(series_path, dtype=str)
            relations = pd.read_csv(relation_path, dtype=str)
            if not {"analysis_unit_id", "compound_count"}.issubset(units.columns):
                return False
            if not {"compound_id", "analysis_unit_id", "membership_value"}.issubset(membership.columns):
                return False
            unit_ids = units["analysis_unit_id"].dropna().astype(str).tolist()
            if len(unit_ids) != len(set(unit_ids)) or "GLOBAL" not in unit_ids:
                return False
            if set(membership["analysis_unit_id"].astype(str)) != set(unit_ids):
                return False
            active = membership["membership_value"].astype(str).str.strip().str.lower().isin({"true", "1", "1.0", "yes"})
            if not bool(active.all()):
                return False
            input_frame = pd.read_csv(control["input_path"], dtype=str)
            input_ids = set(input_frame[control["columns"]["compound_id"]].astype(str))
            global_ids = set(membership.loc[membership["analysis_unit_id"].astype(str).eq("GLOBAL"), "compound_id"].astype(str))
            if global_ids != input_ids or not set(membership["compound_id"].astype(str)).issubset(input_ids):
                return False
            declared_counts = pd.to_numeric(units.set_index("analysis_unit_id")["compound_count"], errors="coerce")
            actual_counts = membership.groupby("analysis_unit_id")["compound_id"].nunique()
            if any(
                unit_id not in declared_counts.index
                or not math.isfinite(float(declared_counts.loc[unit_id]))
                or int(float(declared_counts.loc[unit_id])) != int(actual_counts.loc[unit_id])
                for unit_id in actual_counts.index
            ):
                return False
            cluster_registry = pd.read_csv(root / "runtime" / "cluster_registry.csv", dtype=str)
            if len(relations) and (
                not {"series_id", "cluster_id"}.issubset(relations.columns)
                or not set(relations["series_id"].astype(str)).issubset(set(unit_ids))
                or not set(relations["cluster_id"].astype(str)).issubset(set(cluster_registry["cluster_id"].astype(str)))
            ):
                return False
            if len(series):
                if not {"series_id", "accepted"}.issubset(series.columns):
                    return False
                accepted = series["accepted"].astype(str).str.strip().str.lower().isin({"true", "1", "1.0", "yes"})
                if not set(series.loc[accepted, "series_id"].astype(str)).issubset(set(unit_ids)):
                    return False
            return True
        except (KeyError, OSError, ValueError, TypeError):
            return False
    add("version", control.get("conductor_version") == VERSION and dag.get("conductor_version") == VERSION)
    add("state_revision", control.get("revision") == dag.get("revision"), f"control={control.get('revision')}, dag={dag.get('revision')}")
    input_path = Path(str(control.get("input_path", "")))
    add("input_integrity", input_path.is_file() and sha256(input_path) == control.get("input_sha256"))
    add("node_states", all(node.get("status") in NODE_STATES for node in nodes(dag)))
    add("dependencies", all(all(parent in table for parent in node.get("dependencies", [])) for node in nodes(dag)))
    add("dag_acyclic", acyclic())
    if mode == "full":
        succeeded = [node for node in nodes(dag) if node["status"] == "succeeded"]
        add("succeeded_artifacts", all(primary_intact(node) for node in succeeded))
        add("event_artifacts", all(event_artifacts_intact(node) for node in succeeded))
        add("description_contracts", all(description_contract_intact(node) for node in succeeded))
        add("cluster_registry", runtime_cluster_contract_intact())
        add("series_registry", runtime_series_contract_intact())
        current_round = control.get("active_round_id")
        report_node = latest(dag, "A009", status="succeeded", round_id=current_round)
        report_dir = Path(str((report_node or {}).get("result", {}).get("result_dir", "")))
        add("standard_report", report_node is not None and (report_dir / "standard_summary.html").is_file())
        interpretation_node = latest(dag, "I001", status="succeeded", round_id=current_round)
        add("interpretation", interpretation_contract_intact(interpretation_node))
    return {"schema_version": "1.0.0", "conductor_version": VERSION, "mode": mode, "run_id": control["run_id"], "round_id": control.get("active_round_id"), "status": "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL", "checks": checks, "created_at": now()}


def cmd_audit(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    with writer_lock(root):
        control, dag = load_state(root)
        if args.register:
            if args.mode != "full":
                raise ValueError("Only a full audit can be registered")
            require_lease(control, args.lease_token)
        value = audit_value(root, control, dag, args.mode)
        # Microseconds avoid silently overwriting a prior audit when a human or
        # recovery flow requests two reports within the same second.
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"); directory = root / "state" / timestamp; directory.mkdir(parents=True, exist_ok=False)
        atomic_json(directory / "audit.json", value)
        lines = [f"# CONDUCTOR Audit {control.get('active_round_id')}", "", f"Status: **{value['status']}**", ""] + [f"- {item['status']}: {item['name']} {item['detail']}" for item in value["checks"]]
        (directory / "audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        if args.register:
            if value["status"] != "PASS": raise RuntimeError(f"Full audit failed: {directory / 'audit.json'}")
            control["audited_round_id"] = control["active_round_id"]
            save_state(root, control, dag, "AUDIT_REGISTERED", {"path": str(directory / "audit.json")})
    return emit(root, control, dag, audit=value, audit_dir=str(directory))


def cmd_complete_finalizing(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    with writer_lock(root):
        control, dag = load_state(root); require_lease(control, args.lease_token)
        if required_action(root, control, dag)["code"] != "COMPLETE_FINALIZING": raise ValueError("Runtime is not ready to finalize")
        control["round_status"] = "AWAITING_HUMAN_REVIEW"; control["lease"] = None
        save_state(root, control, dag, "ROUND_AWAITING_HUMAN_REVIEW", {"round_id": control["active_round_id"]})
    return emit(root, control, dag)


def cmd_accept_round(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root); require_control_key(root, args.control_key)
    with writer_lock(root):
        control, dag = load_state(root)
        if control["round_status"] != "AWAITING_HUMAN_REVIEW": raise ValueError("Only AWAITING_HUMAN_REVIEW can be accepted")
        round_id = control["active_round_id"]; control["round_status"] = "CLOSED"; control["lease"] = None
        save_state(root, control, dag, "ROUND_CLOSED", {"round_id": round_id, "note": args.note})
    return emit(root, control, dag)


def cmd_query(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root); control, dag = load_state(root)
    if args.node_id:
        node = lookup(dag).get(args.node_id)
        if not node: raise ValueError(f"Unknown Node: {args.node_id}")
        return emit(root, control, dag, node=node)
    return emit(root, control, dag)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CONDUCTOR 0.1.9 deterministic Runtime Controller")
    sub = parser.add_subparsers(dest="command", required=True)
    item = sub.add_parser("init"); item.add_argument("--input", required=True); item.add_argument("--id-column"); item.add_argument("--smiles-column"); item.add_argument("--endpoint", required=True); item.add_argument("--higher-is-better", action=argparse.BooleanOptionalAction, required=True); item.add_argument("--endpoint-unit"); item.add_argument("--project", required=True); item.add_argument("--parallel-limit", type=int, required=True); item.add_argument("--available-cpu-cores", type=int, default=DEFAULT_CPU_CORES); item.add_argument("--run-id"); item.add_argument("--output-dir"); item.set_defaults(function=cmd_init)
    item = sub.add_parser("prepare-round"); item.add_argument("--run-root", required=True); item.add_argument("--objective", required=True); item.add_argument("--walltime-minutes", type=int, default=480); item.add_argument("--parallel-limit", type=int); item.add_argument("--available-cpu-cores", type=int); item.add_argument("--min-ff-evaluate", type=int, default=10); item.add_argument("--leiden-resolution", type=float, default=1.0); item.add_argument("--approve-high-cost", action="store_true"); item.set_defaults(function=cmd_prepare_round)
    item = sub.add_parser("authorize-round"); item.add_argument("--run-root", required=True); item.add_argument("--control-key", required=True); item.add_argument("--authorization-token", required=True); item.set_defaults(function=cmd_authorize_round)
    item = sub.add_parser("resume-round"); item.add_argument("--run-root", required=True); item.add_argument("--control-key", required=True); item.add_argument("--owner-id", required=True); item.add_argument("--lease-minutes", type=int, default=DEFAULT_LEASE_MINUTES); item.add_argument("--confirm-interrupted-running", action="store_true", help="After human/operator confirmation, recover running Nodes whose originating host cannot be verified"); item.set_defaults(function=cmd_resume_round)
    item = sub.add_parser("release-lease"); item.add_argument("--run-root", required=True); item.add_argument("--lease-token", required=True); item.add_argument("--reason", required=True); item.set_defaults(function=cmd_release_lease)
    item = sub.add_parser("continue-round"); item.add_argument("--run-root", required=True); item.add_argument("--control-key", required=True); item.add_argument("--additional-walltime-minutes", type=int, required=True); item.add_argument("--reason", required=True); item.set_defaults(function=cmd_continue_round)
    item = sub.add_parser("approve-high-cost"); item.add_argument("--run-root", required=True); item.add_argument("--control-key", required=True); item.add_argument("--rationale", required=True); item.add_argument("--approve", action=argparse.BooleanOptionalAction, default=True); item.set_defaults(function=cmd_approve_high_cost)
    item = sub.add_parser("approve-series"); item.add_argument("--run-root", required=True); item.add_argument("--control-key", required=True); item.set_defaults(function=cmd_approve_series)
    item = sub.add_parser("revise-series"); item.add_argument("--run-root", required=True); item.add_argument("--lease-token", required=True); item.add_argument("--control-key", required=True); item.add_argument("--min-ff-evaluate", type=int, required=True); item.add_argument("--leiden-resolution", type=float, required=True); item.add_argument("--reason", required=True); item.set_defaults(function=cmd_revise_series)
    for name, function in (("plan-basic", cmd_plan_basic), ("plan-standard", cmd_plan_standard), ("prepare-execution-packet", cmd_prepare_execution_packet), ("prepare-interpretation", cmd_prepare_interpretation), ("complete-finalizing", cmd_complete_finalizing)):
        item = sub.add_parser(name); item.add_argument("--run-root", required=True); item.add_argument("--lease-token", required=True); item.set_defaults(function=function)
    item = sub.add_parser("execute-packet"); item.add_argument("--run-root", required=True); item.add_argument("--packet", required=True); item.set_defaults(function=cmd_execute_packet)
    item = sub.add_parser("retry-node"); item.add_argument("--run-root", required=True); item.add_argument("--lease-token", required=True); item.add_argument("--control-key", required=True); item.add_argument("--node-id", required=True); item.add_argument("--reason", required=True); item.set_defaults(function=cmd_retry_node)
    item = sub.add_parser("waive-node"); item.add_argument("--run-root", required=True); item.add_argument("--control-key", required=True); item.add_argument("--node-id", required=True); item.add_argument("--reason", required=True); item.set_defaults(function=cmd_waive_node)
    item = sub.add_parser("pause-round"); item.add_argument("--run-root", required=True); item.add_argument("--lease-token", required=True); item.add_argument("--reason", required=True); item.set_defaults(function=cmd_pause_round)
    item = sub.add_parser("commit-interpretation"); item.add_argument("--run-root", required=True); item.add_argument("--lease-token", required=True); item.add_argument("--node-id", required=True); item.add_argument("--draft"); item.set_defaults(function=cmd_commit_interpretation)
    item = sub.add_parser("audit"); item.add_argument("--run-root", required=True); item.add_argument("--mode", choices=["quick", "full"], default="full"); item.add_argument("--register", action="store_true"); item.add_argument("--lease-token"); item.set_defaults(function=cmd_audit)
    item = sub.add_parser("accept-round"); item.add_argument("--run-root", required=True); item.add_argument("--control-key", required=True); item.add_argument("--note", default=""); item.set_defaults(function=cmd_accept_round)
    item = sub.add_parser("query"); item.add_argument("--run-root", required=True); item.add_argument("--node-id"); item.set_defaults(function=cmd_query)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.function(args))
    except Exception as exc:
        print(json.dumps({"protocol_version": PROTOCOL_VERSION, "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
