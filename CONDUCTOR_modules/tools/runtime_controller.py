from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import importlib.util
import json
import os
import secrets
import signal
import shutil
import socket
import subprocess
import sys
import time
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator


VERSION = "0.1.5"
PROTOCOL_VERSION = "0.1.5"
CONTROL_SCHEMA = "3.0.0"
MAX_CONTROL_BYTES = 32 * 1024
MAX_WORKING_SET_BYTES = 64 * 1024
MAX_CANDIDATES = 20
MAX_COMPACT_RESPONSE_BYTES = 16 * 1024
EXECUTION_PACKET_TTL_MINUTES = 360
DEFAULT_LEASE_MINUTES = 360
DEFAULT_EXECUTION_TIMEOUT_MINUTES = 360
DEFAULT_AVAILABLE_CPU_CORES = 8
XTB_CORES_PER_COMPOUND = 4
MCS_MAX_WORKERS = 8
MORDRED_3D_MAX_WORKERS = 8
MMP_MAX_FRAGMENT_JOBS = 8
EXECUTION_LEASE_GRACE_MINUTES = 10
MAX_EXECUTION_ATTEMPTS = 3
MAX_INTERPRETER_ATTEMPTS = 3
RUNTIME_PYTHON_TOKEN = "<CONDUCTOR_RUNTIME_PYTHON>"
DIRECT_STRUCTURE_CLUSTERING = {"C001", "C002", "C003", "C004"}
DIRECT_STRUCTURE_ANALYSIS = {"A006", "A009", "A013"}
EXCLUSIVE_CPU_CAPABILITIES = {"C002", "D016", "D019", "D020"}
MMP_PAYLOAD_NAMES = {
    "mmp_database.sqlite", "mmp_pair_detail.csv", "mmp_storage_profile.json",
    "pair_summary.csv", "transform_summary.csv", "core_summary.csv", "transform_core_summary.csv",
    "context_summary.csv", "coverage_summary.csv", "compound_coverage.csv",
    "mmp_reference_cards.jsonl", "mmp_reference_cards.csv", "mmp_local_screening.csv",
    "mmp_local_detail_pairs.csv", "mmp_global_vs_local.csv", "mmp_query_result.json",
    "mmp_result.json",
}
ROUND_STATES = {"ACTIVE", "FINALIZING", "AWAITING_HUMAN_REVIEW", "CLOSED"}
NODE_STATES = {"pending", "running", "succeeded", "failed", "cancelled"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def parse_time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [clean(item) for item in value]
    if hasattr(value, "item"):
        try:
            return clean(value.item())
        except Exception:
            pass
    if isinstance(value, Path):
        return str(value)
    return value


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(clean(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def value_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _compact_response(
    control: dict[str, Any],
    *,
    detail_pointer: str | None = None,
    **payload: Any,
) -> dict[str, Any]:
    """Return the bounded protocol surface consumed by the Main Agent.

    Full Control remains available through the explicit read-only query command;
    mutation commands do not echo it into the conversation.
    """
    response: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "control_revision": int(control["revision"]),
        "run_id": control["run"]["run_id"],
        "round_id": control.get("active_round_id"),
        "round_state": control["round_state"],
        "required_action": clean(control["required_action"]),
        "counts": clean(control.get("counts") or {}),
        "closure": clean(control.get("closure") or {}),
        "working_set": control.get("pointers", {}).get("working_set"),
        "resources": {
            "parallel_limit": int(control["run"].get("parallel_limit", 1)),
            "available_cpu_cores": _available_cpu_cores(control),
        },
    }
    if detail_pointer is not None:
        response["detail_pointer"] = detail_pointer
    response.update(clean(payload))
    validate(response, "compact_runtime_response.schema.json")
    if len(canonical_bytes(response)) > MAX_COMPACT_RESPONSE_BYTES:
        # Payloads must opt into a file pointer rather than silently truncating
        # scientific identifiers or failure information.
        raise ValueError("Compact Runtime response exceeds 16 KiB; store details and return a pointer")
    return response


def _print_compact(control: dict[str, Any], **payload: Any) -> None:
    print(json.dumps(_compact_response(control, **payload), ensure_ascii=False, indent=2))


def _available_cpu_cores(control: dict[str, Any]) -> int:
    """Return the human-declared CPU allocation, including legacy Run fallback."""
    value = int(control.get("run", {}).get("available_cpu_cores", DEFAULT_AVAILABLE_CPU_CORES))
    if value < 1:
        raise ValueError("available_cpu_cores must be at least one")
    return value


def _execution_capacity(control: dict[str, Any]) -> int:
    """Bound concurrent Node processes independently by Node and CPU budgets."""
    return min(int(control["run"]["parallel_limit"]), _available_cpu_cores(control))


def _requires_exclusive_cpu(node: dict[str, Any]) -> bool:
    return node["capability_id"] in EXCLUSIVE_CPU_CAPABILITIES or (
        node["capability_id"] == "A014" and node.get("parameters", {}).get("role") == "global-build"
    )


def _select_execution_nodes(
    requested: list[str],
    runnable: dict[str, dict[str, Any]],
    control: dict[str, Any],
) -> list[str]:
    """Select a deterministic batch while keeping internally parallel CPU Nodes exclusive."""
    selected: list[str] = []
    for node_id in requested:
        node = runnable[node_id]
        if _requires_exclusive_cpu(node):
            if not selected:
                return [node_id]
            break
        selected.append(node_id)
        if len(selected) >= _execution_capacity(control):
            break
    return selected


def _node_cpu_allocation(control: dict[str, Any], node: dict[str, Any]) -> int:
    if node["capability_id"] == "C002":
        return min(MCS_MAX_WORKERS, _available_cpu_cores(control))
    if node["capability_id"] == "D016":
        return min(MORDRED_3D_MAX_WORKERS, _available_cpu_cores(control))
    if node["capability_id"] == "A014" and node.get("parameters", {}).get("role") == "global-build":
        return min(MMP_MAX_FRAGMENT_JOBS, _available_cpu_cores(control))
    if _requires_exclusive_cpu(node):
        return _available_cpu_cores(control)
    return 1


def _native_thread_limit(control: dict[str, Any], node: dict[str, Any]) -> int:
    """Limit the initial native thread pools without changing the Node CPU budget."""
    if node["capability_id"] in {"C002", "D016"}:
        return 1
    if node["capability_id"] == "A014" and node.get("parameters", {}).get("role") == "global-build":
        return 1
    if node["capability_id"] == "D019":
        return min(XTB_CORES_PER_COMPOUND, _available_cpu_cores(control))
    return _node_cpu_allocation(control, node)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL record {path}:{number}") from exc
    return rows


def atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def write_json(path: Path, value: Any) -> None:
    atomic_bytes(path, json.dumps(clean(value), ensure_ascii=False, indent=2, default=str).encode("utf-8") + b"\n")


def append_jsonl_fsync(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(canonical_bytes(row) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())


def write_csv(path: Path, fields: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fields})
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def project_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in [here.parent, *here.parents, Path.cwd(), *Path.cwd().parents]:
        if (candidate / "CONDUCTOR_modules" / "catalog" / "catalog.json").is_file() and (candidate / ".claude" / "skills").is_dir():
            return candidate
    raise FileNotFoundError("CONDUCTOR Project root could not be located")


def module_root() -> Path:
    return project_root() / "CONDUCTOR_modules"


@lru_cache(maxsize=1)
def _local_schema_registry() -> tuple[dict[str, dict[str, Any]], Any]:
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    schema_dir = module_root() / "schemas"
    schemas: dict[str, dict[str, Any]] = {}
    resources: list[tuple[str, Resource[Any]]] = []
    registered_ids: set[str] = set()
    for path in sorted(schema_dir.glob("*.schema.json")):
        schema = read_json(path)
        schema_id = schema.get("$id")
        if not isinstance(schema_id, str) or not schema_id:
            raise ValueError(f"Bundled Schema has no $id: {path.name}")
        if schema_id in registered_ids:
            raise ValueError(f"Duplicate bundled Schema $id: {schema_id}")
        registered_ids.add(schema_id)
        schemas[path.name] = schema
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        resources.extend(((schema_id, resource), (path.resolve().as_uri(), resource)))
    return schemas, Registry().with_resources(resources)


def validate(instance: dict[str, Any], schema_name: str) -> None:
    import jsonschema

    schemas, registry = _local_schema_registry()
    if schema_name not in schemas:
        raise FileNotFoundError(f"Bundled Schema is not registered: {schema_name}")
    schema = schemas[schema_name]
    validator_class = jsonschema.validators.validator_for(schema)
    validator_class.check_schema(schema)
    validator_class(
        schema,
        registry=registry,
        format_checker=jsonschema.FormatChecker(),
    ).validate(instance)


def catalog() -> dict[str, dict[str, Any]]:
    data = read_json(module_root() / "catalog" / "catalog.json")
    return {item["capability_id"]: item for item in data["capabilities"]}


def profile() -> dict[str, Any]:
    return read_json(module_root() / "catalog" / "analysis_profile.json")


def resolve_root(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()
    if path.name == "conductor_control.json":
        path = path.parent
    if not (path / "conductor_control.json").is_file():
        raise FileNotFoundError(f"CONDUCTOR control file not found: {path / 'conductor_control.json'}")
    return path


def _run_relative_artifact(root: Path, path: Path, *, require_file: bool = False) -> str:
    """Return one canonical Run-root-relative artifact path."""
    resolved_root = root.resolve()
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise PermissionError(f"Artifact escapes the Run Root: {resolved}") from exc
    if require_file and not resolved.is_file():
        raise FileNotFoundError(f"Result Card artifact does not exist: {resolved}")
    return relative.as_posix()


def _validate_result_card_links(root: Path, card: dict[str, Any]) -> None:
    for name, value in (card.get("artifact_links") or {}).items():
        if value is None:
            continue
        if Path(str(value)).is_absolute():
            raise PermissionError(f"Result Card link must be Run-root-relative ({name}): {value}")
        canonical = _run_relative_artifact(root, root / str(value), require_file=True)
        if canonical != Path(str(value)).as_posix():
            raise PermissionError(f"Result Card link is not canonical ({name}): {value}")


def control_path(root: Path) -> Path:
    return root / "conductor_control.json"


def snapshot_path(root: Path) -> Path:
    return root / "runtime" / "dag_snapshot.json"


def ledger_path(root: Path) -> Path:
    return root / "runtime" / "event_ledger.jsonl"


@contextmanager
def writer_lock(root: Path, timeout: float = 30.0) -> Iterator[None]:
    lock_dir = root / "runtime" / ".writer.lock"
    started = time.monotonic()
    while True:
        try:
            lock_dir.mkdir(parents=False)
            (lock_dir / "owner.json").write_text(json.dumps({"pid": os.getpid(), "host": socket.gethostname(), "created_at": utc_now()}), encoding="utf-8")
            break
        except FileExistsError:
            # A hard-killed Runtime process cannot clean up its directory. Recover only
            # when the recorded process is certainly gone; never steal a live lock.
            owner_path = lock_dir / "owner.json"
            try:
                owner = read_json(owner_path)
                owner_pid = int(owner.get("pid", -1))
                owner_host = owner.get("host")
                same_host = not owner_host or owner_host == socket.gethostname()
                created_at = parse_time(owner.get("created_at"))
                cross_host_stale = bool(not same_host and created_at and datetime.now(timezone.utc) - created_at > timedelta(minutes=5))
                if (same_host and not pid_alive(owner_pid)) or cross_host_stale:
                    shutil.rmtree(lock_dir, ignore_errors=True)
                    continue
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                # An owner file can be observed between mkdir and atomic content
                # creation. Let the normal timeout protect that short race.
                pass
            if time.monotonic() - started > timeout:
                raise TimeoutError(f"Runtime writer lock is held: {lock_dir}")
            time.sleep(0.05)
    try:
        yield
    finally:
        shutil.rmtree(lock_dir, ignore_errors=True)


def _event(sequence: int, revision: int, previous: str | None, event_type: str, round_id: str | None, node_id: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    value = {
        "schema_version": "1.0.0",
        "sequence": sequence,
        "event_id": f"EVT{sequence:08d}",
        "event_type": event_type,
        "control_revision": revision,
        "round_id": round_id,
        "node_id": node_id,
        "payload": clean(payload),
        "previous_checksum": previous,
        "created_at": utc_now(),
    }
    value["checksum"] = value_hash(value)
    validate(value, "runtime_event.schema.json")
    return value


def _read_state(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    return read_json(control_path(root)), read_json(snapshot_path(root))


def _validate_snapshot(snapshot: dict[str, Any]) -> None:
    ids = [node["node_id"] for node in snapshot["nodes"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate Node IDs in DAG snapshot")
    lookup = set(ids)
    for node in snapshot["nodes"]:
        validate(node, "node_record.schema.json")
        if node["status"] not in NODE_STATES:
            raise ValueError(f"Invalid Node status: {node['status']}")
        missing = set(node["input_nodes"]) - lookup
        if missing:
            raise ValueError(f"Node {node['node_id']} has missing inputs: {sorted(missing)}")
    graph = {node["node_id"]: node["input_nodes"] for node in snapshot["nodes"]}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            raise ValueError("DAG cycle detected")
        if node_id in visited:
            return
        visiting.add(node_id)
        for dependency in graph[node_id]:
            visit(dependency)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in graph:
        visit(node_id)


def _verify_ledger(root: Path, tolerate_truncated_tail: bool = False) -> tuple[int, str | None]:
    path = ledger_path(root)
    if not path.is_file():
        return 0, None
    previous: str | None = None
    sequence = 0
    raw = path.read_bytes()
    lines = raw.splitlines()
    for index, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            if tolerate_truncated_tail and index == len(lines):
                break
            raise ValueError(f"Invalid Event Ledger record at line {index}")
        checksum = event.pop("checksum", None)
        if event.get("sequence") != sequence + 1 or event.get("previous_checksum") != previous or value_hash(event) != checksum:
            raise ValueError(f"Event Ledger chain failure at line {index}")
        event["checksum"] = checksum
        validate(event, "runtime_event.schema.json")
        sequence = event["sequence"]
        previous = checksum
    return sequence, previous


def _recover_transaction(root: Path) -> list[str]:
    transaction_path = root / "runtime" / "pending_transaction.json"
    if not transaction_path.is_file():
        return []
    transaction = read_json(transaction_path)
    event = transaction["event"]
    ledger = ledger_path(root)
    if ledger.is_file():
        raw = ledger.read_bytes()
        if raw and not raw.endswith(b"\n"):
            last_complete = raw.rfind(b"\n")
            atomic_bytes(ledger, raw[: last_complete + 1] if last_complete >= 0 else b"")
    sequence, checksum = _verify_ledger(root, tolerate_truncated_tail=True)
    if sequence == event["sequence"] - 1 and checksum == event["previous_checksum"]:
        append_jsonl_fsync(ledger_path(root), event)
    elif sequence != event["sequence"] or checksum != event["checksum"]:
        raise ValueError("Pending transaction does not match Event Ledger")
    write_json(snapshot_path(root), transaction["snapshot"])
    write_json(control_path(root), transaction["control"])
    transaction_path.unlink()
    return [event["event_id"]]


def _commit(root: Path, control: dict[str, Any], snapshot: dict[str, Any], event_type: str, payload: dict[str, Any], *, round_id: str | None = None, node_id: str | None = None) -> None:
    _validate_snapshot(snapshot)
    next_revision = int(control["revision"]) + 1
    next_sequence = int(control["last_event_sequence"]) + 1
    event = _event(next_sequence, next_revision, control.get("last_event_checksum"), event_type, round_id, node_id, payload)
    control["revision"] = next_revision
    control["last_event_sequence"] = next_sequence
    control["last_event_checksum"] = event["checksum"]
    control["updated_at"] = utc_now()
    snapshot["control_revision"] = next_revision
    snapshot["last_event_sequence"] = next_sequence
    _refresh_control(root, control, snapshot)
    validate(control, "conductor_control.schema.json")
    if len(canonical_bytes(control)) > MAX_CONTROL_BYTES:
        raise ValueError("conductor_control.json exceeds 32 KiB")
    transaction = {"schema_version": "1.0.0", "event": event, "control": control, "snapshot": snapshot, "created_at": utc_now()}
    pending = root / "runtime" / "pending_transaction.json"
    write_json(pending, transaction)
    append_jsonl_fsync(ledger_path(root), event)
    write_json(snapshot_path(root), snapshot)
    write_json(control_path(root), control)
    pending.unlink()
    return None


def _node_lookup(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {node["node_id"]: node for node in snapshot["nodes"]}


def _active_contract(root: Path, control: dict[str, Any]) -> dict[str, Any] | None:
    round_id = control.get("active_round_id")
    path = root / "rounds" / str(round_id) / "round_contract.json" if round_id else None
    return read_json(path) if path and path.is_file() else None


def _lease_live(control: dict[str, Any]) -> bool:
    expires = parse_time(control["lease"].get("expires_at"))
    return bool(control["lease"].get("owner_id") and expires and expires > datetime.now(timezone.utc))


def _require_control_authority(root: Path, key: str) -> None:
    authority = read_json(root / "runtime" / "authority.json")
    if not secrets.compare_digest(authority["control_authority_key_hash"], value_hash(key)):
        raise PermissionError("Human-authorized Main control authority is required")


def _require_action(control: dict[str, Any], lease_token: str, allowed_actions: set[str] | None = None) -> None:
    if not _lease_live(control):
        raise PermissionError("No live Orchestrator lease")
    if not secrets.compare_digest(str(control["lease"].get("token_hash")), value_hash(lease_token)):
        raise PermissionError("Invalid Orchestrator lease token")
    if allowed_actions and control["required_action"]["code"] not in allowed_actions:
        raise PermissionError(f"Action is not allowed while required_action={control['required_action']['code']}")


def _packet_signature(root: Path, packet: dict[str, Any]) -> str:
    key = (root / "runtime" / "control_authority.key").read_text(encoding="utf-8").strip().encode("utf-8")
    unsigned = {name: value for name, value in packet.items() if name != "signature"}
    return hmac.new(key, canonical_bytes(unsigned), hashlib.sha256).hexdigest()


def _validate_execution_packet(
    root: Path,
    control: dict[str, Any],
    packet_path: Path,
) -> dict[str, Any]:
    packet_path = packet_path.resolve()
    packet_root = (root / "runtime" / "scratch" / "packets").resolve()
    if packet_root not in packet_path.parents:
        raise PermissionError("Execution packet is outside the Runtime packet directory")
    packet = read_json(packet_path)
    validate(packet, "execution_packet.schema.json")
    if not hmac.compare_digest(packet["signature"], _packet_signature(root, packet)):
        raise PermissionError("Execution packet signature is invalid")
    if packet["run_id"] != control["run"]["run_id"] or packet["round_id"] != control.get("active_round_id"):
        raise PermissionError("Execution packet belongs to another Run or Round")
    if int(packet["control_revision"]) != int(control["revision"]):
        raise PermissionError("Execution packet is stale")
    if packet["required_action"] != control["required_action"]["code"]:
        raise PermissionError("Execution packet action no longer matches Runtime Control")
    if not secrets.compare_digest(packet["lease_token_hash"], str(control["lease"].get("token_hash"))):
        raise PermissionError("Execution packet lease is stale")
    if not _lease_live(control):
        raise PermissionError("Execution packet has no live Main Agent lease")
    expires = parse_time(packet.get("expires_at"))
    if not expires or expires <= datetime.now(timezone.utc):
        raise PermissionError("Execution packet has expired")
    return packet


def _require_executor_followup(control: dict[str, Any], packet: dict[str, Any]) -> None:
    if not _lease_live(control):
        raise PermissionError("Main Agent lease expired while Executor was active")
    if not secrets.compare_digest(packet["lease_token_hash"], str(control["lease"].get("token_hash"))):
        raise PermissionError("Main Agent lease changed while Executor was active")
    if control["required_action"]["code"] != "WAIT_OR_RECONCILE_RUNNING":
        raise PermissionError("Runtime is not waiting for the claimed Executor batch")


def cmd_prepare_execution_packet(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        _require_action(control, args.lease_token, {"EXECUTE_RUNNABLE_BATCH"})
        runnable = {node["node_id"]: node for node in _runnable(control, snapshot)}
        requested = [item for item in (args.node_ids or "").split(",") if item] or list(runnable)
        if not requested:
            raise ValueError("No runnable Nodes")
        if set(requested) - set(runnable):
            raise ValueError(f"Requested Nodes are not currently runnable: {sorted(set(requested) - set(runnable))}")
        requested = _select_execution_nodes(requested, runnable, control)
        packet_id = f"PKT{timestamp()}_{secrets.token_hex(4)}"
        packet_dir = root / "runtime" / "scratch" / "packets" / packet_id
        packet_dir.mkdir(parents=True, exist_ok=False)
        execution_contracts: list[dict[str, Any]] = []
        for node_id in requested:
            node = runnable[node_id]
            attempt_id = f"ATT{len(node['attempts']) + 1:04d}"
            scratch = root / "runtime" / "scratch" / node["assigned_round"] / node_id / attempt_id
            skill_output = _skill_output_dir(scratch)
            command = _skill_command(root, control, snapshot, node, attempt_id, scratch)
            request_path = scratch / "execution_request.json"
            execution_contracts.append({
                "node_id": node_id,
                "capability_id": node["capability_id"],
                "attempt_id": attempt_id,
                "node_signature": node["signature"],
                "input_nodes": node["input_nodes"],
                "request_path": str(request_path.resolve()),
                "request_hash": value_hash(read_json(request_path)),
                "command_argv": command,
                "command_hash": value_hash(command),
                "working_directory": str(project_root()),
                "scratch": str(scratch),
                "skill_output": str(skill_output),
                "environment": {
                    "CONDUCTOR_ATTEMPT_TMP": str(scratch / "tmp"),
                    "CONDUCTOR_AVAILABLE_CPU_CORES": str(_available_cpu_cores(control)),
                    "CONDUCTOR_NODE_CPU_CORES": str(_node_cpu_allocation(control, node)),
                    "CONDUCTOR_NATIVE_THREAD_LIMIT": str(_native_thread_limit(control, node)),
                },
                "expected_output_ref": node["output_ref"],
                "validation": ["execution_event_identity", "artifact_sha256", "stage_schema", "analysis_subject", "scientific_invariants"],
            })
        packet = {
            "schema_version": "1.0.0",
            "protocol_version": PROTOCOL_VERSION,
            "packet_id": packet_id,
            "run_id": control["run"]["run_id"],
            "round_id": control["active_round_id"],
            "control_revision": control["revision"],
            "required_action": control["required_action"]["code"],
            "lease_token_hash": control["lease"]["token_hash"],
            "node_ids": requested,
            "capability_ids": [runnable[node_id]["capability_id"] for node_id in requested],
            "execution_contracts": execution_contracts,
            "timeout_minutes": args.timeout_minutes,
            "clean_scratch": bool(args.clean_scratch),
            "created_at": utc_now(),
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=EXECUTION_PACKET_TTL_MINUTES)).isoformat(),
        }
        packet["signature"] = _packet_signature(root, packet)
        validate(packet, "execution_packet.schema.json")
        packet_path = packet_dir / "execution_packet.json"
        write_json(packet_path, packet)
    _print_compact(
        control,
        packet_path=str(packet_path),
        packet_id=packet_id,
        node_ids=requested,
        executor_agent="cs-conductor-executor",
    )
    return 0


def _execution_round(node: dict[str, Any]) -> str | None:
    return node.get("assigned_round")


def _runnable(control: dict[str, Any], snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    if control["round_state"] != "ACTIVE":
        return []
    lookup = _node_lookup(snapshot)
    running_count = sum(node["status"] == "running" for node in snapshot["nodes"])
    capacity = max(0, _execution_capacity(control) - running_count)
    active = control["active_round_id"]
    contract = None
    try:
        contract = _active_contract(Path(control["run"]["run_root"]), control)
    except Exception:
        pass
    high_approved = bool(contract and contract.get("high_cost_bundle_approved"))
    high_cost = set(profile()["basic_compute"].get("high_cost_bundle", []))
    values = []
    for node in snapshot["nodes"]:
        if node["status"] != "pending" or node.get("assigned_round") != active:
            continue
        if node["capability_id"] in high_cost and not high_approved:
            continue
        if all(
            lookup[item]["status"] == "succeeded"
            and (lookup[item].get("result_quality") or {}).get("eligible_for_downstream", True)
            for item in node["input_nodes"]
        ):
            values.append(node)
    wave_order = {"basic_compute": 0, "exploration": 1, "deep_dive": 2, "human_directed": 3, "round_commit": 4}
    return sorted(values, key=lambda node: (wave_order[node["wave"]], node["node_id"]))[:capacity]


def _round_nodes(snapshot: dict[str, Any], round_id: str | None) -> list[dict[str, Any]]:
    reused = set(snapshot.get("rounds", {}).get(str(round_id), {}).get("reused_node_ids") or [])
    return [node for node in snapshot["nodes"] if node.get("created_in_round") == round_id or node.get("assigned_round") == round_id or node["node_id"] in reused]


def _interpretation_fresh(snapshot: dict[str, Any], round_id: str) -> tuple[bool, str | None]:
    record = snapshot.get("rounds", {}).get(round_id, {})
    if record.get("interpretation_revision_required"):
        return False, None
    round_node_ids = {node["node_id"] for node in _round_nodes(snapshot, round_id)}
    analyses = [node for node in snapshot["nodes"] if node["kind"] == "analysis" and node["status"] == "succeeded" and node["node_id"] in round_node_ids]
    interpretations = [node for node in snapshot["nodes"] if node["kind"] == "interpretation" and node["status"] == "succeeded" and node.get("assigned_round") == round_id]
    if not interpretations:
        return False, None
    latest = max(interpretations, key=lambda node: node.get("finished_at") or "")
    latest_time = parse_time(latest.get("finished_at"))
    newest_analysis = max((parse_time(node.get("finished_at")) for node in analyses), default=None)
    required = all((Path(latest["output_ref"]) / name).is_file() for name in ("interpretation.json", "interpretation.md", "interpretation.html"))
    return bool(required and latest_time and (not newest_analysis or latest_time >= newest_analysis)), latest["node_id"]


def _round_time(root: Path, control: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    round_id = control.get("active_round_id")
    record = snapshot.get("rounds", {}).get(str(round_id), {})
    deadline = parse_time(record.get("deadline_at"))
    soft = parse_time(record.get("soft_stop_at"))
    now = datetime.now(timezone.utc)
    return {
        "deadline_at": record.get("deadline_at"),
        "soft_stop_at": record.get("soft_stop_at"),
        "remaining_minutes": max(0.0, round((deadline - now).total_seconds() / 60, 2)) if deadline else 0.0,
        "soft_stop_reached": bool(soft and now >= soft),
        "deadline_reached": bool(deadline and now >= deadline),
    }


def _deliverable_status(root: Path, control: dict[str, Any], snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    contract = _active_contract(root, control)
    if not contract:
        return []
    result: list[dict[str, Any]] = []
    nodes = _round_nodes(snapshot, control["active_round_id"])
    for item in contract["required_deliverables"]:
        kind = item["type"]
        parameters = item.get("parameters") or {}
        satisfied = False
        evidence: list[str] = []
        if kind == "interpretation_completed":
            satisfied, node_id = _interpretation_fresh(snapshot, control["active_round_id"])
            evidence = [node_id] if node_id else []
        elif kind == "artifact_exists":
            relative = parameters.get("path")
            satisfied = bool(relative and (root / relative).is_file())
            evidence = [relative] if satisfied else []
        elif kind == "capability_coverage":
            required_ids = set(parameters.get("capability_ids") or [])
            required_scopes = set(parameters.get("scope_modes") or [])
            succeeded_ids = {
                node["capability_id"]
                for node in nodes
                if node["status"] == "succeeded"
                and (node.get("result_quality") or {}).get("eligible_for_downstream", True)
                and (not required_scopes or node.get("scope", {}).get("mode") in required_scopes)
            }
            satisfied = required_ids <= succeeded_ids
            evidence = sorted(required_ids & succeeded_ids)
        elif kind == "planned_node_coverage":
            plan_key = str(parameters.get("plan_key") or "")
            plan = snapshot.get("plans", {}).get(control["active_round_id"], {})
            required_nodes = list(plan.get(f"{plan_key}_node_ids") or [])
            lookup = _node_lookup(snapshot)
            completed_nodes = [
                node_id for node_id in required_nodes
                if node_id in lookup
                and lookup[node_id]["status"] == "succeeded"
                and (lookup[node_id].get("result_quality") or {}).get("eligible_for_downstream", True)
            ]
            satisfied = bool(required_nodes) and len(completed_nodes) == len(required_nodes)
            evidence = completed_nodes
        elif kind == "comparison_completed":
            required_scopes = set(parameters.get("scope_modes") or [])
            cards = read_jsonl(root / "runtime" / "result_index.jsonl")
            round_node_ids = {node["node_id"] for node in nodes}
            lookup = _node_lookup(snapshot)
            actual = {
                card.get("analysis_subject", {}).get("scope_mode")
                for card in cards
                if (card.get("round_id") == control["active_round_id"] or card.get("node_id") in round_node_ids)
                and (lookup.get(card.get("node_id"), {}).get("result_quality") or {}).get("eligible_for_downstream", True)
            }
            satisfied = required_scopes <= actual
            evidence = sorted(required_scopes & actual)
        elif kind == "scientific_objective":
            satisfied = False
        result.append({**item, "satisfied": satisfied, "evidence": evidence})
    return result


def _has_high_cost_waiting(root: Path, control: dict[str, Any], snapshot: dict[str, Any]) -> bool:
    contract = _active_contract(root, control)
    if not contract or contract.get("high_cost_bundle_approved"):
        return False
    high = set(profile()["basic_compute"].get("high_cost_bundle", []))
    return any(node["status"] == "pending" and node["capability_id"] in high and node.get("assigned_round") == control["active_round_id"] for node in snapshot["nodes"])


def _latest_failure_packet(root: Path, node: dict[str, Any]) -> dict[str, Any] | None:
    for attempt in reversed(node.get("attempts") or []):
        relative = attempt.get("failure_packet")
        if not relative:
            continue
        path = root / str(relative)
        if not path.is_file():
            return None
        try:
            packet = read_json(path)
            validate(packet, "failure_packet.schema.json")
            return packet
        except Exception:
            return None
    return None


def _finalize_allowed(root: Path, control: dict[str, Any], snapshot: dict[str, Any]) -> tuple[bool, str]:
    round_id = control.get("active_round_id")
    record = snapshot.get("rounds", {}).get(str(round_id), {})
    if record.get("human_checkpoint_requested"):
        return True, "human_checkpoint"
    timing = _round_time(root, control, snapshot)
    if timing["soft_stop_reached"]:
        return True, "budget_exhausted"
    maximum_analysis_nodes, _batch_size = _analysis_planning_limits()
    if _round_analysis_work_count(snapshot, round_id) >= maximum_analysis_nodes:
        return True, "analysis_node_budget_exhausted"
    if record.get("finish_reason") in {"no_eligible_work", "contract_satisfied", "analysis_node_budget_exhausted"}:
        return True, record["finish_reason"]
    deliverables = _deliverable_status(root, control, snapshot)
    if deliverables and all(item["satisfied"] or item.get("human_acceptance_required") for item in deliverables if item["type"] != "interpretation_completed"):
        if record.get("scientific_finish_requested"):
            return True, "contract_satisfied"
    return False, "eligible work or unfulfilled contract remains"


def _required_action(root: Path, control: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    round_id = control.get("active_round_id")
    if not round_id:
        return {"code": "AWAIT_HUMAN_ROUND", "reason": "No active Round. Only a human-authorized Main Orchestrator operation can start one."}
    if control["round_state"] == "AWAITING_HUMAN_REVIEW":
        return {"code": "HUMAN_REVIEW_REQUIRED", "reason": "Interpretation and audit are ready. Human continuation, report revision, or acceptance is required."}
    if control["round_state"] == "CLOSED":
        return {"code": "AWAIT_HUMAN_ROUND", "reason": "The previous Round is closed. A new Round requires explicit human authorization."}
    running = [node["node_id"] for node in snapshot["nodes"] if node["status"] == "running"]
    if running:
        return {"code": "WAIT_OR_RECONCILE_RUNNING", "reason": "Running Attempts must be reconciled before another control action.", "node_ids": running[:20]}
    if control["round_state"] == "FINALIZING":
        if (control.get("blocker") or {}).get("code") == "INTERPRETATION_RETRY_EXHAUSTED":
            return {"code": "INTERPRETATION_BLOCKED", "reason": "The bounded Interpreter retry budget is exhausted. Human correction or report-revision authorization is required.", "node_id": control["blocker"].get("node_id")}
        fresh, interpretation_node = _interpretation_fresh(snapshot, round_id)
        if not fresh:
            existing = [node for node in snapshot["nodes"] if node["kind"] == "interpretation" and node.get("assigned_round") == round_id and node["status"] in {"pending", "failed"}]
            if existing:
                return {"code": "WRITE_INTERPRETATION", "reason": "A current Interpretation is mandatory before Round handoff.", "node_id": existing[-1]["node_id"]}
            return {"code": "PLAN_INTERPRETATION", "reason": "Create the Round commit Interpretation Node."}
        audit = snapshot.get("rounds", {}).get(round_id, {}).get("latest_audit")
        if not audit or audit.get("status") != "pass" or audit.get("after_interpretation_node") != interpretation_node:
            return {"code": "RUN_FULL_AUDIT", "reason": "A passing Full Audit newer than the final Interpretation is required."}
        return {"code": "COMPLETE_FINALIZING", "reason": "Interpretation and Full Audit satisfy the Round handoff gate."}
    stop_allowed, stop_reason = _finalize_allowed(root, control, snapshot)
    if stop_allowed and stop_reason in {"human_checkpoint", "budget_exhausted"}:
        return {"code": "ENTER_FINALIZING", "reason": stop_reason}
    plans = snapshot.get("plans", {}).get(round_id, {})
    if not plans.get("basic_compute"):
        return {"code": "PLAN_BASIC", "reason": "Basic calculation must be planned before exploration."}
    runnable = _runnable(control, snapshot)
    if runnable:
        return {"code": "EXECUTE_RUNNABLE_BATCH", "reason": "Validated Nodes are ready.", "node_ids": [node["node_id"] for node in runnable]}
    failed_nodes = [
        node for node in snapshot["nodes"]
        if node["status"] == "failed" and node.get("assigned_round") == round_id
    ]
    retryable = [
        node for node in failed_nodes
        if len(node.get("attempts") or []) < MAX_EXECUTION_ATTEMPTS
        and bool((_latest_failure_packet(root, node) or {}).get("recoverable"))
    ]
    if retryable:
        retryable.sort(key=lambda node: node["node_id"])
        return {
            "code": "RETRY_FAILED_NODE",
            "reason": "A failed scientific Node has a bounded same-Node retry available. Retry never creates a replacement Node.",
            "node_id": retryable[0]["node_id"],
        }
    if failed_nodes:
        failed_nodes.sort(key=lambda node: node["node_id"])
        blocked = failed_nodes[0]
        packet = _latest_failure_packet(root, blocked) or {}
        return {
            "code": "FAILED_NODE_REPAIR_REQUIRED",
            "reason": "A deterministic failure or exhausted retry requires human repair before same-Node retry or Round finalization.",
            "node_id": blocked["node_id"],
            "classification": packet.get("classification", "unknown_failure"),
            "failure_pointer": next((item.get("failure_packet") for item in reversed(blocked.get("attempts") or []) if item.get("failure_packet")), None),
        }
    if _has_high_cost_waiting(root, control, snapshot):
        return {"code": "HUMAN_APPROVAL_REQUIRED", "reason": "The one-time high-cost Description bundle needs explicit human approval."}
    if not plans.get("exploration"):
        return {"code": "PLAN_EXPLORATION", "reason": "Plan one bounded Global-first exploration set for this Round."}
    runnable = _runnable(control, snapshot)
    if runnable:
        return {"code": "EXECUTE_RUNNABLE_BATCH", "reason": "Exploration Nodes are ready.", "node_ids": [node["node_id"] for node in runnable]}
    allowed, reason = _finalize_allowed(root, control, snapshot)
    if allowed:
        return {"code": "ENTER_FINALIZING", "reason": reason}
    return {"code": "SCIENTIFIC_DECISION", "reason": "Select an evidence-led follow-up from the bounded Working Set, or finalize this Round."}


def _refresh_control(root: Path, control: dict[str, Any], snapshot: dict[str, Any]) -> None:
    counts = Counter(node["status"] for node in snapshot["nodes"])
    counts.update({f"kind_{kind}": sum(node["kind"] == kind for node in snapshot["nodes"]) for kind in ("description", "clustering", "analysis", "interpretation")})
    maximum_analysis_nodes, batch_size = _analysis_planning_limits()
    counts.update({
        "round_analysis_nodes": _round_analysis_work_count(snapshot, control.get("active_round_id")),
        "round_analysis_node_limit": maximum_analysis_nodes,
    })
    control["counts"] = dict(sorted(counts.items()))
    deliverables = _deliverable_status(root, control, snapshot) if control.get("active_round_id") else []
    fresh, interpretation_node = _interpretation_fresh(snapshot, control["active_round_id"]) if control.get("active_round_id") else (False, None)
    audit = snapshot.get("rounds", {}).get(str(control.get("active_round_id")), {}).get("latest_audit") if control.get("active_round_id") else None
    control["closure"] = {
        "contract_satisfied": bool(deliverables and all(item["satisfied"] or item.get("human_acceptance_required") for item in deliverables)),
        "interpretation_ready": fresh,
        "audit_ready": bool(audit and audit.get("status") == "pass" and audit.get("after_interpretation_node") == interpretation_node),
        "outcome": control.get("closure", {}).get("outcome", "undetermined"),
    }
    control["required_action"] = _required_action(root, control, snapshot)
    control["pointers"].update({
        "round_contract": f"rounds/{control['active_round_id']}/round_contract.json" if control.get("active_round_id") else None,
        "working_set": "runtime/working_set.json",
        "dag_snapshot": "runtime/dag_snapshot.json",
        "event_ledger": "runtime/event_ledger.jsonl",
        "result_index": "runtime/result_index.jsonl",
    })


def _signature(capability_id: str, input_nodes: list[str], scope: dict[str, Any], parameters: dict[str, Any]) -> str:
    return value_hash({"capability_id": capability_id, "input_nodes": sorted(input_nodes), "scope": scope, "parameters": parameters})


def _analysis_planning_limits() -> tuple[int, int]:
    settings = profile().get("runtime_planning") or {}
    maximum = int(settings.get("max_new_analysis_nodes_per_round", 100))
    batch_size = maximum
    if maximum != 100:
        raise ValueError("Invalid Runtime analysis planning limits")
    return maximum, batch_size


def _round_analysis_work_count(snapshot: dict[str, Any], round_id: str | None) -> int:
    if not round_id:
        return 0
    return sum(
        node["kind"] == "analysis"
        and (node.get("created_in_round") == round_id or node.get("assigned_round") == round_id)
        for node in snapshot["nodes"]
    )


def _balanced_analysis_specs(snapshot: dict[str, Any], specs: list[dict[str, Any]], wave: str) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for spec in specs:
        signature = _signature(spec["capability_id"], spec["input_nodes"], spec["scope"], spec["parameters"])
        unique.setdefault(signature, {**spec, "signature": signature})
    lookup = _node_lookup(snapshot)
    strata: dict[tuple[str, str, tuple[str, ...]], list[dict[str, Any]]] = {}
    for spec in unique.values():
        input_capabilities = tuple(sorted(
            lookup[node_id]["capability_id"]
            for node_id in spec["input_nodes"]
            if node_id in lookup
        ))
        key = (spec["capability_id"], str(spec["scope"].get("mode", "unknown")), input_capabilities)
        strata.setdefault(key, []).append(spec)
    for key, values in strata.items():
        values.sort(key=lambda spec: (value_hash([wave, key, spec["signature"]]), spec["signature"]))
    capability_queues: dict[str, list[dict[str, Any]]] = {}
    for capability_id in sorted({key[0] for key in strata}):
        keys = sorted(
            (key for key in strata if key[0] == capability_id),
            key=lambda key: (value_hash([wave, capability_id, key]), key),
        )
        queue: list[dict[str, Any]] = []
        while keys:
            next_keys: list[tuple[str, str, tuple[str, ...]]] = []
            for key in keys:
                queue.append(strata[key].pop(0))
                if strata[key]:
                    next_keys.append(key)
            keys = next_keys
        capability_queues[capability_id] = queue
    ordered_capabilities = sorted(
        capability_queues,
        key=lambda capability_id: (value_hash([wave, capability_id]), capability_id),
    )
    balanced: list[dict[str, Any]] = []
    while ordered_capabilities:
        next_capabilities: list[str] = []
        for capability_id in ordered_capabilities:
            balanced.append(capability_queues[capability_id].pop(0))
            if capability_queues[capability_id]:
                next_capabilities.append(capability_id)
        ordered_capabilities = next_capabilities
    return balanced


def _materialize_analysis_specs(
    snapshot: dict[str, Any],
    control: dict[str, Any],
    specs: list[dict[str, Any]],
    wave: str,
    wave_limit: int | None = None,
    batch_limit: int | None = None,
    preserve_order: bool = False,
) -> tuple[list[str], int]:
    """Materialize a bounded, deterministic slice without storing deferred candidates as Nodes."""
    round_id = control["active_round_id"]
    maximum, batch_size = _analysis_planning_limits()
    remaining_budget = max(0, maximum - _round_analysis_work_count(snapshot, round_id))
    if wave_limit is not None:
        wave_count = sum(
            node["kind"] == "analysis"
            and node.get("wave") == wave
            and (node.get("created_in_round") == round_id or node.get("assigned_round") == round_id)
            for node in snapshot["nodes"]
        )
        remaining_budget = min(remaining_budget, max(0, wave_limit - wave_count))
    activation_limit = min(batch_size if batch_limit is None else max(0, batch_limit), remaining_budget)
    planned: list[str] = []
    deferred = 0
    by_signature = {node["signature"]: node for node in snapshot["nodes"]}
    ordered_specs = specs if preserve_order else _balanced_analysis_specs(snapshot, specs, wave)
    for spec in ordered_specs:
        existing = by_signature.get(spec["signature"])
        if existing and existing["status"] == "succeeded" and (existing.get("result_quality") or {}).get("eligible_for_downstream", True):
            continue
        if existing and existing.get("assigned_round") == round_id:
            continue
        if len(planned) >= activation_limit:
            deferred += 1
            continue
        node, created = _add_node(
            snapshot,
            control,
            spec["capability_id"],
            spec["input_nodes"],
            wave,
            spec["scope"],
            spec["parameters"],
        )
        by_signature[spec["signature"]] = node
        activated = created or (existing is not None and node.get("assigned_round") == round_id)
        if activated:
            planned.append(node["node_id"])
        elif not (node["status"] == "succeeded" and (node.get("result_quality") or {}).get("eligible_for_downstream", True)):
            deferred += 1
    return planned, deferred


def _add_node(snapshot: dict[str, Any], control: dict[str, Any], capability_id: str, input_nodes: list[str], wave: str, scope: dict[str, Any] | None = None, parameters: dict[str, Any] | None = None, supersedes: str | None = None) -> tuple[dict[str, Any], bool]:
    caps = catalog()
    if capability_id not in caps:
        raise ValueError(f"Unknown capability: {capability_id}")
    capability = caps[capability_id]
    kind = capability["stage"]
    scope = scope or {"mode": "global" if kind == "analysis" else "not_applicable"}
    parameters = parameters or {}
    signature = _signature(capability_id, input_nodes, scope, parameters)
    for node in snapshot["nodes"]:
        if node["signature"] == signature:
            if node["status"] == "succeeded" and (node.get("result_quality") or {}).get("eligible_for_downstream", True):
                record = snapshot.get("rounds", {}).get(str(control.get("active_round_id")))
                if record is not None and node.get("created_in_round") != control.get("active_round_id"):
                    reused = record.setdefault("reused_node_ids", [])
                    if node["node_id"] not in reused:
                        reused.append(node["node_id"])
                return node, False
            if node["status"] in {"pending", "failed"} and node.get("assigned_round") is None:
                node["assigned_round"] = control["active_round_id"]
                if node["status"] == "failed":
                    node["status"] = "pending"
                    node["finished_at"] = None
                return node, False
            if node.get("assigned_round") == control["active_round_id"]:
                return node, False
            if node["status"] == "failed":
                node["assigned_round"] = control["active_round_id"]
                node["status"] = "pending"
                node["finished_at"] = None
                return node, False
            if node["status"] == "cancelled":
                if wave == "human_directed":
                    node["assigned_round"] = control["active_round_id"]
                    node["status"] = "pending"
                    node["finished_at"] = None
                return node, False
    snapshot["counters"]["node"] += 1
    node_id = f"N{snapshot['counters']['node']:06d}"
    node = {
        "node_id": node_id,
        "kind": kind,
        "capability_id": capability_id,
        "skill_name": capability["skill_name"],
        "input_nodes": list(dict.fromkeys(input_nodes)),
        "scope": scope,
        "parameters": parameters,
        "signature": signature,
        "status": "pending",
        "wave": wave,
        "selection_reason": "balanced_random" if wave == "exploration" else ("human" if wave == "human_directed" else "deterministic_plan"),
        "created_in_round": control["active_round_id"],
        "assigned_round": control["active_round_id"],
        "attempts": [],
        "current_attempt_id": None,
        "output_ref": str((Path(control["run"]["run_root"]) / kind / node_id).resolve()),
        "result_quality": None,
        "supersedes": supersedes,
        "created_at": utc_now(),
        "finished_at": None,
    }
    snapshot["nodes"].append(node)
    return node, True


def _infer_compound_column(columns: Iterable[Any]) -> str | None:
    accepted = {"compoundid", "moleculeid", "molid", "id", "chemblid"}
    for column in columns:
        normalized = "".join(character for character in str(column).lower() if character.isalnum())
        if normalized in accepted:
            return str(column)
    return None


def _infer_smiles_column(columns: Iterable[Any], explicit: str | None = None) -> str:
    names = [str(column) for column in columns]
    if explicit:
        if explicit not in names:
            raise ValueError(f"SMILES column not found: {explicit}")
        return explicit
    normalized = {
        name: "".join(character for character in name.lower() if character.isalnum())
        for name in names
    }
    preferred = ("inputsmiles", "canonicalsmiles", "isomericsmiles", "smiles", "structure")
    for candidate in preferred:
        matches = [name for name, value in normalized.items() if value == candidate]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(f"Ambiguous SMILES columns: {matches}; specify --smiles-column")
    contained = [name for name, value in normalized.items() if "smiles" in value]
    if len(contained) == 1:
        return contained[0]
    if len(contained) > 1:
        raise ValueError(f"Ambiguous SMILES columns: {contained}; specify --smiles-column")
    raise ValueError("SMILES column could not be inferred; specify --smiles-column")


def _run_smiles_column(control: dict[str, Any]) -> str:
    import pandas as pd

    recorded = control["run"].get("smiles_column")
    if recorded:
        return str(recorded)
    input_path = Path(control["run"]["input"])
    columns = list(pd.read_csv(input_path, nrows=0).columns)
    return _infer_smiles_column(columns)


def cmd_init(args: argparse.Namespace) -> int:
    import pandas as pd

    if args.parallel_limit < 1:
        raise ValueError("parallel_limit must be at least one")
    if args.available_cpu_cores < 1:
        raise ValueError("available_cpu_cores must be at least one")
    source = Path(args.input).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    frame = pd.read_csv(source)
    if args.endpoint not in frame.columns:
        raise ValueError(f"Endpoint column not found: {args.endpoint}")
    if len(frame) < 1:
        raise ValueError("Input must contain at least one compound")
    smiles_column = _infer_smiles_column(frame.columns, args.smiles_column)
    run_id = args.run_id or timestamp()
    root = Path(args.output_dir).expanduser().resolve() if args.output_dir else (project_root() / "results" / "CONDUCTOR" / args.project / run_id).resolve()
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"Run Root is not empty: {root}")
    for relative in ("runtime/logs", "runtime/scratch", "runtime/requests", "rounds", "description", "clustering", "analysis", "interpretation", "concierge", "audit", "state"):
        (root / relative).mkdir(parents=True, exist_ok=True)
    control_key = secrets.token_hex(48)
    write_json(root / "runtime" / "authority.json", {"schema_version": "1.0.0", "control_authority_key_hash": value_hash(control_key), "created_at": utc_now()})
    atomic_bytes(root / "runtime" / "control_authority.key", control_key.encode("utf-8") + b"\n")
    try:
        os.chmod(root / "runtime" / "control_authority.key", 0o600)
    except OSError:
        pass
    for path in (root / "runtime" / "result_index.jsonl", root / "runtime" / "insight_index.jsonl", root / "runtime" / "cluster_registry.jsonl", root / "runtime" / "event_ledger.jsonl"):
        atomic_bytes(path, b"")
    compound_column = _infer_compound_column(frame.columns)
    if compound_column:
        if compound_column != "compound_id":
            frame.insert(0, "compound_id", frame[compound_column].astype("string"))
    else:
        frame.insert(0, "compound_id", [f"CMP{index + 1:06d}" for index in range(len(frame))])
    if frame["compound_id"].isna().any() or frame["compound_id"].astype(str).str.strip().eq("").any():
        raise ValueError("Compound IDs must not be empty")
    compound_ids = frame["compound_id"].astype("string").tolist()
    if len(compound_ids) != len(set(compound_ids)):
        raise ValueError("Compound IDs must be unique")
    canonical_input = root / "runtime" / "input.csv"
    frame.to_csv(canonical_input, index=False)
    write_csv(root / "runtime" / "cluster_membership.csv", ["compound_id"], ({"compound_id": value} for value in compound_ids))
    control = {
        "schema_version": CONTROL_SCHEMA,
        "conductor_version": VERSION,
        "revision": 0,
        "run": {
            "run_id": run_id,
            "project": args.project,
            "run_root": str(root),
            "input": str(canonical_input),
            "input_hash": file_hash(canonical_input),
            "source_input": str(source),
            "source_input_hash": file_hash(source),
            "id_column": "compound_id",
            "smiles_column": smiles_column,
            "endpoint": args.endpoint,
            "higher_is_better": bool(args.higher_is_better),
            "endpoint_unit": args.endpoint_unit,
            "endpoint_transform": args.endpoint_transform,
            "row_count": len(frame),
            "profile_id": profile()["profile_id"],
            "parallel_limit": args.parallel_limit,
            "available_cpu_cores": args.available_cpu_cores,
        },
        "active_round_id": None,
        "round_state": "NO_ACTIVE_ROUND",
        "next_round_number": 1,
        "required_action": {"code": "AWAIT_HUMAN_ROUND", "reason": "A human-authorized Round is required."},
        "lease": {"owner_id": None, "token_hash": None, "expires_at": None, "heartbeat_at": None, "process_id": None},
        "counts": {},
        "closure": {"contract_satisfied": False, "interpretation_ready": False, "audit_ready": False, "outcome": "undetermined"},
        "pointers": {"round_contract": None, "working_set": "runtime/working_set.json", "dag_snapshot": "runtime/dag_snapshot.json", "event_ledger": "runtime/event_ledger.jsonl", "result_index": "runtime/result_index.jsonl"},
        "blocker": None,
        "last_event_sequence": 0,
        "last_event_checksum": None,
        "updated_at": utc_now(),
    }
    snapshot = {"schema_version": "1.0.0", "control_revision": 0, "last_event_sequence": 0, "counters": {"node": 0, "cluster": 0, "insight": 0}, "nodes": [], "plans": {}, "rounds": {}, "decisions": []}
    with writer_lock(root):
        _commit(root, control, snapshot, "run_initialized", {"run": control["run"]})
    _print_compact(control, run_root=str(root), control_path=str(control_path(root)), next_action="Invoke /cs-conductor-orchestrator and explicitly authorize RND0001.")
    return 0


def _default_deliverables(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    first_comprehensive = not any(node["status"] == "succeeded" for node in snapshot["nodes"])
    items: list[dict[str, Any]] = []
    if first_comprehensive:
        p = profile()
        items.append({"deliverable_id": "DELIV_BASIC", "type": "planned_node_coverage", "description": "計画された基本計算Nodeを可能な範囲で完了する。", "parameters": {"plan_key": "basic_compute"}, "human_acceptance_required": False})
        items.append({"deliverable_id": "DELIV_GLOBAL", "type": "capability_coverage", "description": "Global Operatorを優先的に探索する。", "parameters": {"capability_ids": p["exploration"]["global_operator_capabilities"], "scope_modes": ["global"]}, "human_acceptance_required": False})
    items.append({"deliverable_id": "DELIV_INTERPRETATION", "type": "interpretation_completed", "description": "当該RoundのInterpretationを生成する。", "parameters": {}, "human_acceptance_required": False})
    return items


def cmd_prepare_round(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        if control.get("active_round_id"):
            raise ValueError(f"Active Round already exists: {control['active_round_id']}")
        if args.parallel_limit is not None and args.parallel_limit < 1:
            raise ValueError("parallel_limit must be at least one")
        if args.available_cpu_cores is not None and args.available_cpu_cores < 1:
            raise ValueError("available_cpu_cores must be at least one")
        round_id = f"RND{control['next_round_number']:04d}"
        request_payload = {
            "objective": args.objective,
            "optional_directions": args.optional_direction or [],
            "human_priorities": args.human_priority or [],
            "budgets": {
                "walltime_minutes": args.walltime_minutes,
                "parallel_limit": args.parallel_limit or control["run"]["parallel_limit"],
                "available_cpu_cores": args.available_cpu_cores or _available_cpu_cores(control),
                "max_additional_nodes": args.max_additional_nodes,
                "interpretation_iterations": args.interpretation_iterations,
            },
            "omissions": args.omission or [],
            "high_cost_bundle_approved": bool(args.approve_high_cost),
        }
        request_hash = value_hash(request_payload)
        contract = {"schema_version": "1.0.0", "round_id": round_id, **request_payload, "required_deliverables": _default_deliverables(snapshot), "request_hash": request_hash, "created_at": utc_now()}
        if args.required_deliverables_json:
            contract["required_deliverables"] = json.loads(Path(args.required_deliverables_json).read_text(encoding="utf-8") if Path(args.required_deliverables_json).is_file() else args.required_deliverables_json)
        validate(contract, "round_contract.schema.json")
        token = secrets.token_hex(32)
        request_record = {"schema_version": "1.0.0", "contract": contract, "authorization_token_hash": value_hash(token), "used": False, "created_at": utc_now()}
        request_path = root / "runtime" / "requests" / f"{round_id}_{request_hash[:12]}.json"
        write_json(request_path, request_record)
    _print_compact(control, request_file=str(request_path), authorization_token=token, state_changed=False, proposed_round_id=round_id, contract_hash=value_hash(contract))
    return 0


def cmd_authorize_round(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    _require_control_authority(root, args.control_key)
    request_path = Path(args.request_file).resolve()
    if request_path.parent != (root / "runtime" / "requests").resolve():
        raise ValueError("Round request must be inside this Run Root")
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        if control.get("active_round_id"):
            raise ValueError("Cannot authorize a new Round while another Round is active")
        request = read_json(request_path)
        if request.get("used"):
            raise ValueError("Round authorization request was already used")
        if not secrets.compare_digest(request["authorization_token_hash"], value_hash(args.authorization_token)):
            raise PermissionError("Invalid one-time Round authorization token")
        contract = request["contract"]
        expected = f"RND{control['next_round_number']:04d}"
        if contract["round_id"] != expected:
            raise ValueError(f"Expected {expected}, got {contract['round_id']}")
        round_id = contract["round_id"]
        round_dir = root / "rounds" / round_id
        round_dir.mkdir(parents=True, exist_ok=False)
        write_json(round_dir / "round_contract.json", contract)
        started = datetime.now(timezone.utc)
        total_minutes = contract["budgets"]["walltime_minutes"]
        reserve = min(90, max(5, total_minutes // 5), max(1, total_minutes - 1))
        deadline = started + timedelta(minutes=contract["budgets"]["walltime_minutes"])
        snapshot["rounds"][round_id] = {"state": "ACTIVE", "runtime_version": VERSION, "started_at": started.isoformat(), "deadline_at": deadline.isoformat(), "soft_stop_at": (deadline - timedelta(minutes=reserve)).isoformat(), "scientific_finish_requested": False, "finish_reason": None, "human_checkpoint_requested": False, "latest_audit": None, "current_interpretation_node": None, "no_progress_returns": 0}
        maximum_analysis_nodes, batch_size = _analysis_planning_limits()
        snapshot["plans"][round_id] = {
            "basic_compute": False,
            "exploration": False,
            "exploration_nodes_planned": 0,
            "analysis_node_limit": maximum_analysis_nodes,
            "scope_sequence": ["global", "global", "local"],
        }
        control.update({"active_round_id": round_id, "round_state": "ACTIVE", "next_round_number": control["next_round_number"] + 1, "blocker": None})
        control["run"]["parallel_limit"] = contract["budgets"]["parallel_limit"]
        control["run"]["available_cpu_cores"] = contract["budgets"].get(
            "available_cpu_cores", DEFAULT_AVAILABLE_CPU_CORES
        )
        request["used"] = True
        request["used_at"] = utc_now()
        write_json(request_path, request)
        _commit(root, control, snapshot, "round_authorized", {"contract": contract}, round_id=round_id)
    _print_compact(control, next_step="Acquire the Main Agent Orchestrator lease with resume-round.")
    return 0


def cmd_resume_round(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    _require_control_authority(root, args.control_key)
    with writer_lock(root):
        recovered = _recover_transaction(root)
        control, snapshot = _read_state(root)
        if control["round_state"] not in {"ACTIVE", "FINALIZING"} or not control.get("active_round_id"):
            raise ValueError(f"No resumable Round: {control['round_state']}")
        live = _lease_live(control)
        if live:
            _print_compact(control, lease_acquired=False, reason="LIVE_LEASE_EXISTS", owner_id=control["lease"]["owner_id"], expires_at=control["lease"]["expires_at"])
            return 0
        if args.smiles_column:
            import pandas as pd

            existing = control["run"].get("smiles_column")
            resolved = _infer_smiles_column(
                list(pd.read_csv(control["run"]["input"], nrows=0).columns),
                args.smiles_column,
            )
            if existing and existing != resolved:
                raise ValueError(f"Run SMILES column is immutable: {existing}")
            control["run"]["smiles_column"] = resolved
        lease_token = secrets.token_hex(32)
        now = datetime.now(timezone.utc)
        control["lease"].update({"owner_id": args.owner_id, "token_hash": value_hash(lease_token), "expires_at": (now + timedelta(minutes=max(5, args.lease_minutes))).isoformat(), "heartbeat_at": now.isoformat(), "process_id": args.process_id})
        _commit(root, control, snapshot, "orchestrator_lease_acquired", {"owner_id": args.owner_id, "recovered_transactions": recovered, "smiles_column": control["run"].get("smiles_column")}, round_id=control["active_round_id"])
        working = _write_working_set(root, control, snapshot)
    _print_compact(control, lease_acquired=True, lease_token=lease_token, recovered_transactions=recovered)
    return 0


def cmd_release_lease(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        _require_action(control, args.lease_token)
        owner = control["lease"]["owner_id"]
        control["lease"] = {"owner_id": None, "token_hash": None, "expires_at": None, "heartbeat_at": None, "process_id": None}
        _commit(root, control, snapshot, "orchestrator_lease_released", {"owner_id": owner, "reason": args.reason}, round_id=control.get("active_round_id"))
    _print_compact(control, lease_released=True, released_owner=owner)
    return 0


def cmd_continue_round(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    _require_control_authority(root, args.control_key)
    if args.additional_walltime_minutes < 1:
        raise ValueError("Additional walltime must be at least one minute")
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        if control["round_state"] != "AWAITING_HUMAN_REVIEW":
            raise ValueError("Same-Round continuation requires AWAITING_HUMAN_REVIEW")
        round_id = control["active_round_id"]
        record = snapshot["rounds"][round_id]
        now = datetime.now(timezone.utc)
        minutes = args.additional_walltime_minutes
        reserve = min(90, max(5, minutes // 5), max(1, minutes - 1))
        record.update({"state": "ACTIVE", "deadline_at": (now + timedelta(minutes=minutes)).isoformat(), "soft_stop_at": (now + timedelta(minutes=minutes - reserve)).isoformat(), "scientific_finish_requested": False, "finish_reason": None, "latest_audit": None, "interpretation_revision_required": True, "interpretation_revision_serial": int(record.get("interpretation_revision_serial", 0)) + 1})
        record.setdefault("human_continuations", []).append({"reason": args.reason, "at": utc_now()})
        control.update({"round_state": "ACTIVE", "blocker": None})
        control["closure"] = {"contract_satisfied": False, "interpretation_ready": False, "audit_ready": False, "outcome": "undetermined"}
        _commit(root, control, snapshot, "round_continued_by_human", {"reason": args.reason, "additional_walltime_minutes": minutes}, round_id=round_id)
    _print_compact(control, continued_round_id=round_id, additional_walltime_minutes=minutes)
    return 0


def cmd_revise_report(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    _require_control_authority(root, args.control_key)
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        blocked_finalizing = control["round_state"] == "FINALIZING" and (control.get("blocker") or {}).get("code") == "INTERPRETATION_RETRY_EXHAUSTED"
        if control["round_state"] != "AWAITING_HUMAN_REVIEW" and not blocked_finalizing:
            raise ValueError("Report revision requires human review or a blocked Interpretation gate")
        round_id = control["active_round_id"]
        record = snapshot["rounds"][round_id]
        record.update({"state": "FINALIZING", "latest_audit": None, "report_revision_reason": args.reason, "interpretation_revision_required": True, "interpretation_revision_serial": int(record.get("interpretation_revision_serial", 0)) + 1, "human_interpretation_retry_authorized": blocked_finalizing})
        control.update({"round_state": "FINALIZING", "blocker": None})
        _commit(root, control, snapshot, "report_revision_requested", {"reason": args.reason}, round_id=round_id)
    _print_compact(control, report_revision_requested=True, round_id=round_id)
    return 0


def cmd_accept_round(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    _require_control_authority(root, args.control_key)
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        if control["round_state"] != "AWAITING_HUMAN_REVIEW":
            raise ValueError("Round acceptance requires AWAITING_HUMAN_REVIEW")
        round_id = control["active_round_id"]
        record = snapshot["rounds"][round_id]
        interpretation = record.get("current_interpretation_node")
        audit = record.get("latest_audit") or {}
        if not interpretation or audit.get("status") != "pass":
            raise ValueError("Interpretation and passing Full Audit are required")
        outcome_path = root / "rounds" / round_id / "round_outcome.json"
        outcome = read_json(outcome_path)
        outcome["human_accepted_at"] = utc_now()
        outcome["human_note"] = args.note
        write_json(outcome_path, outcome)
        record["state"] = "CLOSED"
        record["accepted_at"] = utc_now()
        control.update({"active_round_id": None, "round_state": "CLOSED", "blocker": None})
        control["lease"] = {"owner_id": None, "token_hash": None, "expires_at": None, "heartbeat_at": None, "process_id": None}
        _commit(root, control, snapshot, "round_accepted_by_human", {"note": args.note}, round_id=round_id)
    _print_compact(control, accepted_round_id=round_id)
    return 0


def cmd_verify_return(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    with writer_lock(root):
        recovered = _recover_transaction(root)
        control, snapshot = _read_state(root)
        reclaimed = False
        if args.confirm_returned:
            if not args.control_key or not args.owner_id or args.start_revision is None:
                raise ValueError("Confirmed return requires Main control authority, owner ID, and start revision")
            _require_control_authority(root, args.control_key)
            lease = control["lease"]
            if lease.get("owner_id") and lease.get("owner_id") != args.owner_id:
                raise ValueError("Returned Orchestrator owner does not match the live lease")
            if lease.get("owner_id") == args.owner_id:
                record = snapshot["rounds"][control["active_round_id"]]
                progressed = int(control["revision"]) > int(args.start_revision)
                record["no_progress_returns"] = 0 if progressed else int(record.get("no_progress_returns", 0)) + 1
                control["lease"] = {"owner_id": None, "token_hash": None, "expires_at": None, "heartbeat_at": None, "process_id": None}
                _commit(root, control, snapshot, "returned_orchestrator_lease_reclaimed", {"owner_id": args.owner_id, "start_revision": args.start_revision, "progressed": progressed, "no_progress_returns": record["no_progress_returns"]}, round_id=control["active_round_id"])
                reclaimed = True
        sequence, checksum = _verify_ledger(root)
        lease = control["lease"]
        no_progress = int(snapshot.get("rounds", {}).get(str(control.get("active_round_id")), {}).get("no_progress_returns", 0)) if control.get("active_round_id") else 0
        resumable = bool(control.get("active_round_id") and control["round_state"] in {"ACTIVE", "FINALIZING"} and not _lease_live(control))
        human_stop = control["required_action"]["code"] in {"FAILED_NODE_REPAIR_REQUIRED", "HUMAN_APPROVAL_REQUIRED", "HUMAN_REVIEW_REQUIRED", "INTERPRETATION_BLOCKED", "AWAIT_HUMAN_ROUND"}
        response = {"ledger_ok": sequence == control["last_event_sequence"] and checksum == control["last_event_checksum"], "lease_live": _lease_live(control), "lease_reclaimed": reclaimed, "recovered_transactions": recovered, "same_round_resume_allowed": resumable, "automatic_same_round_resume_recommended": bool(resumable and not human_stop and no_progress < 2), "no_progress_returns": no_progress, "new_round_allowed": not control.get("active_round_id")}
    _print_compact(control, **response)
    return 0


def _succeeded(snapshot: dict[str, Any], kind: str | None = None, capability_ids: Iterable[str] | None = None) -> list[dict[str, Any]]:
    allowed = set(capability_ids or [])
    return [
        node
        for node in snapshot["nodes"]
        if node["status"] == "succeeded"
        and (node.get("result_quality") or {}).get("eligible_for_downstream", True)
        and (kind is None or node["kind"] == kind)
        and (not allowed or node["capability_id"] in allowed)
    ]


def _all_nodes_by_capability(snapshot: dict[str, Any], capability_ids: Iterable[str] | None = None) -> dict[str, list[dict[str, Any]]]:
    allowed = set(capability_ids or [])
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in snapshot["nodes"]:
        if not allowed or node["capability_id"] in allowed:
            result[node["capability_id"]].append(node)
    return result


def _plan_basic(control: dict[str, Any], snapshot: dict[str, Any]) -> list[str]:
    p = profile()["basic_compute"]
    planned: list[str] = []
    required: list[str] = []
    description_nodes: dict[str, dict[str, Any]] = {}
    for capability_id in p["description_capabilities"]:
        node, created = _add_node(snapshot, control, capability_id, [], "basic_compute", {"mode": "not_applicable"}, {})
        description_nodes[capability_id] = node
        required.append(node["node_id"])
        if created:
            planned.append(node["node_id"])
    for capability_id in p["direct_structure_clustering"]:
        node, created = _add_node(snapshot, control, capability_id, [], "basic_compute", {"mode": "not_applicable"}, {"min_cluster_size": 5})
        required.append(node["node_id"])
        if created:
            planned.append(node["node_id"])
    for capability_id in p["vector_clustering_capabilities"]:
        for representation in p["vector_clustering_representations"]:
            source = description_nodes.get(representation)
            if not source:
                continue
            parameters = {"input_representation": representation, "parameter_mode": "auto", "min_cluster_size": 5}
            node, created = _add_node(snapshot, control, capability_id, [source["node_id"]], "basic_compute", {"mode": "not_applicable"}, parameters)
            required.append(node["node_id"])
            if created:
                planned.append(node["node_id"])
    plan = snapshot["plans"][control["active_round_id"]]
    plan["basic_compute"] = True
    plan["basic_compute_node_ids"] = list(dict.fromkeys(required))
    return planned


def _analysis_inputs(capability: dict[str, Any], descriptions: list[dict[str, Any]], clusterings: list[dict[str, Any]], scope_mode: str) -> list[list[str]]:
    dependencies = set(capability.get("dependencies") or [])
    if capability["capability_id"] == "A005":
        return []
    if not dependencies:
        return [[]] if scope_mode == "global" else [[cluster["node_id"]] for cluster in clusterings]
    if dependencies == {"description"}:
        return [[description["node_id"]] if scope_mode == "global" else [description["node_id"], cluster["node_id"]] for description in descriptions for cluster in ([None] if scope_mode == "global" else clusterings) if scope_mode == "global" or cluster]
    if dependencies == {"clustering"}:
        return [[cluster["node_id"]] for cluster in clusterings]
    if dependencies == {"description", "clustering"}:
        return [[description["node_id"], cluster["node_id"]] for description in descriptions for cluster in clusterings]
    return []


def _mmp_enabled_for_active_round(control: dict[str, Any], snapshot: dict[str, Any]) -> bool:
    """A014 is available only to a Round created by this Runtime version."""
    round_id = control.get("active_round_id")
    return bool(round_id and (snapshot.get("rounds", {}).get(round_id) or {}).get("runtime_version") == VERSION)


def _usable_clusterings(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return _succeeded(snapshot, "clustering")


def _cluster_rows(root: Path, source_node: str | None = None) -> list[dict[str, Any]]:
    rows = read_jsonl(root / "runtime" / "cluster_registry.jsonl")
    latest = {row["cluster_id"]: row for row in rows}
    values = [row for row in latest.values() if row.get("status", "active") == "active" and int(row.get("compound_count", 0)) >= 5]
    if source_node:
        values = [row for row in values if row.get("source_node_id") == source_node]
    return values


def _representative_cluster_ids(root: Path, clustering_node: dict[str, Any], limit: int) -> list[str]:
    rows = _cluster_rows(root, clustering_node["node_id"])
    if not rows:
        return []
    total = max(1, int(read_json(control_path(root))["run"]["row_count"]))
    ranked: list[dict[str, Any]] = []
    ranked.extend(sorted(rows, key=lambda row: (-int(row["compound_count"]), row["cluster_id"])))
    ranked.extend(sorted(rows, key=lambda row: (abs(int(row["compound_count"]) / total - 0.2), row["cluster_id"])))
    ranked.extend(sorted(rows, key=lambda row: (int(row["compound_count"]) / total > 0.5, -float(row.get("structural_cohesion") or 0), row["cluster_id"])))
    selected: list[str] = []
    for row in ranked:
        if row["cluster_id"] not in selected:
            selected.append(row["cluster_id"])
        if len(selected) >= limit:
            break
    return selected


def _exploration_global_specs(control: dict[str, Any], snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    settings = profile()["exploration"]
    caps = catalog()
    descriptions = _succeeded(snapshot, "description", settings["description_panel"])
    clusterings = _usable_clusterings(snapshot)
    by_description = {node["capability_id"]: node for node in _succeeded(snapshot, "description")}
    specs: list[dict[str, Any]] = []
    for capability_id in settings["global_operator_capabilities"]:
        capability = caps[capability_id]
        if capability_id == "A005":
            panel = profile()["modeling"]["fixed_description_panel"]
            if all(item in by_description for item in panel):
                specs.append({"capability_id": capability_id, "input_nodes": [by_description[item]["node_id"] for item in panel], "scope": {"mode": "global"}, "parameters": {"role": "global-model"}})
            continue
        for input_nodes in _analysis_inputs(capability, descriptions, clusterings, "global"):
            specs.append({
                "capability_id": capability_id,
                "input_nodes": input_nodes,
                "scope": {"mode": "global"},
                "parameters": {"role": "global-build"} if capability_id == "A014" else {},
            })
    return specs


def _global_comparator(global_nodes: list[dict[str, Any]], capability_id: str, local_inputs: list[str]) -> dict[str, Any] | None:
    local_set = set(local_inputs)
    compatible = [
        node for node in global_nodes
        if node["capability_id"] == capability_id
        and node.get("scope", {}).get("mode") == "global"
        and set(node["input_nodes"]).issubset(local_set)
    ]
    return max(compatible, key=lambda node: (len(node["input_nodes"]), node["node_id"]), default=None)


def _exploration_local_specs(root: Path, control: dict[str, Any], snapshot: dict[str, Any], global_nodes: list[dict[str, Any]], mmp_screen_node: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    settings = profile()["exploration"]
    caps = catalog()
    descriptions = _succeeded(snapshot, "description", settings["description_panel"])
    by_description = {node["capability_id"]: node for node in _succeeded(snapshot, "description")}
    clusterings = _usable_clusterings(snapshot)
    limit = int(settings["representative_clusters_per_clustering"])
    specs: list[dict[str, Any]] = []
    for clustering in clusterings:
        cluster_ids = _representative_cluster_ids(root, clustering, limit)
        for cluster_id in cluster_ids:
            scope = {"mode": "single_cluster", "cluster_ids": [cluster_id]}
            for capability_id in settings["local_operator_capabilities"]:
                if capability_id in {"A003", "A004", "A005", "A014"}:
                    continue
                capability = caps[capability_id]
                for base_inputs in _analysis_inputs(capability, descriptions, [clustering], "local"):
                    comparator = _global_comparator(global_nodes, capability_id, base_inputs)
                    if not comparator:
                        continue
                    specs.append({
                        "capability_id": capability_id,
                        "input_nodes": list(dict.fromkeys([*base_inputs, comparator["node_id"]])),
                        "scope": scope,
                        "parameters": {"target_cluster": cluster_id},
                    })
            for projection_id in ("A003", "A004"):
                for global_projection in [node for node in global_nodes if node["capability_id"] == projection_id]:
                    specs.append({
                        "capability_id": projection_id,
                        "input_nodes": [global_projection["node_id"], clustering["node_id"]],
                        "scope": scope,
                        "parameters": {"role": "cluster-overlay", "target_cluster": cluster_id},
                    })
        global_model = next((node for node in global_nodes if node["capability_id"] == "A005" and node.get("parameters", {}).get("role") == "global-model"), None)
        panel = profile()["modeling"]["fixed_description_panel"]
        if global_model and all(item in by_description for item in panel):
            specs.append({
                "capability_id": "A005",
                "input_nodes": [*[by_description[item]["node_id"] for item in panel], clustering["node_id"], global_model["node_id"]],
                "scope": {"mode": "multi_scope", "clustering_node": clustering["node_id"]},
                "parameters": {"role": "cluster-survey", "min_local_samples": profile()["modeling"]["minimum_local_samples"]},
            })
    mmp_profile = profile().get("matched_molecular_pairs") or {}
    global_mmp = next((node for node in global_nodes if node["capability_id"] == "A014" and node.get("parameters", {}).get("role") == "global-build"), None)
    if global_mmp and clusterings and mmp_screen_node:
        representative = set(mmp_profile.get("representative_clustering_capabilities") or [])
        per_clustering = int(mmp_profile.get("representative_clusters_per_clustering", 1))
        for clustering in [node for node in clusterings if node["capability_id"] in representative]:
            for cluster_id in _representative_cluster_ids(root, clustering, per_clustering):
                specs.append({
                    "capability_id": "A014",
                    "input_nodes": [global_mmp["node_id"], mmp_screen_node["node_id"], clustering["node_id"]],
                    "scope": {"mode": "single_cluster", "cluster_ids": [cluster_id]},
                    "parameters": {"role": mmp_profile.get("detail_role", "local-detail"), "target_cluster": cluster_id},
                })
    return specs


def _history_balanced_specs(snapshot: dict[str, Any], specs: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    lookup = _node_lookup(snapshot)
    history = [
        node for node in snapshot["nodes"]
        if node["kind"] == "analysis"
        and node["status"] == "succeeded"
        and (node.get("result_quality") or {}).get("eligible_for_downstream", True)
    ]
    capability_counts = Counter(node["capability_id"] for node in history)
    scope_counts = Counter("local" if node.get("scope", {}).get("mode") != "global" else "global" for node in history)
    input_counts: Counter[str] = Counter()
    for node in history:
        input_counts.update(lookup[item]["capability_id"] for item in node["input_nodes"] if item in lookup and lookup[item]["kind"] in {"description", "clustering"})
    unique: dict[str, dict[str, Any]] = {}
    for spec in specs:
        signature = _signature(spec["capability_id"], spec["input_nodes"], spec["scope"], spec["parameters"])
        blocked = any(
            node["signature"] == signature
            and (
                node["status"] in {"pending", "running", "cancelled"}
                or (
                    node["status"] == "succeeded"
                    and (node.get("result_quality") or {}).get("eligible_for_downstream", True)
                )
            )
            for node in snapshot["nodes"]
        )
        if not blocked:
            unique.setdefault(signature, {**spec, "signature": signature})
    def score(spec: dict[str, Any]) -> tuple[Any, ...]:
        source_ids = [lookup[item]["capability_id"] for item in spec["input_nodes"] if item in lookup and lookup[item]["kind"] in {"description", "clustering"}]
        scope = "local" if spec["scope"].get("mode") != "global" else "global"
        return (
            capability_counts[spec["capability_id"]],
            scope_counts[scope],
            sum(input_counts[item] for item in source_ids),
            value_hash([seed, spec["signature"]]),
        )
    return sorted(unique.values(), key=score)


def _plan_exploration(root: Path, control: dict[str, Any], snapshot: dict[str, Any]) -> list[str]:
    maximum, _batch_size = _analysis_planning_limits()
    contract = _active_contract(root, control)
    requested = int((contract or {}).get("budgets", {}).get("max_additional_nodes", maximum))
    budget = min(maximum, max(0, requested))
    settings = profile()["exploration"]
    global_slots = min(budget, (2 * budget + 2) // 3)
    global_specs = _history_balanced_specs(snapshot, _exploration_global_specs(control, snapshot), int(settings["random_seed"]))
    planned_global, _deferred_global = _materialize_analysis_specs(
        snapshot, control, global_specs, "exploration", batch_limit=global_slots, preserve_order=True,
    )
    lookup = _node_lookup(snapshot)
    global_nodes = [lookup[node_id] for node_id in planned_global]
    global_nodes.extend(node for node in _succeeded(snapshot, "analysis") if node.get("scope", {}).get("mode") == "global")
    remaining = max(0, budget - len(planned_global))
    screen_planned: list[str] = []
    mmp_screen_node: dict[str, Any] | None = None
    global_mmp = next((node for node in global_nodes if node["capability_id"] == "A014" and node.get("parameters", {}).get("role") == "global-build"), None)
    clusterings = _usable_clusterings(snapshot)
    if global_mmp and clusterings and remaining:
        mmp_profile = profile().get("matched_molecular_pairs") or {}
        mmp_screen_node, created = _add_node(
            snapshot, control, "A014", [global_mmp["node_id"], *[node["node_id"] for node in clusterings]],
            "exploration", {"mode": "multi_scope"}, {"role": mmp_profile.get("screen_role", "local-screen")},
        )
        if created or (mmp_screen_node.get("assigned_round") == control["active_round_id"] and mmp_screen_node.get("status") != "succeeded"):
            screen_planned.append(mmp_screen_node["node_id"])
            remaining -= 1
    local_specs = _history_balanced_specs(snapshot, _exploration_local_specs(root, control, snapshot, global_nodes, mmp_screen_node), int(settings["random_seed"]) + 1)
    planned_local, _deferred_local = _materialize_analysis_specs(
        snapshot, control, local_specs, "exploration", batch_limit=remaining, preserve_order=True,
    )
    planned = list(dict.fromkeys([*planned_global, *screen_planned, *planned_local]))
    plan = snapshot["plans"][control["active_round_id"]]
    plan.update({
        "exploration": True,
        "exploration_nodes_planned": len(planned),
        "global_nodes_planned": len(planned_global),
        "local_nodes_planned": len(screen_planned) + len(planned_local),
        "selection_seed": int(settings["random_seed"]),
        "scope_sequence": list(settings["scope_sequence"]),
    })
    return planned


def _candidate_cells(root: Path, control: dict[str, Any], snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    p = profile()
    contract = _active_contract(root, control)
    round_plan = snapshot.get("plans", {}).get(str(control.get("active_round_id")), {})
    maximum, _batch_size = _analysis_planning_limits()
    if _round_analysis_work_count(snapshot, control["active_round_id"]) >= maximum:
        return []
    if contract and _round_analysis_work_count(snapshot, control["active_round_id"]) >= min(100, int(contract["budgets"]["max_additional_nodes"])):
        return []
    caps = catalog()
    descriptions = _succeeded(snapshot, "description", p["exploration"]["description_panel"])
    clusterings = _usable_clusterings(snapshot)
    existing = {
        node["signature"] for node in snapshot["nodes"]
        if node["status"] in {"pending", "running", "cancelled"}
        or (node["status"] == "succeeded" and (node.get("result_quality") or {}).get("eligible_for_downstream", True))
    }
    candidates: list[dict[str, Any]] = []
    for capability_id in p["exploration"]["global_operator_capabilities"]:
        capability = caps[capability_id]
        for scope_mode in ("global", "local"):
            for input_nodes in _analysis_inputs(capability, descriptions, clusterings, scope_mode):
                scopes = [{"mode": "global"}] if scope_mode == "global" else [{"mode": "single_cluster", "cluster_ids": [row["cluster_id"]]} for row in _cluster_rows(root, next((item for item in input_nodes if _node_lookup(snapshot)[item]["kind"] == "clustering"), None))[:4]]
                for scope in scopes:
                    parameters = {"target_cluster": scope.get("cluster_ids", [None])[0]} if scope_mode == "local" else {}
                    signature = _signature(capability_id, input_nodes, scope, parameters)
                    if signature not in existing:
                        candidates.append({"candidate_id": value_hash(signature)[:16], "capability_id": capability_id, "input_nodes": input_nodes, "scope": scope, "parameters": parameters, "balance_key": [capability_id, scope_mode, *sorted(_node_lookup(snapshot)[item]["capability_id"] for item in input_nodes)]})
    return sorted(candidates, key=lambda item: (value_hash(item["balance_key"]), item["candidate_id"]))


def _write_working_set(root: Path, control: dict[str, Any], snapshot: dict[str, Any]) -> Path:
    round_id = control.get("active_round_id")
    insights = read_jsonl(root / "runtime" / "insight_index.jsonl")
    latest_insights: dict[str, dict[str, Any]] = {}
    for item in insights:
        latest_insights[item["insight_id"]] = item
    chosen_insights = sorted(latest_insights.values(), key=lambda item: ({"pinned": 0, "active": 1, "watch": 2, "background": 3}.get(item.get("attention"), 3), item["insight_id"]))[:20]
    lookup = _node_lookup(snapshot)
    result_rows = [
        row
        for row in read_jsonl(root / "runtime" / "result_index.jsonl")
        if (lookup.get(row.get("node_id"), {}).get("result_quality") or {}).get("eligible_for_downstream", True)
    ]
    active_refs = {ref for insight in chosen_insights for ref in [*(insight.get("supporting_results") or []), *(insight.get("counter_results") or [])]}
    chosen_results = [row for row in result_rows if row.get("result_ref") in active_refs]
    if len(chosen_results) < 20:
        chosen_results.extend([row for row in reversed(result_rows) if row not in chosen_results][: 20 - len(chosen_results)])
    candidates = _candidate_cells(root, control, snapshot)[:MAX_CANDIDATES] if round_id and control["required_action"]["code"] == "SCIENTIFIC_DECISION" else []
    contract = _active_contract(root, control)
    deliverables = _deliverable_status(root, control, snapshot) if contract else []
    working = {"schema_version": "1.0.0", "run_id": control["run"]["run_id"], "round_id": round_id, "control_revision": control["revision"], "required_action": control["required_action"], "round_contract": contract, "human_priorities": contract.get("human_priorities", []) if contract else [], "unmet_deliverables": [item for item in deliverables if not item["satisfied"]], "insights": chosen_insights, "results": chosen_results[:20], "candidates": candidates, "query_pointers": [], "created_at": utc_now()}
    payload = canonical_bytes(working)
    if len(payload) > MAX_WORKING_SET_BYTES:
        working["query_pointers"].append({"reason": "bounded_working_set", "commands": ["query result", "query insight", "query candidates"]})
        while len(canonical_bytes(working)) > MAX_WORKING_SET_BYTES and working["results"]:
            working["results"].pop()
        while len(canonical_bytes(working)) > MAX_WORKING_SET_BYTES and working["insights"]:
            working["insights"].pop()
        while len(canonical_bytes(working)) > MAX_WORKING_SET_BYTES and working["candidates"]:
            working["candidates"].pop()
    if len(canonical_bytes(working)) > MAX_WORKING_SET_BYTES:
        raise ValueError("Round Contract and human priorities exceed the bounded Working Set limit")
    validate(working, "working_set.schema.json")
    path = root / "runtime" / "working_set.json"
    write_json(path, working)
    return path


def _plan_mutation(args: argparse.Namespace, allowed: set[str], event_type: str, planner: Callable[[Path, dict[str, Any], dict[str, Any]], list[str]]) -> int:
    root = resolve_root(args.run_root)
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        _require_action(control, args.lease_token, allowed)
        planned = planner(root, control, snapshot)
        _commit(root, control, snapshot, event_type, {"planned_node_ids": planned}, round_id=control["active_round_id"])
        working = _write_working_set(root, control, snapshot)
    _print_compact(control, planned_node_ids=planned[:100], planned_count=len(planned))
    return 0


def cmd_plan_basic(args: argparse.Namespace) -> int:
    return _plan_mutation(args, {"PLAN_BASIC"}, "basic_compute_planned", lambda _root, control, snapshot: _plan_basic(control, snapshot))


def cmd_plan_exploration(args: argparse.Namespace) -> int:
    return _plan_mutation(args, {"PLAN_EXPLORATION"}, "exploration_planned", _plan_exploration)


def cmd_apply_scientific_decision(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        _require_action(control, args.lease_token, {"SCIENTIFIC_DECISION"})
        candidates = {item["candidate_id"]: item for item in _candidate_cells(root, control, snapshot)}
        selected_ids = [item for item in (args.candidate_ids or "").split(",") if item]
        maximum, _batch_size = _analysis_planning_limits()
        remaining_round_capacity = max(0, maximum - _round_analysis_work_count(snapshot, control["active_round_id"]))
        if len(selected_ids) > remaining_round_capacity:
            raise ValueError(
                f"Round Analysis Node limit would be exceeded: selected={len(selected_ids)}, "
                f"remaining={remaining_round_capacity}, limit={maximum}"
            )
        planned: list[str] = []
        for candidate_id in selected_ids:
            if candidate_id not in candidates:
                raise ValueError(f"Unknown or stale candidate: {candidate_id}")
            item = candidates[candidate_id]
            node, created = _add_node(snapshot, control, item["capability_id"], item["input_nodes"], "deep_dive", item["scope"], item["parameters"])
            if created:
                node["selection_reason"] = "interpreter_followup"
                planned.append(node["node_id"])
        record = snapshot["rounds"][control["active_round_id"]]
        if args.finish_reason:
            if args.finish_reason not in {"no_eligible_work", "contract_satisfied"}:
                raise ValueError("Invalid finish reason")
            deliverables = [item for item in _deliverable_status(root, control, snapshot) if item["type"] != "interpretation_completed"]
            if args.finish_reason == "contract_satisfied" and not deliverables:
                raise ValueError("Runtime cannot verify contract_satisfied without required deliverables")
            if args.finish_reason == "contract_satisfied" and not all(item["satisfied"] or item.get("human_acceptance_required") for item in deliverables):
                raise ValueError("Runtime refuses contract_satisfied while required scientific deliverables remain")
            remaining = _candidate_cells(root, control, snapshot)
            if args.finish_reason == "no_eligible_work" and remaining:
                raise ValueError("Runtime refuses no_eligible_work while validated candidates remain")
            record.update({"scientific_finish_requested": True, "finish_reason": args.finish_reason})
        elif _round_analysis_work_count(snapshot, control["active_round_id"]) >= maximum:
            record.update({"scientific_finish_requested": True, "finish_reason": "analysis_node_budget_exhausted"})
        if not planned and not args.finish_reason:
            raise ValueError("Select at least one candidate or supply a Runtime-verifiable finish reason")
        snapshot["decisions"].append({"round_id": control["active_round_id"], "candidate_ids": selected_ids, "planned_node_ids": planned, "rationale": args.rationale, "created_at": utc_now()})
        _commit(root, control, snapshot, "scientific_decision_applied", {"candidate_ids": selected_ids, "planned_node_ids": planned, "rationale": args.rationale, "finish_reason": args.finish_reason}, round_id=control["active_round_id"])
        working = _write_working_set(root, control, snapshot)
    _print_compact(control, planned_node_ids=planned[:100], planned_count=len(planned))
    return 0


def cmd_approve_high_cost(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    _require_control_authority(root, args.control_key)
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        if control["required_action"]["code"] != "HUMAN_APPROVAL_REQUIRED":
            raise ValueError("No high-cost approval is currently required")
        contract_path = root / "rounds" / control["active_round_id"] / "round_contract.json"
        contract = read_json(contract_path)
        contract["high_cost_bundle_approved"] = bool(args.approve)
        validate(contract, "round_contract.schema.json")
        write_json(contract_path, contract)
        if not args.approve:
            high = set(profile()["basic_compute"].get("high_cost_bundle", []))
            for node in snapshot["nodes"]:
                if node["status"] == "pending" and node["capability_id"] in high and node.get("assigned_round") == control["active_round_id"]:
                    node["status"] = "cancelled"
                    node["finished_at"] = utc_now()
        _commit(root, control, snapshot, "high_cost_bundle_decided", {"approved": bool(args.approve), "rationale": args.rationale}, round_id=control["active_round_id"])
    _print_compact(control, high_cost_bundle_approved=bool(args.approve))
    return 0


def _canonical_result(node: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    result_path = Path(node["output_ref"]) / "result.json"
    result = read_json(result_path)
    schema_name = {"description": "description_result.schema.json", "clustering": "clustering_result.schema.json", "analysis": "analysis_result.schema.json"}[node["kind"]]
    validate(result, schema_name)
    expected_type = f"{node['kind']}_result"
    if result.get("document_type") != expected_type:
        raise ValueError(f"Canonical Result type mismatch for {node['node_id']}: expected {expected_type}")
    if result.get("node_id") != node["node_id"] or result.get("capability_id") != node["capability_id"]:
        raise ValueError(f"Canonical Result identity mismatch for {node['node_id']}")
    return result_path, result


def _primary_payload(node: dict[str, Any]) -> Path:
    result_path, result = _canonical_result(node)
    key = {"description": "payload", "clustering": "membership", "analysis": "primary_payload"}[node["kind"]]
    payload = result_path.parent / result[key]
    if not payload.is_file():
        raise FileNotFoundError(f"Canonical Result payload is missing for {node['node_id']}: {payload}")
    return payload


def _result_path(node: dict[str, Any]) -> Path:
    return _canonical_result(node)[0]


def _skill_output_dir(scratch: Path) -> Path:
    return scratch / "output"


def _validate_attempt_scratch(scratch: Path) -> None:
    if not scratch.exists():
        return
    entries = {path.name for path in scratch.iterdir()}
    if not entries:
        return
    allowed = {"execution_request.json"}
    if entries <= allowed:
        return
    raise FileExistsError(f"Unexpected pre-existing Attempt scratch: {scratch}")


def _request_artifact(role: str, path: Path, artifact_type: str, node: dict[str, Any] | None = None, result_path: Path | None = None) -> dict[str, Any]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Required Execution Request artifact is missing: {resolved}")
    item: dict[str, Any] = {
        "role": role,
        "artifact_type": artifact_type,
        "path": str(resolved),
        "sha256": file_hash(resolved),
    }
    if node:
        item.update({"source_node_id": node["node_id"], "source_capability_id": node["capability_id"]})
    if result_path:
        result_path = result_path.resolve()
        item.update({"result_path": str(result_path), "result_sha256": file_hash(result_path)})
    return item


def _validate_execution_request_artifacts(root: Path, control: dict[str, Any], request: dict[str, Any]) -> None:
    """Bind a signed Request to the bytes that will actually be consumed."""
    resolved_root = root.resolve()
    canonical_input = Path(control["run"]["input"]).resolve()

    def verify(item: dict[str, Any], path_key: str, hash_key: str) -> None:
        value = item.get(path_key)
        expected_hash = item.get(hash_key)
        if not value or not expected_hash:
            raise PermissionError(f"Execution Request input lacks {path_key}/{hash_key}: {item.get('role')}")
        path = Path(str(value)).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Execution Request input is missing: {path}")
        if path != canonical_input:
            try:
                path.relative_to(resolved_root)
            except ValueError as exc:
                raise PermissionError(f"Execution Request input escapes the Run Root: {path}") from exc
        actual_hash = file_hash(path)
        if not hmac.compare_digest(actual_hash, str(expected_hash)):
            raise PermissionError(
                f"Execution Request artifact hash mismatch for {item.get('role')}:{path_key}: {path}"
            )

    for item in request.get("inputs") or []:
        verify(item, "path", "sha256")
        if item.get("result_path") is not None or item.get("result_sha256") is not None:
            verify(item, "result_path", "result_sha256")


def _request_resource_options(control: dict[str, Any], node: dict[str, Any], capability: dict[str, Any]) -> dict[str, Any]:
    algorithm = str(capability.get("implementation", {}).get("algorithm", ""))
    available = _node_cpu_allocation(control, node)
    if algorithm == "mordred_3d":
        return {"compound_workers": min(MORDRED_3D_MAX_WORKERS, available), "available_cpu_cores": available}
    if algorithm == "tblite_xtb":
        all_available = _available_cpu_cores(control)
        cores = min(XTB_CORES_PER_COMPOUND, all_available)
        return {"cores_per_compound": cores, "compound_workers": max(1, all_available // cores), "available_cpu_cores": all_available}
    if algorithm == "chemberta_embedding":
        return {"cpu_threads": _available_cpu_cores(control)}
    return {}


def _execution_request(root: Path, control: dict[str, Any], snapshot: dict[str, Any], node: dict[str, Any], attempt_id: str, scratch: Path) -> dict[str, Any]:
    capability = catalog()[node["capability_id"]]
    request_contract = capability.get("conductor_request")
    if not isinstance(request_contract, dict):
        raise ValueError(f"Capability lacks conductor_request contract: {node['capability_id']}")
    adapter = request_contract.get("adapter")
    dataset = Path(control["run"]["input"])
    inputs = [_request_artifact("dataset", dataset, "endpoint_csv")]
    lookup = _node_lookup(snapshot)
    upstream = [lookup[item] for item in node["input_nodes"]]
    for source in upstream:
        if source["kind"] == "description":
            inputs.append(_request_artifact("description", _primary_payload(source), "description_payload", source, _result_path(source)))
        elif source["kind"] == "clustering":
            inputs.append(_request_artifact("clustering", _primary_payload(source), "cluster_membership", source, _result_path(source)))
        elif source["kind"] == "analysis":
            role = "analysis"
            payload = _primary_payload(source)
            if adapter == "projection_operator":
                role = "projection"
            elif adapter == "multidescription_operator" and (Path(source["output_ref"]) / "global_oof_predictions.csv").is_file():
                role = "global_model"
                payload = Path(source["output_ref"]) / "global_oof_predictions.csv"
            elif adapter == "mmp_operator" and (Path(source["output_ref"]) / "mmp_database.sqlite").is_file():
                role = "mmp_database"
                payload = Path(source["output_ref"]) / "mmp_database.sqlite"
            inputs.append(_request_artifact(role, payload, f"{role}_payload", source, _result_path(source)))
    if adapter == "meta_clustering":
        inputs.append(_request_artifact("cluster_membership_matrix", root / "runtime" / "cluster_membership.csv", "cluster_membership_matrix"))
    if adapter == "mmp_operator" and str(node.get("parameters", {}).get("role") or "global-build") != "global-build":
        matrix = root / "runtime" / "cluster_membership.csv"
        registry = root / "runtime" / "cluster_registry.jsonl"
        inputs.append(_request_artifact("cluster_membership_matrix", matrix, "cluster_membership_matrix"))
        if registry.is_file():
            inputs.append(_request_artifact("cluster_registry", registry, "cluster_registry"))
    defaults = capability.get("default_parameters", {})
    parameters = {**(defaults if isinstance(defaults, dict) else {}), **node.get("parameters", {})}
    subject = dict(node.get("scope") or {"mode": "global"})
    subject.setdefault("mode", "global")
    if parameters.get("target_cluster") and not subject.get("target_cluster_id"):
        subject["target_cluster_id"] = parameters["target_cluster"]
    if parameters.get("comparison_cluster") and not subject.get("comparison_cluster_id"):
        subject["comparison_cluster_id"] = parameters["comparison_cluster"]
    request = {
        "schema_version": "1.0.0",
        "identity": {
            "project": control["run"]["project"], "run_id": control["run"]["run_id"],
            "round_id": node["assigned_round"], "node_id": node["node_id"], "attempt_id": attempt_id,
            "capability_id": node["capability_id"], "skill_name": node["skill_name"],
        },
        "inputs": inputs,
        "columns": {"compound_id": control["run"]["id_column"], "smiles": _run_smiles_column(control), "endpoint": control["run"]["endpoint"]},
        "endpoint": {"higher_is_better": bool(control["run"]["higher_is_better"])},
        "subject": subject,
        "parameters": parameters,
        "resources": {
            "available_cpu_cores": _available_cpu_cores(control),
            "node_cpu_cores": _node_cpu_allocation(control, node),
            "native_thread_limit": _native_thread_limit(control, node),
            "skill_options": _request_resource_options(control, node, capability),
        },
        "output": {"directory": str(_skill_output_dir(scratch).resolve()), "overwrite": False},
        "created_at": utc_now(),
    }
    validate(request, "execution_request.schema.json")
    return request


def _skill_command(root: Path, control: dict[str, Any], snapshot: dict[str, Any], node: dict[str, Any], attempt_id: str, scratch: Path) -> list[str]:
    launcher = project_root() / ".claude" / "skills" / node["skill_name"] / "scripts" / "launch.py"
    request_path = scratch / "execution_request.json"
    if request_path.is_file():
        request = read_json(request_path)
        validate(request, "execution_request.schema.json")
        identity = request["identity"]
        expected = (node["node_id"], attempt_id, node["capability_id"], node["skill_name"])
        actual = (identity["node_id"], identity["attempt_id"], identity["capability_id"], identity["skill_name"])
        if actual != expected:
            raise PermissionError(f"Execution Request identity changed after preparation: {node['node_id']}")
        _validate_execution_request_artifacts(root, control, request)
    else:
        request = _execution_request(root, control, snapshot, node, attempt_id, scratch)
        write_json(request_path, request)
    return [RUNTIME_PYTHON_TOKEN, str(launcher), "--conductor-request", str(request_path.resolve())]


def _resolve_skill_command(command: list[str]) -> list[str]:
    if len(command) < 2 or command[0] != RUNTIME_PYTHON_TOKEN:
        raise PermissionError("Scientific command does not use the Runtime Python token")
    return [sys.executable, *command[1:]]


def _read_input_ids(control: dict[str, Any]) -> tuple[list[str], set[str]]:
    import pandas as pd

    frame = pd.read_csv(control["run"]["input"])
    id_column = _infer_compound_column(frame.columns)
    if not id_column:
        raise ValueError("Compound ID column could not be inferred from Run input")
    ids = frame[id_column].astype(str).tolist()
    endpoint = pd.to_numeric(frame[control["run"]["endpoint"]], errors="coerce")
    valid = set(frame.loc[endpoint.notna(), id_column].astype(str))
    return ids, valid


def _membership_ids(path: Path, cluster_id: str) -> set[str]:
    import pandas as pd

    frame = pd.read_csv(path, dtype={"compound_id": "string"})
    if {"compound_id", "cluster_id", "membership_value"} <= set(frame.columns):
        mask = (frame["cluster_id"].astype(str) == cluster_id) & (pd.to_numeric(frame["membership_value"], errors="coerce").fillna(0) > 0)
        return set(frame.loc[mask, "compound_id"].astype(str))
    if cluster_id in frame.columns:
        mask = frame[cluster_id].astype(str).str.lower().isin({"true", "1", "yes"})
        return set(frame.loc[mask, "compound_id"].astype(str))
    raise ValueError(f"Cluster {cluster_id} is absent from membership: {path}")


def _description_valid_ids(node: dict[str, Any]) -> set[str] | None:
    import pandas as pd

    path = _primary_payload(node)
    frame = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path, dtype={"compound_id": "string"})
    if "compound_id" not in frame.columns:
        return None
    excluded = {"compound_id", "input_smiles", "canonical_smiles", "mol_parse_ok", "description_error", "descriptor_error"}
    features = [column for column in frame.columns if column not in excluded]
    mask = frame[features].notna().any(axis=1) if features else frame["compound_id"].notna()
    if "mol_parse_ok" in frame.columns:
        mask &= frame["mol_parse_ok"].astype(str).str.lower().isin({"true", "1", "yes"})
    return set(frame.loc[mask, "compound_id"].astype(str))


def _analysis_subject(root: Path, control: dict[str, Any], snapshot: dict[str, Any], node: dict[str, Any], sample_count: int) -> dict[str, Any]:
    lookup = _node_lookup(snapshot)
    inputs = [lookup[item] for item in node["input_nodes"]]
    description_nodes = [item for item in inputs if item["kind"] == "description"]
    # Projection overlays receive a prior Analysis Node rather than the source
    # Description directly. Follow only Analysis ancestry here: traversing a
    # Clustering branch would incorrectly report the clustering representation
    # as the representation used by the Operator itself.
    pending_analysis = [item for item in inputs if item["kind"] == "analysis"]
    seen_analysis: set[str] = set()
    while pending_analysis:
        analysis = pending_analysis.pop()
        if analysis["node_id"] in seen_analysis:
            continue
        seen_analysis.add(analysis["node_id"])
        for parent_id in analysis["input_nodes"]:
            parent = lookup[parent_id]
            if parent["kind"] == "description" and all(existing["node_id"] != parent_id for existing in description_nodes):
                description_nodes.append(parent)
            elif parent["kind"] == "analysis":
                pending_analysis.append(parent)
    clustering_nodes = [item for item in inputs if item["kind"] == "clustering"]
    all_ids, endpoint_valid = _read_input_ids(control)
    scope_mode = node["scope"].get("mode", "global")
    cluster_ids = list(node["scope"].get("cluster_ids") or [])
    population = set(all_ids)
    overlap: dict[str, Any] | None = None
    if cluster_ids and clustering_nodes:
        sets = [_membership_ids(_primary_payload(clustering_nodes[0]), cluster_id) for cluster_id in cluster_ids]
        if scope_mode == "single_cluster":
            population = sets[0]
        elif scope_mode == "cluster_vs_cluster" and len(sets) == 2:
            intersection = sets[0] & sets[1]
            union = sets[0] | sets[1]
            overlap = {"count": len(intersection), "jaccard": len(intersection) / len(union) if union else 0.0, "independent": not intersection}
            population = union
    eligible = population & endpoint_valid
    for description in description_nodes:
        valid = _description_valid_ids(description)
        if valid is not None:
            eligible &= valid
    clustering_kind = "none"
    source_description_nodes: list[str] = []
    if clustering_nodes:
        cid = clustering_nodes[0]["capability_id"]
        clustering_kind = "structure" if cid in {"C001", "C002", "C003", "C004"} else "vector" if cid in {"C005", "C006", "C007", "C008", "C009", "C010"} else "categorical" if cid == "C011" else "meta"
        source_description_nodes = [item for item in clustering_nodes[0]["input_nodes"] if lookup[item]["kind"] == "description"]
    if sample_count > len(eligible):
        raise ValueError(f"Operator reported {sample_count} analyzed compounds, but only {len(eligible)} are eligible for the canonical subject")
    # Most Operators analyze every eligible compound. If an Operator applies an
    # additional internal filter, do not manufacture a biased ID subset merely
    # to match its count; bind the hash to the eligible cohort and reported n.
    subject_hash_basis = {"eligible_compound_ids": sorted(eligible), "reported_analyzed_count": int(sample_count)}
    subject = {"scope_mode": scope_mode, "cluster_ids": cluster_ids, "clustering_input_kind": clustering_kind, "cluster_source_description_nodes": source_description_nodes, "analysis_description_nodes": [item["node_id"] for item in description_nodes], "clustering_nodes": [item["node_id"] for item in clustering_nodes], "population_count": len(population), "endpoint_valid_count": len(population & endpoint_valid), "analyzed_count": int(sample_count), "excluded_count": max(0, len(population) - int(sample_count)), "compound_set_hash": value_hash(subject_hash_basis), "cluster_overlap": overlap}
    validate(subject, "analysis_subject.schema.json")
    return subject


def _copy_artifact(source: Path, destination: Path, expected_hash: str | None = None) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    if expected_hash and file_hash(source) != expected_hash:
        raise ValueError(f"Artifact hash mismatch: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _promote_mmp_payloads(
    skill_output: Path,
    temporary: Path,
    manifest: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
) -> dict[str, str]:
    payload_map = manifest.get("payloads") or {}
    if not isinstance(payload_map, dict) or any(not str(key).strip() for key in payload_map):
        raise ValueError("A014 manifest payloads must be a non-empty logical-name mapping")
    declared = set(payload_map.values())
    if not declared or not declared <= MMP_PAYLOAD_NAMES:
        raise ValueError(f"A014 manifest declares unsupported payloads: {sorted(declared - MMP_PAYLOAD_NAMES)}")
    if len(declared) != len(payload_map):
        raise ValueError("A014 manifest declares the same payload basename more than once")
    promoted: dict[str, str] = {}
    by_path = {item["path"]: item for item in artifacts.values()}
    for logical_name, name in sorted(payload_map.items()):
        if Path(name).name != name:
            raise ValueError(f"A014 payload must use a stable basename: {name}")
        event_artifact = by_path.get(name)
        if not event_artifact:
            raise ValueError(f"A014 execution event does not declare payload: {name}")
        _copy_artifact(
            _skill_artifact_path(skill_output, name), temporary / name,
            event_artifact.get("sha256"),
        )
        promoted[str(logical_name)] = name
    if "mmp_pair_detail.csv" in declared:
        import pandas as pd
        import sqlite3

        required = {"mmp_database.sqlite", "mmp_storage_profile.json"}
        if not required <= declared:
            raise ValueError("A014 Global payload is missing stable SQLite or storage profile")
        csv_rows = len(pd.read_csv(temporary / "mmp_pair_detail.csv"))
        from contextlib import closing
        with closing(sqlite3.connect(temporary / "mmp_database.sqlite")) as connection:
            database_rows = int(connection.execute("SELECT COUNT(*) FROM mmp_pairs").fetchone()[0])
        storage = read_json(temporary / "mmp_storage_profile.json")
        profile_rows = int((storage.get("table_rows") or {}).get("mmp_pairs", -1))
        if len({csv_rows, database_rows, profile_rows}) != 1:
            raise ValueError(f"A014 payload row-count mismatch: CSV={csv_rows}, DB={database_rows}, profile={profile_rows}")
    return promoted


def _skill_artifact_path(skill_output: Path, declared_path: str) -> Path:
    relative = Path(declared_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Skill artifact path must remain inside the Attempt output: {declared_path}")
    root = skill_output.resolve()
    resolved = (root / relative).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"Skill artifact escaped the Attempt output: {declared_path}")
    return resolved


def _promote_clusters(root: Path, snapshot: dict[str, Any], node: dict[str, Any], skill_output: Path, output: Path, manifest: dict[str, Any], artifacts: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    import pandas as pd

    for required in ("cluster_registry", "cluster_membership", "clustering_diagnostics"):
        if required not in artifacts:
            raise ValueError(f"Clustering execution event is missing {required}")
    registry = read_json(_skill_artifact_path(skill_output, artifacts["cluster_registry"]["path"]))
    membership = pd.read_csv(_skill_artifact_path(skill_output, artifacts["cluster_membership"]["path"]), dtype={"compound_id": "string"})
    required_columns = {"compound_id", "cluster_id", "membership_value"}
    if not required_columns.issubset(membership.columns):
        raise ValueError(f"Clustering membership is missing columns: {sorted(required_columns - set(membership.columns))}")
    if membership.duplicated(["compound_id", "cluster_id"]).any():
        raise ValueError("Clustering membership contains duplicate compound/Cluster rows")
    if not isinstance(registry, list):
        raise ValueError("Clustering registry must be a list")
    source_membership = pd.to_numeric(membership["membership_value"], errors="coerce").fillna(0)
    mapping: dict[str, str] = {}
    registry_rows: list[dict[str, Any]] = []
    lookup = _node_lookup(snapshot)
    source_description_nodes = [item for item in node["input_nodes"] if lookup[item]["kind"] == "description"]
    source_description_capabilities = [lookup[item]["capability_id"] for item in source_description_nodes]
    for row in registry:
        count = int(row.get("compound_count", 0))
        local = str(row.get("local_cluster_id") or row.get("cluster_id"))
        observed_count = int(((membership["cluster_id"].astype(str) == local) & (source_membership > 0)).sum())
        if count != observed_count:
            raise ValueError(f"Clustering registry count mismatch for {local}: expected {count}, observed {observed_count}")
        if count < 5:
            continue
        snapshot["counters"]["cluster"] += 1
        cluster_id = f"C{snapshot['counters']['cluster']:06d}"
        mapping[local] = cluster_id
        canonical_membership = Path(node["output_ref"]) / "membership.csv"
        registry_rows.append({"cluster_id": cluster_id, "local_cluster_id": local, "source_node_id": node["node_id"], "clustering_capability_id": node["capability_id"], "source_description_node_ids": source_description_nodes, "source_description_capability_ids": source_description_capabilities, "cluster_label": row.get("cluster_label") or local, "compound_count": count, "membership_path": str(canonical_membership.relative_to(root)), "status": "active", "created_at": utc_now()})
    membership["cluster_id"] = membership["cluster_id"].astype(str).map(mapping).fillna("")
    membership["membership_value"] = pd.to_numeric(membership["membership_value"], errors="coerce").fillna(0)
    membership.loc[membership["cluster_id"].eq(""), "membership_value"] = 0
    membership.to_csv(output / "membership.csv", index=False)
    input_kind = "structure" if node["capability_id"] in {"C001", "C002", "C003", "C004"} else "vector" if node["capability_id"] in {"C005", "C006", "C007", "C008", "C009", "C010"} else "categorical" if node["capability_id"] == "C011" else "meta"
    result = {"document_type": "clustering_result", "schema_version": "1.0.0", "node_id": node["node_id"], "capability_id": node["capability_id"], "membership": "membership.csv", "cluster_count": len(registry_rows), "selection_status": manifest.get("selection_status", "selected"), "quality_flags": manifest.get("quality_flags") or [], "input_kind": input_kind, "source_description_nodes": [item for item in node["input_nodes"] if _node_lookup(snapshot)[item]["kind"] == "description"], "metric": manifest.get("natural_metric"), "payloads": {}, "created_at": utc_now()}
    for artifact_type, output_name in (("clustering_diagnostics", "clustering_diagnostics.csv"), ("distance_profile", "distance_profile.json")):
        if artifact_type in artifacts:
            _copy_artifact(_skill_artifact_path(skill_output, artifacts[artifact_type]["path"]), output / output_name, artifacts[artifact_type]["sha256"])
            result["payloads"][output_name.rsplit(".", 1)[0]] = output_name
    validate(result, "clustering_result.schema.json")
    return result, registry_rows


def _rebuild_cluster_matrix(root: Path) -> None:
    import pandas as pd

    control = read_json(control_path(root))
    ids, _valid = _read_input_ids(control)
    matrix = pd.DataFrame({"compound_id": ids})
    registry = {row["cluster_id"]: row for row in read_jsonl(root / "runtime" / "cluster_registry.jsonl") if row.get("status", "active") == "active"}
    by_membership: dict[str, list[str]] = defaultdict(list)
    for cluster_id, row in registry.items():
        by_membership[row["membership_path"]].append(cluster_id)
    for relative, cluster_ids in by_membership.items():
        frame = pd.read_csv(root / relative, dtype={"compound_id": "string"})
        for cluster_id in cluster_ids:
            members = set(frame.loc[(frame["cluster_id"].astype(str) == cluster_id) & (pd.to_numeric(frame["membership_value"], errors="coerce").fillna(0) > 0), "compound_id"].astype(str))
            matrix[cluster_id] = matrix["compound_id"].astype(str).isin(members)
    matrix.to_csv(root / "runtime" / "cluster_membership.csv", index=False)


def _operator_report_html(control: dict[str, Any], node: dict[str, Any], subject: dict[str, Any], summary: dict[str, Any], detail_name: str | None, snapshot: dict[str, Any]) -> str:
    import html

    scope_label = {"global": "Global", "single_cluster": "Cluster-local", "global_vs_cluster": "Global対Cluster比較", "cluster_vs_cluster": "Cluster間比較", "multi_scope": "複数scope", "projection": "Projection"}.get(subject["scope_mode"], subject["scope_mode"])
    clusters = ", ".join(subject["cluster_ids"]) or "—"
    lookup = _node_lookup(snapshot)
    descriptions = ", ".join(f"{lookup[item]['capability_id']} ({item})" for item in subject["analysis_description_nodes"] if item in lookup) or "—"
    source_descriptions = ", ".join(f"{lookup[item]['capability_id']} ({item})" for item in subject["cluster_source_description_nodes"] if item in lookup) or "—"
    clustering_methods = ", ".join(f"{lookup[item]['capability_id']} ({item})" for item in subject["clustering_nodes"] if item in lookup) or "—"
    link = f"<p><a href='{html.escape(detail_name)}'>詳細Operator reportを開く</a></p>" if detail_name else ""
    metrics = "".join(f"<tr><th>{html.escape(str(key))}</th><td>{html.escape(str(value))}</td></tr>" for key, value in list((summary.get("key_metrics") or {}).items())[:30])
    return f"<!doctype html><html lang='ja'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{html.escape(node['capability_id'])} report</title><style>body{{margin:0;background:#f4f3ef;color:#263238;font-family:system-ui,sans-serif}}main{{max-width:1080px;margin:auto;padding:32px}}header{{border-left:7px solid #526b72;background:#fff;padding:20px 24px}}.facts{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;margin:20px 0}}.fact,section{{background:#fff;border:1px solid #d7d9d5;border-radius:8px;padding:14px}}small{{color:#5e6b70}}table{{border-collapse:collapse;width:100%}}th,td{{padding:8px;border-bottom:1px solid #ddd;text-align:left}}@media print{{body{{background:#fff}}main{{padding:0}}}}</style></head><body><main><header><small>CONDUCTOR Operator Result</small><h1>{html.escape(node['capability_id'])}: {html.escape(summary.get('headline') or '解析結果')}</h1></header><div class='facts'><div class='fact'><b>対象</b><br>{scope_label}</div><div class='fact'><b>Cluster</b><br>{html.escape(clusters)}</div><div class='fact'><b>Clustering手法</b><br>{html.escape(clustering_methods)}</div><div class='fact'><b>Cluster生成Description</b><br>{html.escape(source_descriptions)}</div><div class='fact'><b>解析Description</b><br>{html.escape(descriptions)}</div><div class='fact'><b>Endpoint</b><br>{html.escape(control['run']['endpoint'])}</div><div class='fact'><b>母集団 / endpoint有効 / 実解析 / 除外</b><br>{subject['population_count']} / {subject['endpoint_valid_count']} / {subject['analyzed_count']} / {subject['excluded_count']}</div><div class='fact'><b>Metric</b><br>{html.escape(str(summary.get('metric') or '—'))}</div></div><section><h2>主要数値</h2><table>{metrics}</table>{link}</section></main></body></html>"


def _adapt_success(root: Path, control: dict[str, Any], snapshot: dict[str, Any], node: dict[str, Any], attempt: dict[str, Any], skill_output: Path, event: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts = {item["type"]: item for item in event["artifacts"]}
    if len(artifacts) != len(event["artifacts"]):
        raise ValueError("Skill execution event contains duplicate artifact types")
    if "manifest" not in artifacts:
        raise ValueError("Skill execution event does not declare a stage Manifest")
    manifest = read_json(_skill_artifact_path(skill_output, artifacts["manifest"]["path"]))
    validate(manifest, "artifact_manifest.schema.json")
    expected_stage = {"description": "description", "clustering": "clustering", "analysis": "analysis"}[node["kind"]]
    if manifest.get("artifact_stage") != expected_stage or manifest.get("capability_id") != node["capability_id"]:
        raise ValueError("Skill stage Manifest identity does not match the Node")
    if manifest.get("node_id") != node["node_id"] or manifest.get("attempt_id") != attempt["attempt_id"]:
        raise ValueError("Skill stage Manifest Node or Attempt identity mismatch")
    final = Path(node["output_ref"])
    temporary = final.with_name(f".{final.name}.{attempt['attempt_id']}.commit")
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)
    result_cards: list[dict[str, Any]] = []
    cluster_registry_rows: list[dict[str, Any]] = []
    if node["kind"] == "description":
        primary = artifacts["description"]
        payload_name = "features" + Path(primary["path"]).suffix.lower()
        _copy_artifact(_skill_artifact_path(skill_output, primary["path"]), temporary / payload_name, primary["sha256"])
        capability = catalog()[node["capability_id"]]
        expected_semantics = capability.get("value_semantics")
        expected_metric = capability.get("natural_metric")
        if manifest.get("capability_id") != node["capability_id"]:
            raise ValueError("Description Artifact Manifest capability does not match the Node")
        if manifest.get("value_semantics") != expected_semantics or manifest.get("natural_metric") != expected_metric:
            raise ValueError("Description Artifact Manifest semantics or metric conflicts with the Catalog")
        if int(manifest.get("feature_count", -1)) != len(manifest.get("feature_columns") or []):
            raise ValueError("Description Artifact Manifest feature_count does not match feature_columns")
        result = {"document_type": "description_result", "schema_version": "1.0.0", "node_id": node["node_id"], "capability_id": node["capability_id"], "payload": payload_name, "row_count": int(manifest.get("row_count", 0)), "feature_count": int(manifest.get("feature_count", 0)), "value_semantics": manifest.get("value_semantics", "dense_continuous"), "natural_metric": manifest.get("natural_metric"), "feature_columns": manifest.get("feature_columns") or [], "quality_flags": ["row_errors"] if manifest.get("errors") else [], "created_at": utc_now()}
        validate(result, "description_result.schema.json")
        write_json(temporary / "result.json", result)
    elif node["kind"] == "clustering":
        result, cluster_registry_rows = _promote_clusters(root, snapshot, node, skill_output, temporary, manifest, artifacts)
        write_json(temporary / "result.json", result)
        node["result_quality"] = {"validation_passed": True, "eligible_for_downstream": result["selection_status"] == "selected" and result["cluster_count"] > 0, "quality_flags": result["quality_flags"] or (["no_usable_clusters"] if result["cluster_count"] == 0 else [])}
    elif node["kind"] == "analysis":
        primary = artifacts["operator_result"]
        mmp_payloads: dict[str, str] = {}
        if node["capability_id"] == "A014":
            mmp_payloads = _promote_mmp_payloads(skill_output, temporary, manifest, artifacts)
            primary_name = str(manifest.get("output") or "")
            if primary_name not in mmp_payloads.values() or primary_name != primary["path"]:
                raise ValueError("A014 primary output is not a declared promoted payload")
        else:
            primary_name = "analysis" + Path(primary["path"]).suffix.lower()
            _copy_artifact(_skill_artifact_path(skill_output, primary["path"]), temporary / primary_name, primary["sha256"])
        summary = read_json(_skill_artifact_path(skill_output, artifacts["operator_summary"]["path"]))
        validate(summary, "operator_summary.schema.json")
        subject = _analysis_subject(root, control, snapshot, node, int(summary.get("sample_count", 0)))
        detail_name = None
        if "operator_report" in artifacts:
            detail_name = "detail.html"
            _copy_artifact(_skill_artifact_path(skill_output, artifacts["operator_report"]["path"]), temporary / detail_name, artifacts["operator_report"]["sha256"])
        report_name = "report.html"
        atomic_bytes(temporary / report_name, _operator_report_html(control, node, subject, summary, detail_name, snapshot).encode("utf-8"))
        result_ref = f"{node['node_id']}@{attempt['attempt_id']}"
        artifact_links = {
            "result": _run_relative_artifact(root, final / primary_name),
            "report": _run_relative_artifact(root, final / report_name),
            "detail": _run_relative_artifact(root, final / detail_name) if detail_name else None,
        }
        if "mmp_database" in mmp_payloads:
            artifact_links["mmp_database"] = _run_relative_artifact(root, final / mmp_payloads["mmp_database"])
        if "mmp_reference_cards" in mmp_payloads:
            artifact_links["mmp_reference_cards"] = _run_relative_artifact(root, final / mmp_payloads["mmp_reference_cards"])
        card_quality_flags = ["negative_result"] if (summary.get("key_metrics") or {}).get("negative_result") is True else []
        card = {"schema_version": "1.0.0", "result_ref": result_ref, "node_id": node["node_id"], "capability_id": node["capability_id"], "round_id": node["assigned_round"], "analysis_subject": subject, "endpoint": {"column": control["run"]["endpoint"], "higher_is_better": control["run"]["higher_is_better"], "unit": control["run"].get("endpoint_unit"), "transform": control["run"].get("endpoint_transform")}, "metric": summary.get("metric"), "headline": str(summary.get("headline") or ""), "key_metrics": summary.get("key_metrics") or {}, "validation_passed": True, "eligible_for_downstream": True, "quality_flags": card_quality_flags, "limitations": summary.get("limitations") or [], "artifact_links": artifact_links, "attention": "watch", "created_at": utc_now()}
        validate(card, "result_card.schema.json")
        write_json(temporary / "result_card.json", card)
        result_card_files = ["result_card.json"]
        result_cards.append(card)
        if "operator_summary_collection" in artifacts:
            collection = read_json(_skill_artifact_path(skill_output, artifacts["operator_summary_collection"]["path"]))
            write_json(temporary / "cluster_result_cards_source.json", collection)
            for local_summary in collection:
                cluster_id = str((local_summary.get("scope_context") or {}).get("cluster_ids", [None])[0])
                if not cluster_id or not cluster_id.startswith("C"):
                    raise ValueError("Cluster survey summary lacks a canonical Cluster ID")
                local_node = {**node, "scope": {"mode": "single_cluster", "cluster_ids": [cluster_id]}}
                local_subject = _analysis_subject(root, control, snapshot, local_node, int(local_summary.get("sample_count", 0)))
                source_payload = _skill_artifact_path(skill_output, local_summary["primary_artifact"]["path"])
                local_relative = Path("clusters") / cluster_id / "model_comparison.csv"
                _copy_artifact(source_payload, temporary / local_relative, local_summary["primary_artifact"].get("sha256"))
                local_card = {"schema_version": "1.0.0", "result_ref": str(local_summary["result_ref"]), "node_id": node["node_id"], "capability_id": node["capability_id"], "round_id": node["assigned_round"], "analysis_subject": local_subject, "endpoint": {"column": control["run"]["endpoint"], "higher_is_better": control["run"]["higher_is_better"], "unit": control["run"].get("endpoint_unit"), "transform": control["run"].get("endpoint_transform")}, "metric": local_summary.get("metric"), "headline": str(local_summary.get("headline") or ""), "key_metrics": local_summary.get("key_metrics") or {}, "validation_passed": True, "eligible_for_downstream": True, "quality_flags": [], "limitations": local_summary.get("limitations") or [], "artifact_links": {"result": _run_relative_artifact(root, final / local_relative), "report": _run_relative_artifact(root, final / report_name), "detail": _run_relative_artifact(root, final / detail_name) if detail_name else None}, "attention": "watch", "created_at": utc_now()}
                validate(local_card, "result_card.schema.json")
                card_file = f"result_card_{cluster_id}.json"
                write_json(temporary / card_file, local_card)
                result_card_files.append(card_file)
                result_cards.append(local_card)
        result_payloads = {"detail_report": detail_name} if detail_name else {}
        result_payloads.update(mmp_payloads)
        result = {"document_type": "analysis_result", "schema_version": "1.0.0", "node_id": node["node_id"], "capability_id": node["capability_id"], "analysis_subject": subject, "primary_payload": primary_name, "report": report_name, "result_cards": result_card_files, "payloads": result_payloads, "created_at": utc_now()}
        validate(result, "analysis_result.schema.json")
        write_json(temporary / "result.json", result)
        for name in ("global_oof_predictions.csv", "cluster_model_comparison.csv", "projection.png"):
            if (skill_output / name).is_file():
                _copy_artifact(skill_output / name, temporary / name)
    else:
        raise ValueError("Interpretation is committed through the dedicated gate")
    if final.exists():
        raise FileExistsError(f"Committed Node output already exists: {final}")
    final.parent.mkdir(parents=True, exist_ok=True)
    os.replace(temporary, final)
    if node["kind"] == "clustering":
        known_clusters = {row["cluster_id"] for row in read_jsonl(root / "runtime" / "cluster_registry.jsonl")}
        for row in cluster_registry_rows:
            if row["cluster_id"] not in known_clusters:
                append_jsonl_fsync(root / "runtime" / "cluster_registry.jsonl", row)
                known_clusters.add(row["cluster_id"])
        _rebuild_cluster_matrix(root)
    known_results = {row["result_ref"] for row in read_jsonl(root / "runtime" / "result_index.jsonl")}
    for card in result_cards:
        _validate_result_card_links(root, card)
        if card["result_ref"] not in known_results:
            append_jsonl_fsync(root / "runtime" / "result_index.jsonl", card)
            known_results.add(card["result_ref"])
    return result_cards


def _run_one(
    command: list[str],
    log_path: Path,
    process_path: Path,
    timeout_seconds: int,
    contract_command_hash: str,
    cpu_cores: int = 1,
    available_cpu_cores: int | None = None,
    native_thread_limit: int | None = None,
) -> dict[str, Any]:
    started = utc_now()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    process: subprocess.Popen[str] | None = None
    process_identity = {
        "command_hash": contract_command_hash,
        "resolved_command_hash": value_hash(command),
        "runtime_python": command[0],
    }

    def terminate_tree(target: subprocess.Popen[Any], grace_seconds: int = 10) -> None:
        if target.poll() is not None:
            return
        if os.name == "posix":
            try:
                os.killpg(os.getpgid(target.pid), signal.SIGTERM)
            except ProcessLookupError:
                return
        elif os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(target.pid), "/T"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
        else:
            target.terminate()
        try:
            target.wait(timeout=grace_seconds)
            return
        except subprocess.TimeoutExpired:
            pass
        if os.name == "posix":
            try:
                os.killpg(os.getpgid(target.pid), signal.SIGKILL)
            except ProcessLookupError:
                return
        elif os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(target.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
        else:
            target.kill()
        try:
            target.wait(timeout=10)
        except subprocess.TimeoutExpired:
            target.kill()

    try:
        attempt_tmp = process_path.parent / "tmp"
        attempt_tmp.mkdir(parents=True, exist_ok=True)
        process_env = os.environ.copy()
        process_env["CONDUCTOR_ATTEMPT_TMP"] = str(attempt_tmp.resolve())
        process_env["CONDUCTOR_NODE_CPU_CORES"] = str(cpu_cores)
        process_env["CONDUCTOR_AVAILABLE_CPU_CORES"] = str(available_cpu_cores or cpu_cores)
        thread_limit = native_thread_limit or cpu_cores
        process_env["CONDUCTOR_NATIVE_THREAD_LIMIT"] = str(thread_limit)
        for name in (
            "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
            "BLIS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS",
            "NUMBA_NUM_THREADS", "RAYON_NUM_THREADS",
        ):
            process_env[name] = str(thread_limit)
        popen_options: dict[str, Any] = {}
        if os.name == "posix":
            popen_options["start_new_session"] = True
        elif os.name == "nt":
            popen_options["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        with log_path.open("w", encoding="utf-8", errors="replace") as log_handle:
            process = subprocess.Popen(
                command, cwd=project_root(), env=process_env, text=True,
                stdout=log_handle, stderr=subprocess.STDOUT, **popen_options,
            )
            write_json(process_path, {"pid": process.pid, "process_group_id": process.pid, "started_at": started, **process_identity})
            process.wait(timeout=timeout_seconds)
        finished = utc_now()
        write_json(process_path, {"pid": process.pid, "process_group_id": process.pid, "started_at": started, "finished_at": finished, "returncode": process.returncode, **process_identity})
        return {"returncode": process.returncode, "timed_out": False, "started_at": started, "finished_at": finished}
    except subprocess.TimeoutExpired:
        if process is not None:
            terminate_tree(process)
        with log_path.open("a", encoding="utf-8") as log_handle:
            log_handle.write("\nTIMEOUT\n")
        finished = utc_now()
        write_json(process_path, {"pid": process.pid if process else None, "process_group_id": process.pid if process else None, "started_at": started, "finished_at": finished, "returncode": 124, "timed_out": True, **process_identity})
        return {"returncode": 124, "timed_out": True, "started_at": started, "finished_at": finished}
    except Exception as exc:
        if process is not None and process.poll() is None:
            terminate_tree(process)
        with log_path.open("a", encoding="utf-8") as log_handle:
            log_handle.write(f"\nPROCESS_START_OR_WAIT_FAILURE: {exc}\n")
        finished = utc_now()
        previous = read_json(process_path) if process_path.is_file() else {"started_at": started, **process_identity}
        write_json(process_path, {**previous, "finished_at": finished, "returncode": 125, "runner_error": str(exc)})
        return {"returncode": 125, "timed_out": False, "started_at": started, "finished_at": finished, "runner_error": str(exc)}


def _classify_execution_failure(log_path: Path, outcome: dict[str, Any], error: Exception) -> tuple[str, bool]:
    text = ""
    if log_path.is_file():
        with log_path.open("rb") as handle:
            handle.seek(max(0, log_path.stat().st_size - 12000))
            text = handle.read(12000).decode("utf-8", errors="replace").lower()
    message = f"{error} {outcome.get('runner_error') or ''}".lower()
    combined = f"{message}\n{text}"
    if outcome.get("timed_out"):
        return "transient_process_failure", True
    if any(token in combined for token in ("unrecognized arguments", "unknown option", "no such option", "argument contract")):
        return "argument_contract_mismatch", False
    if any(token in combined for token in ("pixi", "environment", "conda", "uv cache")) and outcome.get("returncode") in {1, 125, 127}:
        return "environment_initialization_failure", True
    if any(token in combined for token in ("working directory", "no such file", "cannot find the path", "file not found")):
        return "path_or_working_directory_mismatch", False
    if any(token in combined for token in ("missing column", "column not found", "required column", "csv")):
        return "input_format_or_column_mismatch", False
    if any(token in combined for token in ("schema", "identity or status mismatch", "missing or invalid skill artifact")):
        return "payload_validation_failure", False
    if outcome.get("returncode") in {125}:
        return "transient_process_failure", True
    return "non_recoverable_implementation_failure", False


def _write_failure_packet(
    root: Path,
    node: dict[str, Any],
    attempt: dict[str, Any],
    outcome: dict[str, Any],
    error: Exception,
) -> Path:
    log_path = root / attempt["log"]
    classification, recoverable = _classify_execution_failure(log_path, outcome, error)
    packet = {
        "schema_version": "1.0.0",
        "protocol_version": PROTOCOL_VERSION,
        "node_id": node["node_id"],
        "attempt_id": attempt["attempt_id"],
        "round_id": node["assigned_round"],
        "capability_id": node["capability_id"],
        "classification": classification,
        "recoverable": recoverable,
        "attempt_count": len(node.get("attempts") or []),
        "attempt_limit": MAX_EXECUTION_ATTEMPTS,
        "error": str(error)[:2000],
        "log_pointer": attempt["log"],
        "scratch_pointer": str(Path(attempt["scratch"]).relative_to(root)),
        "created_at": utc_now(),
    }
    validate(packet, "failure_packet.schema.json")
    path = Path(attempt["scratch"]) / "failure_packet.json"
    write_json(path, packet)
    return path


def _execute_packet_batch(args: argparse.Namespace) -> int:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    root = resolve_root(args.run_root)
    packet_path = Path(args.packet).resolve()
    selected: list[tuple[dict[str, Any], dict[str, Any], Path, list[str]]] = []
    prepared_commands: list[tuple[dict[str, Any], str, Path, list[str], list[str]]] = []
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        executor_packet = _validate_execution_packet(root, control, packet_path)
        args.timeout_minutes = int(executor_packet["timeout_minutes"])
        args.clean_scratch = bool(executor_packet["clean_scratch"])
        if args.timeout_minutes < 1:
            raise ValueError("Node timeout must be at least one minute")
        soft_stop = parse_time(snapshot["rounds"][control["active_round_id"]].get("soft_stop_at"))
        now = datetime.now(timezone.utc)
        if soft_stop and now >= soft_stop:
            raise ValueError("Scientific execution window has ended; refresh control and enter finalizing")
        remaining_seconds = max(1, int((soft_stop - now).total_seconds())) if soft_stop else args.timeout_minutes * 60
        execution_timeout_seconds = min(args.timeout_minutes * 60, remaining_seconds)
        runnable = {node["node_id"]: node for node in _runnable(control, snapshot)}
        requested = list(executor_packet["node_ids"])
        if not requested:
            raise ValueError("No runnable Nodes")
        if set(requested) - set(runnable):
            raise ValueError(f"Requested Nodes are not currently runnable: {sorted(set(requested) - set(runnable))}")
        requested = _select_execution_nodes(requested, runnable, control)
        contract_lookup = {item["node_id"]: item for item in executor_packet.get("execution_contracts", [])}
        for node_id in requested:
            node = runnable[node_id]
            attempt_id = f"ATT{len(node['attempts']) + 1:04d}"
            scratch = root / "runtime" / "scratch" / node["assigned_round"] / node_id / attempt_id
            skill_output = _skill_output_dir(scratch)
            command = _skill_command(root, control, snapshot, node, attempt_id, scratch)
            contract = contract_lookup.get(node_id)
            request_path = scratch / "execution_request.json"
            if not contract or contract["attempt_id"] != attempt_id or Path(contract["scratch"]).resolve() != scratch.resolve() or Path(contract["skill_output"]).resolve() != skill_output.resolve() or contract["command_hash"] != value_hash(command) or Path(contract["request_path"]).resolve() != request_path.resolve() or contract["request_hash"] != value_hash(read_json(request_path)):
                raise PermissionError(f"Execution contract changed after packet creation: {node_id}")
            resolved_command = _resolve_skill_command(command)
            _validate_attempt_scratch(scratch)
            if skill_output.exists():
                raise FileExistsError(f"Skill output directory must be absent before execution: {skill_output}")
            prepared_commands.append((node, attempt_id, scratch, command, resolved_command))
        for node, attempt_id, scratch, command, resolved_command in prepared_commands:
            if not scratch.exists():
                scratch.mkdir(parents=True, exist_ok=False)
            attempt = {"attempt_id": attempt_id, "status": "running", "started_at": utc_now(), "finished_at": None, "command_argv": command, "scratch": str(scratch), "log": str((root / "runtime" / "logs" / f"{node['node_id']}_{attempt_id}.log").relative_to(root))}
            node["attempts"].append(attempt)
            node["current_attempt_id"] = attempt_id
            node["status"] = "running"
            selected.append((node, attempt, scratch, resolved_command))
        now = datetime.now(timezone.utc)
        control["lease"]["expires_at"] = (
            now
            + timedelta(
                seconds=execution_timeout_seconds,
                minutes=EXECUTION_LEASE_GRACE_MINUTES,
            )
        ).isoformat()
        _commit(root, control, snapshot, "batch_started", {"nodes": [{"node_id": node["node_id"], "attempt_id": attempt["attempt_id"], "command_argv": attempt["command_argv"]} for node, attempt, _scratch, _resolved_command in selected], "execution_timeout_seconds": execution_timeout_seconds}, round_id=control["active_round_id"])
    outcomes: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=len(selected)) as executor:
        futures = {
            executor.submit(
                _run_one,
                command,
                root / attempt["log"],
                scratch / "process.json",
                execution_timeout_seconds,
                value_hash(attempt["command_argv"]),
                _node_cpu_allocation(control, node),
                _available_cpu_cores(control),
                _native_thread_limit(control, node),
            ): (node, attempt, scratch)
            for node, attempt, scratch, command in selected
        }
        for future in as_completed(futures):
            node, attempt, scratch = futures[future]
            outcomes[node["node_id"]] = {**future.result(), "attempt_id": attempt["attempt_id"], "scratch": str(scratch)}
    committed: list[str] = []
    failed: list[str] = []
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        _require_executor_followup(control, executor_packet)
        lookup = _node_lookup(snapshot)
        event_payload: list[dict[str, Any]] = []
        for node_id, outcome in outcomes.items():
            node = lookup[node_id]
            attempt = next(item for item in node["attempts"] if item["attempt_id"] == outcome["attempt_id"])
            scratch = Path(outcome["scratch"])
            skill_output = _skill_output_dir(scratch)
            try:
                if outcome["returncode"] != 0:
                    raise RuntimeError(f"Skill exited with code {outcome['returncode']}")
                event_path = skill_output / "execution_event.json"
                if not event_path.is_file():
                    raise FileNotFoundError("Skill did not produce execution_event.json")
                event = read_json(event_path)
                validate(event, "execution_event.schema.json")
                if event.get("node_id") != node_id or event.get("attempt_id") != attempt["attempt_id"] or event.get("round_id") != node["assigned_round"] or event.get("capability_id") != node["capability_id"] or event.get("status") != "succeeded":
                    raise ValueError("Skill event identity or status mismatch")
                for artifact in event.get("artifacts") or []:
                    source = _skill_artifact_path(skill_output, artifact["path"])
                    if not source.is_file() or file_hash(source) != artifact["sha256"]:
                        raise ValueError(f"Missing or invalid Skill artifact: {artifact['path']}")
                cards = _adapt_success(root, control, snapshot, node, attempt, skill_output, event)
                node.update({"status": "succeeded", "current_attempt_id": None, "finished_at": utc_now(), "result_quality": node.get("result_quality") or {"validation_passed": True, "eligible_for_downstream": True, "quality_flags": []}})
                attempt.update({"status": "succeeded", "finished_at": node["finished_at"]})
                committed.append(node_id)
                event_payload.append({"node_id": node_id, "attempt_id": attempt["attempt_id"], "status": "succeeded", "result_refs": [card["result_ref"] for card in cards]})
                if args.clean_scratch:
                    shutil.rmtree(scratch, ignore_errors=True)
            except Exception as exc:
                failure_path = _write_failure_packet(root, node, attempt, outcome, exc)
                failure_packet = read_json(failure_path)
                node.update({"status": "failed", "current_attempt_id": None, "finished_at": utc_now(), "result_quality": {"validation_passed": False, "eligible_for_downstream": False, "quality_flags": ["technical_failure"]}})
                attempt.update({"status": "failed", "finished_at": node["finished_at"], "error": str(exc), "returncode": outcome["returncode"], "failure_classification": failure_packet["classification"], "failure_packet": str(failure_path.relative_to(root))})
                failed.append(node_id)
                event_payload.append({"node_id": node_id, "attempt_id": attempt["attempt_id"], "status": "failed", "failure_code": failure_packet["classification"], "recoverable": failure_packet["recoverable"], "failure_pointer": str(failure_path.relative_to(root))})
        control["lease"]["heartbeat_at"] = utc_now()
        control["lease"]["expires_at"] = (
            datetime.now(timezone.utc) + timedelta(minutes=DEFAULT_LEASE_MINUTES)
        ).isoformat()
        _commit(root, control, snapshot, "batch_reconciled", {"outcomes": event_payload}, round_id=control["active_round_id"])
        working = _write_working_set(root, control, snapshot)
    detail_dir = root / "runtime" / "logs"
    _print_compact(
        control,
        detail_pointer=str(detail_dir.relative_to(root)),
        succeeded_count=len(committed),
        failed_count=len(failed),
        affected_node_ids=(committed + failed)[:50],
        packet_id=executor_packet.get("packet_id"),
    )
    return 1 if failed and not committed else 0


def cmd_execute_packet(args: argparse.Namespace) -> int:
    # Delegate to the same transactional implementation.  Packet validation
    # supplies the signed lease identity without exposing the lease token.
    args.timeout_minutes = DEFAULT_EXECUTION_TIMEOUT_MINUTES
    args.clean_scratch = True
    return _execute_packet_batch(args)


def _recover_promoted_output(root: Path, snapshot: dict[str, Any], node: dict[str, Any]) -> list[str]:
    import pandas as pd

    final = Path(node["output_ref"])
    result = read_json(final / "result.json")
    validate(result, {"description": "description_result.schema.json", "clustering": "clustering_result.schema.json", "analysis": "analysis_result.schema.json"}[node["kind"]])
    result_refs: list[str] = []
    if node["kind"] == "clustering":
        membership = pd.read_csv(final / result["membership"], dtype={"compound_id": "string"})
        known = {row["cluster_id"] for row in read_jsonl(root / "runtime" / "cluster_registry.jsonl")}
        for cluster_id in sorted(value for value in membership.get("cluster_id", pd.Series(dtype=str)).astype(str).unique() if value.startswith("C")):
            mask = (membership["cluster_id"].astype(str) == cluster_id) & (pd.to_numeric(membership["membership_value"], errors="coerce").fillna(0) > 0)
            count = int(mask.sum())
            if count >= 5 and cluster_id not in known:
                append_jsonl_fsync(root / "runtime" / "cluster_registry.jsonl", {"cluster_id": cluster_id, "local_cluster_id": "recovered", "source_node_id": node["node_id"], "clustering_capability_id": node["capability_id"], "cluster_label": "recovered after interrupted commit", "compound_count": count, "membership_path": str((final / result["membership"]).relative_to(root)), "status": "active", "created_at": utc_now()})
            snapshot["counters"]["cluster"] = max(snapshot["counters"]["cluster"], int(cluster_id[1:]))
        _rebuild_cluster_matrix(root)
    elif node["kind"] == "analysis":
        known = {row["result_ref"] for row in read_jsonl(root / "runtime" / "result_index.jsonl")}
        for relative in result.get("result_cards") or []:
            card = read_json(final / relative)
            validate(card, "result_card.schema.json")
            _validate_result_card_links(root, card)
            if card["result_ref"] not in known:
                append_jsonl_fsync(root / "runtime" / "result_index.jsonl", card)
                known.add(card["result_ref"])
            result_refs.append(card["result_ref"])
    return result_refs


def cmd_reconcile_running(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    reconciled: list[dict[str, Any]] = []
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        _require_action(control, args.lease_token, {"WAIT_OR_RECONCILE_RUNNING"})
        for node in [item for item in snapshot["nodes"] if item["status"] == "running"]:
            attempt = next(item for item in node["attempts"] if item["attempt_id"] == node["current_attempt_id"])
            scratch = Path(attempt["scratch"])
            skill_output = _skill_output_dir(scratch)
            process_record = read_json(scratch / "process.json") if (scratch / "process.json").is_file() else {}
            if not process_record.get("finished_at") and pid_alive(int(process_record.get("pid", -1))):
                reconciled.append({"node_id": node["node_id"], "status": "still_running", "pid": process_record["pid"]})
                continue
            try:
                result_refs: list[str]
                if (Path(node["output_ref"]) / "result.json").is_file():
                    result_refs = _recover_promoted_output(root, snapshot, node)
                else:
                    event_path = skill_output / "execution_event.json"
                    if not event_path.is_file():
                        raise RuntimeError("interrupted process produced no committable execution event")
                    event = read_json(event_path)
                    validate(event, "execution_event.schema.json")
                    if event.get("node_id") != node["node_id"] or event.get("attempt_id") != attempt["attempt_id"] or event.get("round_id") != node["assigned_round"] or event.get("capability_id") != node["capability_id"] or event.get("status") != "succeeded":
                        raise ValueError("interrupted execution event identity or status mismatch")
                    for artifact in event.get("artifacts") or []:
                        source = _skill_artifact_path(skill_output, artifact["path"])
                        if not source.is_file() or file_hash(source) != artifact["sha256"]:
                            raise ValueError(f"missing or invalid interrupted artifact: {artifact['path']}")
                    cards = _adapt_success(root, control, snapshot, node, attempt, skill_output, event)
                    result_refs = [card["result_ref"] for card in cards]
                node.update({"status": "succeeded", "current_attempt_id": None, "finished_at": utc_now(), "result_quality": node.get("result_quality") or {"validation_passed": True, "eligible_for_downstream": True, "quality_flags": ["recovered_after_interruption"]}})
                attempt.update({"status": "succeeded", "finished_at": node["finished_at"], "recovered": True})
                reconciled.append({"node_id": node["node_id"], "status": "succeeded", "result_refs": result_refs})
            except Exception as exc:
                final = Path(node["output_ref"])
                if final.exists():
                    quarantine = root / "runtime" / "quarantine" / f"{node['node_id']}_{timestamp()}"
                    quarantine.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(final, quarantine)
                node.update({"status": "failed", "current_attempt_id": None, "finished_at": utc_now(), "result_quality": {"validation_passed": False, "eligible_for_downstream": False, "quality_flags": ["interrupted_without_committable_result"]}})
                attempt.update({"status": "failed", "finished_at": node["finished_at"], "error": str(exc), "recovered": True})
                reconciled.append({"node_id": node["node_id"], "status": "failed", "error": str(exc)})
        _commit(root, control, snapshot, "running_attempts_reconciled", {"outcomes": reconciled}, round_id=control["active_round_id"])
        working = _write_working_set(root, control, snapshot)
    _print_compact(control, outcome_count=len(reconciled), outcomes=reconciled[:50])
    return 0


def cmd_retry_node(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        _require_action(control, args.lease_token, {"RETRY_FAILED_NODE", "FAILED_NODE_REPAIR_REQUIRED"})
        if control["round_state"] != "ACTIVE":
            raise ValueError("A scientific Node can be retried only while the Round is ACTIVE")
        node = _node_lookup(snapshot).get(args.node_id)
        if not node or node["status"] != "failed":
            raise ValueError("Only a failed Node can be retried")
        if control["required_action"].get("node_id") != node["node_id"]:
            raise ValueError("Runtime selected a different failed Node for bounded retry")
        human_repair = control["required_action"]["code"] == "FAILED_NODE_REPAIR_REQUIRED"
        if len(node.get("attempts") or []) >= MAX_EXECUTION_ATTEMPTS and not human_repair:
            raise ValueError("The bounded retry allowance for this Node is exhausted")
        node["status"] = "pending"
        node["finished_at"] = None
        node["assigned_round"] = control["active_round_id"]
        _commit(root, control, snapshot, "node_retry_requested", {"reason": args.reason}, round_id=control["active_round_id"], node_id=node["node_id"])
    _print_compact(control, node_id=node["node_id"])
    return 0


def cmd_heartbeat(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        _require_action(control, args.lease_token)
        now = datetime.now(timezone.utc)
        control["lease"]["heartbeat_at"] = now.isoformat()
        control["lease"]["expires_at"] = (now + timedelta(minutes=max(5, args.lease_minutes))).isoformat()
        _commit(root, control, snapshot, "orchestrator_heartbeat", {}, round_id=control["active_round_id"])
    _print_compact(control, heartbeat_at=control["lease"]["heartbeat_at"], lease_expires_at=control["lease"]["expires_at"])
    return 0


def _renderer_module() -> Any:
    path = module_root() / "tools" / "templates" / "interpretation_render.py"
    spec = importlib.util.spec_from_file_location("conductor_interpretation_renderer", path)
    if not spec or not spec.loader:
        raise RuntimeError("Interpretation renderer could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _current_round_cards(root: Path, snapshot: dict[str, Any], round_id: str) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    round_node_ids = {node["node_id"] for node in _round_nodes(snapshot, round_id)}
    lookup = _node_lookup(snapshot)
    for card in read_jsonl(root / "runtime" / "result_index.jsonl"):
        node = lookup.get(card.get("node_id"))
        if (
            node
            and (node.get("result_quality") or {}).get("eligible_for_downstream", True)
            and (card.get("round_id") == round_id or card.get("node_id") in round_node_ids)
        ):
            latest[card["result_ref"]] = card
    return list(latest.values())


def _review_manifest(round_id: str, cards: list[dict[str, Any]], detailed_limit: int) -> dict[str, Any]:
    ordered = sorted(cards, key=lambda card: (card["analysis_subject"]["scope_mode"], card["capability_id"], card["result_ref"]))
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for card in ordered:
        buckets[(card["analysis_subject"]["scope_mode"], card["capability_id"])].append(card)
    detailed: list[dict[str, Any]] = []
    while buckets and len(detailed) < detailed_limit:
        for key in sorted(list(buckets)):
            detailed.append(buckets[key].pop(0))
            if not buckets[key]:
                del buckets[key]
            if len(detailed) >= detailed_limit:
                break
    detailed_refs = {card["result_ref"] for card in detailed}
    unreviewed = [card for card in ordered if card["result_ref"] not in detailed_refs]
    scope_counts = Counter(card["analysis_subject"]["scope_mode"] for card in ordered)
    operator_counts = Counter(card["capability_id"] for card in ordered)
    descriptions = Counter(item for card in ordered for item in card["analysis_subject"]["analysis_description_nodes"])
    manifest = {"schema_version": "1.0.0", "round_id": round_id, "detailed_result_refs": [card["result_ref"] for card in detailed], "aggregate_result_refs": [], "unreviewed_results": [{"result_ref": card["result_ref"], "reason": "bounded_interpretation_context"} for card in unreviewed], "scope_counts": dict(scope_counts), "operator_counts": dict(operator_counts), "description_counts": dict(descriptions), "created_at": utc_now()}
    validate(manifest, "interpretation_review_manifest.schema.json")
    return manifest


def cmd_enter_finalizing(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        _require_action(control, args.lease_token, {"ENTER_FINALIZING"})
        allowed, reason = _finalize_allowed(root, control, snapshot)
        if not allowed:
            raise ValueError(f"Runtime refuses early finalization: {reason}")
        round_id = control["active_round_id"]
        for node in snapshot["nodes"]:
            if node["status"] == "pending" and node.get("assigned_round") == round_id:
                node["assigned_round"] = None
        snapshot["rounds"][round_id].update({"state": "FINALIZING", "finalizing_reason": reason, "finalizing_started_at": utc_now()})
        control["round_state"] = "FINALIZING"
        _commit(root, control, snapshot, "round_entered_finalizing", {"reason": reason}, round_id=round_id)
        working = _write_working_set(root, control, snapshot)
    _print_compact(control)
    return 0


def cmd_prepare_interpretation(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        _require_action(control, args.lease_token, {"PLAN_INTERPRETATION"})
        round_id = control["active_round_id"]
        cards = _current_round_cards(root, snapshot, round_id)
        rereview = set(args.rereview_result_ref or [])
        all_cards = {card["result_ref"]: card for card in read_jsonl(root / "runtime" / "result_index.jsonl")}
        cards.extend(all_cards[ref] for ref in sorted(rereview) if ref in all_cards and all_cards[ref] not in cards)
        iteration_limit = max(1, int(_active_contract(root, control)["budgets"]["interpretation_iterations"])) * 20
        detailed_limit = min(args.detailed_limit, iteration_limit)
        review = _review_manifest(round_id, cards, detailed_limit)
        selected_refs = set(review["detailed_result_refs"])
        selected_cards = [card for card in cards if card["result_ref"] in selected_refs]
        selected_cards.sort(key=lambda card: review["detailed_result_refs"].index(card["result_ref"]))
        analysis_nodes = sorted({card["node_id"] for card in selected_cards})
        previous = snapshot["rounds"][round_id].get("current_interpretation_node")
        record = snapshot["rounds"][round_id]
        effective_focus = args.focus or record.get("report_revision_reason")
        revision_serial = int(record.get("interpretation_revision_serial", 0))
        node, _created = _add_node(snapshot, control, "I001", analysis_nodes, "round_commit", {"mode": "multi_scope"}, {"reviewed_result_refs": review["detailed_result_refs"], "focus": effective_focus, "revision_serial": revision_serial}, supersedes=previous)
        scratch = root / "runtime" / "scratch" / round_id / node["node_id"] / "interpretation"
        scratch.mkdir(parents=True, exist_ok=True)
        context = {"schema_version": "1.0.0", "run": control["run"], "round_id": round_id, "node_id": node["node_id"], "focus": effective_focus, "interpretation_policy": str((module_root() / "docs" / "CONDUCTOR_interpretation_policy.md").resolve()), "allowed_result_refs": review["detailed_result_refs"], "result_cards": selected_cards, "review_manifest": review, "comparison_batches": [[card["result_ref"] for card in selected_cards[index:index + 20]] for index in range(0, len(selected_cards), 20)], "role_contract": {"read_only_evidence_space": True, "scientific_computation_allowed": False, "node_creation_allowed": False, "followups_are_recommendations_only": True}, "draft_contract": {"scope_is_runtime_derived": True, "formal_ids_are_runtime_assigned": True, "comparison_claim_requires_comparison_results": True, "japanese_human_report": True}, "created_at": utc_now()}
        draft = {"title": "CONDUCTOR解析結果の解釈", "executive_summary": "", "coverage_summary": "", "insights": []}
        write_json(scratch / "context.json", context)
        write_json(scratch / "draft.json", draft)
        node["parameters"].update({"context_path": str(scratch / "context.json"), "draft_path": str(scratch / "draft.json"), "review_manifest": review})
        _commit(root, control, snapshot, "interpretation_prepared", {"node": node, "context_path": str(scratch / "context.json"), "draft_path": str(scratch / "draft.json")}, round_id=round_id, node_id=node["node_id"])
        working = _write_working_set(root, control, snapshot)
    _print_compact(control, node_id=node["node_id"], context_path=str(scratch / "context.json"), draft_path=str(scratch / "draft.json"), interpreter_agent="cs-conductor-interpreter")
    return 0


def _combined_subject(cards: list[dict[str, Any]]) -> dict[str, Any]:
    subjects = [card["analysis_subject"] for card in cards]
    modes = {subject["scope_mode"] for subject in subjects}
    cluster_ids = sorted({item for subject in subjects for item in subject["cluster_ids"]})
    if modes == {"global"}:
        mode = "global"
    elif modes <= {"single_cluster"} and len(cluster_ids) == 1:
        mode = "single_cluster"
    elif modes == {"global_vs_cluster"} and cluster_ids:
        mode = "global_vs_cluster"
    elif modes == {"cluster_vs_cluster"} and len(cluster_ids) >= 2:
        mode = "cluster_vs_cluster"
    elif "global" in modes and cluster_ids:
        mode = "global_vs_cluster"
    elif len(cluster_ids) == 2:
        mode = "cluster_vs_cluster"
    else:
        mode = "multi_scope"
    kinds = {subject["clustering_input_kind"] for subject in subjects if subject["clustering_input_kind"] != "none"}
    kind = next(iter(kinds)) if len(kinds) == 1 else "meta" if kinds else "none"
    overlap = next((subject.get("cluster_overlap") for subject in subjects if subject.get("cluster_overlap")), None)
    value = {"scope_mode": mode, "cluster_ids": cluster_ids, "clustering_input_kind": kind, "cluster_source_description_nodes": sorted({item for subject in subjects for item in subject["cluster_source_description_nodes"]}), "analysis_description_nodes": sorted({item for subject in subjects for item in subject["analysis_description_nodes"]}), "clustering_nodes": sorted({item for subject in subjects for item in subject["clustering_nodes"]}), "population_count": max((subject["population_count"] for subject in subjects), default=0), "endpoint_valid_count": max((subject["endpoint_valid_count"] for subject in subjects), default=0), "analyzed_count": max((subject["analyzed_count"] for subject in subjects), default=0), "excluded_count": max((subject["excluded_count"] for subject in subjects), default=0), "compound_set_hash": value_hash(sorted(subject["compound_set_hash"] for subject in subjects)), "cluster_overlap": overlap}
    validate(value, "analysis_subject.schema.json")
    return value


def _formalize_insights(root: Path, snapshot: dict[str, Any], draft: dict[str, Any], cards: dict[str, dict[str, Any]], round_id: str, interpretation_node: str) -> list[dict[str, Any]]:
    existing_rows = read_jsonl(root / "runtime" / "insight_index.jsonl")
    latest = {row["insight_id"]: row for row in existing_rows}
    formal: list[dict[str, Any]] = []
    for value in draft.get("insights") or []:
        supporting = list(dict.fromkeys(value.get("supporting_results") or []))
        comparisons = list(dict.fromkeys(value.get("comparison_results") or []))
        counter = list(dict.fromkeys(value.get("counter_results") or []))
        refs = list(dict.fromkeys([*supporting, *comparisons, *counter]))
        if not supporting:
            raise ValueError("Every Insight requires supporting_results")
        if set(refs) - set(cards):
            raise ValueError(f"Insight references Results outside the Interpretation context: {sorted(set(refs)-set(cards))}")
        existing_id = value.get("existing_insight_id")
        if existing_id:
            if existing_id not in latest:
                raise ValueError(f"Unknown existing Insight: {existing_id}")
            insight_id = existing_id
            revision = int(latest[existing_id]["revision"]) + 1
            attention = latest[existing_id]["attention"] if latest[existing_id]["attention"] == "pinned" else value.get("attention", latest[existing_id]["attention"])
        else:
            snapshot["counters"]["insight"] += 1
            insight_id = f"INS{snapshot['counters']['insight']:06d}"
            revision = 1
            attention = value.get("attention", "watch")
            if attention == "pinned":
                raise ValueError("Only a human can create a pinned Insight")
        selected_cards = [cards[ref] for ref in refs]
        subject = _combined_subject(selected_cards)
        clustering_caps = sorted({_node_lookup(snapshot)[node_id]["capability_id"] for node_id in subject["clustering_nodes"] if node_id in _node_lookup(snapshot)})
        description_caps = sorted({_node_lookup(snapshot)[node_id]["capability_id"] for node_id in subject["analysis_description_nodes"] if node_id in _node_lookup(snapshot)})
        source_caps = sorted({_node_lookup(snapshot)[node_id]["capability_id"] for node_id in subject["cluster_source_description_nodes"] if node_id in _node_lookup(snapshot)})
        fact_panel = {"operators": sorted({card["capability_id"] for card in selected_cards}), "metrics": sorted({str(card.get("metric")) for card in selected_cards if card.get("metric")}), "analysis_descriptions": description_caps, "cluster_source_descriptions": source_caps, "clustering_method": ", ".join(clustering_caps) if clustering_caps else None, "result_samples": {card["result_ref"]: card["analysis_subject"]["analyzed_count"] for card in selected_cards}, "key_metrics": {card["result_ref"]: dict(list((card.get("key_metrics") or {}).items())[:8]) for card in selected_cards}}
        formal.append({"insight_id": insight_id, "revision": revision, "attention": attention, "claim_kind": value.get("claim_kind", "single_scope_observation"), "title": str(value.get("title") or "名称未設定のInsight"), "analysis_subject": subject, "supporting_results": supporting, "comparison_results": comparisons, "counter_results": counter, "observation": str(value.get("observation") or ""), "interpretation": str(value.get("interpretation") or ""), "limitations": [str(item) for item in value.get("limitations") or []], "recommended_followups": [{"title": str(item.get("title") or "追加確認"), "rationale": str(item.get("rationale") or "")} for item in value.get("recommended_followups") or []], "fact_panel": fact_panel})
    return formal


def _anticipated_outcome(root: Path, control: dict[str, Any], snapshot: dict[str, Any]) -> str:
    deliverables = _deliverable_status(root, control, snapshot)
    technical_failures = any(node["status"] == "failed" and (node.get("created_in_round") == control["active_round_id"] or node.get("assigned_round") == control["active_round_id"]) for node in snapshot["nodes"])
    unmet = [item for item in deliverables if item["type"] != "interpretation_completed" and not item["satisfied"] and not item.get("human_acceptance_required")]
    return "partial" if technical_failures or unmet else "complete"


def cmd_commit_interpretation(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        _require_action(control, args.lease_token, {"WRITE_INTERPRETATION"})
        node = _node_lookup(snapshot).get(args.node_id)
        if not node or node["kind"] != "interpretation" or node["status"] not in {"pending", "failed"} or node.get("assigned_round") != control["active_round_id"]:
            raise ValueError("Interpretation Node is not commit-ready")
        draft_path = Path(args.draft).resolve() if args.draft else Path(node["parameters"]["draft_path"])
        if draft_path != Path(node["parameters"]["draft_path"]).resolve():
            raise ValueError("Draft path does not match the Runtime-prepared Interpretation workspace")
        candidate_snapshot = json.loads(json.dumps(snapshot))
        try:
            draft = read_json(draft_path)
            context = read_json(Path(node["parameters"]["context_path"]))
            cards = {card["result_ref"]: card for card in context["result_cards"]}
            insights = _formalize_insights(root, candidate_snapshot, draft, cards, control["active_round_id"], node["node_id"])
            outcome = _anticipated_outcome(root, control, snapshot)
            report = {"schema_version": "3.0.0", "run_id": control["run"]["run_id"], "round_id": control["active_round_id"], "node_id": node["node_id"], "supersedes": node.get("supersedes"), "title": str(draft.get("title") or "CONDUCTOR解析結果の解釈"), "report_header": {"project": control["run"]["project"], "endpoint": control["run"]["endpoint"], "higher_is_better": control["run"]["higher_is_better"], "endpoint_unit": control["run"].get("endpoint_unit"), "endpoint_transform": control["run"].get("endpoint_transform"), "completion": outcome}, "executive_summary": str(draft.get("executive_summary") or ("今回の詳細確認範囲では、支持結果と反証結果を突き合わせても報告基準を満たすInsightは抽出されませんでした。これは解析失敗ではなく、明瞭な差異・一致・矛盾を確認できなかったnegative resultです。" if not insights else "今回の解析で得られた主要なInsightを示します。")), "coverage_summary": str(draft.get("coverage_summary") or f"当該Roundから選択したOperator Result {len(cards)}件を、ScopeとOperatorの偏りを抑えた順序で詳細確認しました。未確認結果はreview manifestに明記しています。"), "insights": insights, "result_catalog": list(cards.values()), "review_manifest": context["review_manifest"], "created_at": utc_now()}
            validate(report, "interpretation.schema.json")
            renderer = _renderer_module()
            issues = renderer.quality_issues(report)
            if issues:
                raise ValueError("Interpretation quality gate failed: " + "; ".join(issues))
        except Exception as exc:
            attempt_id = f"ATT{len(node['attempts']) + 1:04d}"
            failure = {
                "schema_version": "1.0.0",
                "node_id": node["node_id"],
                "attempt_id": attempt_id,
                "error": str(exc)[:4000],
                "created_at": utc_now(),
            }
            failure_path = Path(node["parameters"]["draft_path"]).with_name(f"quality_failure_{attempt_id}.json")
            write_json(failure_path, failure)
            node["attempts"].append({"attempt_id": attempt_id, "status": "failed", "started_at": utc_now(), "finished_at": utc_now(), "draft_path": str(draft_path), "error": str(exc), "failure_pointer": str(failure_path.relative_to(root))})
            node.update({"status": "failed", "current_attempt_id": None, "finished_at": utc_now(), "result_quality": {"validation_passed": False, "eligible_for_downstream": False, "quality_flags": ["interpretation_quality_failure"]}})
            attempt_limit = min(MAX_INTERPRETER_ATTEMPTS, max(1, int(_active_contract(root, control)["budgets"]["interpretation_iterations"])))
            exhausted = len(node["attempts"]) >= attempt_limit
            if exhausted:
                control["blocker"] = {"code": "INTERPRETATION_RETRY_EXHAUSTED", "node_id": node["node_id"], "attempts": len(node["attempts"]), "failure_pointer": str(failure_path.relative_to(root))}
            _commit(root, control, snapshot, "interpretation_draft_rejected", {"node_id": node["node_id"], "attempt_id": attempt_id, "failure_pointer": str(failure_path.relative_to(root)), "retry_exhausted": exhausted}, round_id=control["active_round_id"], node_id=node["node_id"])
            _write_working_set(root, control, snapshot)
            _print_compact(control, node_id=node["node_id"], quality_status="fail", retry_exhausted=exhausted, failure_pointer=str(failure_path.relative_to(root)))
            return 1
        snapshot["counters"]["insight"] = candidate_snapshot["counters"]["insight"]
        final = Path(node["output_ref"])
        temporary = final.with_name(f".{final.name}.commit")
        if temporary.exists():
            shutil.rmtree(temporary)
        temporary.mkdir(parents=True)
        write_json(temporary / "interpretation.json", report)
        write_json(temporary / "review_manifest.json", context["review_manifest"])
        atomic_bytes(temporary / "interpretation.md", renderer.render_markdown(report, final, root).encode("utf-8"))
        atomic_bytes(temporary / "interpretation.html", renderer.render_html(report, temporary, root).encode("utf-8"))
        quality = {"schema_version": "1.0.0", "status": "pass", "issues": [], "report_hash": file_hash(temporary / "interpretation.json"), "created_at": utc_now()}
        write_json(temporary / "quality_report.json", quality)
        if final.exists():
            raise FileExistsError(f"Interpretation output exists: {final}")
        os.replace(temporary, final)
        for insight in insights:
            append_jsonl_fsync(root / "runtime" / "insight_index.jsonl", {**insight, "round_id": control["active_round_id"], "interpretation_node_id": node["node_id"], "updated_at": utc_now()})
        attempt_id = f"ATT{len(node['attempts']) + 1:04d}"
        node["attempts"].append({"attempt_id": attempt_id, "status": "succeeded", "started_at": utc_now(), "finished_at": utc_now(), "draft_path": str(draft_path)})
        node.update({"status": "succeeded", "current_attempt_id": None, "finished_at": utc_now(), "result_quality": {"validation_passed": True, "eligible_for_downstream": True, "quality_flags": []}})
        snapshot["rounds"][control["active_round_id"]].update({"current_interpretation_node": node["node_id"], "latest_audit": None, "interpretation_revision_required": False, "report_revision_reason": None})
        if (control.get("blocker") or {}).get("code") == "INTERPRETATION_RETRY_EXHAUSTED":
            control["blocker"] = None
        control["closure"]["outcome"] = outcome
        _commit(root, control, snapshot, "interpretation_committed", {"node_id": node["node_id"], "insight_ids": [item["insight_id"] for item in insights], "report_hash": quality["report_hash"]}, round_id=control["active_round_id"], node_id=node["node_id"])
        working = _write_working_set(root, control, snapshot)
    _print_compact(control, interpretation_dir=str(final), insight_ids=[item["insight_id"] for item in insights], quality_status="pass")
    return 0


def _audit(root: Path, mode: str) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(code: str, passed: bool, detail: Any = None, severity: str = "error") -> None:
        checks.append({"code": code, "passed": bool(passed), "severity": severity, "detail": clean(detail)})

    try:
        control, snapshot = _read_state(root)
        validate(control, "conductor_control.schema.json")
        _validate_snapshot(snapshot)
        check("CONTROL_AND_DAG_SCHEMA", True)
    except Exception as exc:
        check("CONTROL_AND_DAG_SCHEMA", False, str(exc))
        control = read_json(control_path(root))
        snapshot = read_json(snapshot_path(root))
    try:
        sequence, checksum = _verify_ledger(root)
        check("EVENT_LEDGER_CHAIN", sequence == control["last_event_sequence"] and checksum == control["last_event_checksum"], {"ledger_sequence": sequence, "control_sequence": control["last_event_sequence"]})
    except Exception as exc:
        check("EVENT_LEDGER_CHAIN", False, str(exc))
    check("CONTROL_SNAPSHOT_REVISION", control["revision"] == snapshot.get("control_revision"), {"control": control["revision"], "snapshot": snapshot.get("control_revision")})
    check("NO_PENDING_TRANSACTION", not (root / "runtime" / "pending_transaction.json").exists())
    canonical_input = Path(control["run"]["input"])
    check("CANONICAL_INPUT_HASH", canonical_input.is_file() and file_hash(canonical_input) == control["run"]["input_hash"], str(canonical_input))
    ids = [node["node_id"] for node in snapshot["nodes"]]
    check("NODE_IDS_UNIQUE", len(ids) == len(set(ids)))
    running = [node for node in snapshot["nodes"] if node["status"] == "running"]
    check("RUNNING_ATTEMPTS_VALID", all(node.get("current_attempt_id") for node in running))
    check("PARALLEL_LIMIT", len(running) <= control["run"]["parallel_limit"], {"running": len(running), "limit": control["run"]["parallel_limit"]})
    check("CPU_CORE_LIMIT", len(running) <= _available_cpu_cores(control), {"running": len(running), "available_cpu_cores": _available_cpu_cores(control)})
    registry = {row["cluster_id"]: row for row in read_jsonl(root / "runtime" / "cluster_registry.jsonl")}
    registry_rows = read_jsonl(root / "runtime" / "cluster_registry.jsonl")
    check("CLUSTER_IDS_UNIQUE", len(registry) == len(registry_rows))
    check("CLUSTER_MINIMUM_SIZE", all(int(row["compound_count"]) >= 5 for row in registry.values()))
    result_rows = read_jsonl(root / "runtime" / "result_index.jsonl")
    result_refs = [row.get("result_ref") for row in result_rows]
    check("RESULT_REFS_UNIQUE", len(result_refs) == len(set(result_refs)))
    if mode == "full":
        missing: list[str] = []
        invalid: list[str] = []
        for node in snapshot["nodes"]:
            if node["status"] != "succeeded":
                continue
            output = Path(node["output_ref"])
            required = ["interpretation.json", "interpretation.md", "interpretation.html", "quality_report.json"] if node["kind"] == "interpretation" else ["result.json"]
            for name in required:
                if not (output / name).is_file():
                    missing.append(str(output / name))
            if (output / "result.json").is_file():
                try:
                    result = read_json(output / "result.json")
                    validate(result, {"description": "description_result.schema.json", "clustering": "clustering_result.schema.json", "analysis": "analysis_result.schema.json"}[node["kind"]])
                except Exception as exc:
                    invalid.append(f"{node['node_id']}: {exc}")
        check("SUCCEEDED_ARTIFACTS_EXIST", not missing, missing)
        check("SCIENTIFIC_RESULTS_SCHEMA", not invalid, invalid)
        lookup = _node_lookup(snapshot)
        invalid_index = []
        invalid_result_links = []
        for row in result_rows:
            source = lookup.get(row.get("node_id"))
            if not source or source["status"] != "succeeded" or source["kind"] != "analysis":
                invalid_index.append({"result_ref": row.get("result_ref"), "node_id": row.get("node_id")})
            try:
                validate(row, "result_card.schema.json")
                _validate_result_card_links(root, row)
            except Exception as exc:
                invalid_result_links.append({"result_ref": row.get("result_ref"), "error": str(exc)})
        check("RESULT_INDEX_SOURCES", not invalid_index, invalid_index)
        check("RESULT_INDEX_LINKS", not invalid_result_links, invalid_result_links)
        invalid_clusters = []
        for row in registry_rows:
            source = lookup.get(row.get("source_node_id"))
            membership = root / str(row.get("membership_path", ""))
            if not source or source["status"] != "succeeded" or source["kind"] != "clustering" or not membership.is_file():
                invalid_clusters.append({"cluster_id": row.get("cluster_id"), "source_node_id": row.get("source_node_id"), "membership_path": row.get("membership_path")})
        check("CLUSTER_REGISTRY_SOURCES", not invalid_clusters, invalid_clusters)
        if control.get("active_round_id") and control["round_state"] in {"FINALIZING", "AWAITING_HUMAN_REVIEW"}:
            fresh, interpretation_node = _interpretation_fresh(snapshot, control["active_round_id"])
            check("INTERPRETATION_FRESH", fresh, {"node_id": interpretation_node})
            if interpretation_node:
                report_dir = Path(_node_lookup(snapshot)[interpretation_node]["output_ref"])
                try:
                    report = read_json(report_dir / "interpretation.json")
                    validate(report, "interpretation.schema.json")
                    issues = _renderer_module().quality_issues(report)
                    check("INTERPRETATION_QUALITY", not issues, issues)
                    links_missing = []
                    for card in report["result_catalog"]:
                        try:
                            _validate_result_card_links(root, card)
                        except Exception as exc:
                            links_missing.append(str(exc))
                    check("INTERPRETATION_LINKS", not links_missing, links_missing)
                except Exception as exc:
                    check("INTERPRETATION_SCHEMA", False, str(exc))
    errors = [item for item in checks if not item["passed"] and item["severity"] == "error"]
    warnings = [item for item in checks if not item["passed"] and item["severity"] == "warning"]
    return {"schema_version": "1.0.0", "mode": mode, "run_id": control["run"]["run_id"], "control_revision": control["revision"], "status": "fail" if errors else "warning" if warnings else "pass", "error_count": len(errors), "warning_count": len(warnings), "checks": checks, "created_at": utc_now()}


def _write_audit(root: Path, audit: dict[str, Any]) -> Path:
    output = root / "audit" / timestamp()
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "audit.json", audit)
    lines = [f"# CONDUCTOR {audit['mode'].title()} Audit", "", f"- Status: **{audit['status']}**", f"- Run: `{audit['run_id']}`", f"- Control revision: {audit['control_revision']}", ""]
    lines.extend(f"- [{'PASS' if item['passed'] else item['severity'].upper()}] `{item['code']}` — {json.dumps(item.get('detail'), ensure_ascii=False)}" for item in audit["checks"])
    atomic_bytes(output / "audit.md", ("\n".join(lines) + "\n").encode("utf-8"))
    return output


def cmd_audit(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    if not args.register:
        audit = _audit(root, args.mode)
        output = _write_audit(root, audit)
        print(json.dumps({"output_dir": str(output), "audit": audit}, ensure_ascii=False, indent=2))
        return 1 if audit["status"] == "fail" else 0
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        _require_action(control, args.lease_token, {"RUN_FULL_AUDIT"})
        if args.mode != "full":
            raise ValueError("Only a Full Audit can satisfy the Round gate")
        audit = _audit(root, args.mode)
        output = _write_audit(root, audit)
        interpretation = snapshot["rounds"][control["active_round_id"]].get("current_interpretation_node")
        snapshot["rounds"][control["active_round_id"]]["latest_audit"] = {"status": audit["status"], "path": str((output / "audit.json").relative_to(root)), "created_at": audit["created_at"], "after_interpretation_node": interpretation}
        _commit(root, control, snapshot, "full_audit_registered", {"status": audit["status"], "path": str(output.relative_to(root)), "after_interpretation_node": interpretation}, round_id=control["active_round_id"])
        working = _write_working_set(root, control, snapshot)
    _print_compact(control, output_dir=str(output), audit_status=audit["status"], error_count=audit["error_count"], warning_count=audit["warning_count"])
    return 1 if audit["status"] == "fail" else 0


def cmd_complete_finalizing(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        _require_action(control, args.lease_token, {"COMPLETE_FINALIZING"})
        round_id = control["active_round_id"]
        fresh, interpretation_node = _interpretation_fresh(snapshot, round_id)
        audit = snapshot["rounds"][round_id].get("latest_audit")
        if not fresh or not audit or audit.get("status") != "pass" or audit.get("after_interpretation_node") != interpretation_node:
            raise ValueError("Interpretation and Full Audit gate is not satisfied")
        deliverables = _deliverable_status(root, control, snapshot)
        completion = _anticipated_outcome(root, control, snapshot)
        stop_reason = snapshot["rounds"][round_id].get("finalizing_reason") or "contract_satisfied"
        if stop_reason not in {"contract_satisfied", "budget_exhausted", "no_eligible_work", "human_checkpoint", "abnormal_interruption", "blocked"}:
            stop_reason = "blocked" if completion == "blocked" else "contract_satisfied"
        outcome = {"schema_version": "1.0.0", "round_id": round_id, "completion": completion, "stop_reason": stop_reason, "deliverables": deliverables, "interpretation_node_id": interpretation_node, "audit_ref": audit["path"], "created_at": utc_now()}
        validate(outcome, "round_outcome.schema.json")
        write_json(root / "rounds" / round_id / "round_outcome.json", outcome)
        write_json(root / "rounds" / round_id / "interpretation_ref.json", {"schema_version": "1.0.0", "round_id": round_id, "node_id": interpretation_node, "path": str(Path(_node_lookup(snapshot)[interpretation_node]["output_ref"]).relative_to(root)), "created_at": utc_now()})
        snapshot["rounds"][round_id].update({"state": "AWAITING_HUMAN_REVIEW", "outcome": completion, "handoff_at": utc_now()})
        control.update({"round_state": "AWAITING_HUMAN_REVIEW", "blocker": None})
        control["closure"] = {"contract_satisfied": completion == "complete", "interpretation_ready": True, "audit_ready": True, "outcome": completion}
        owner = control["lease"]["owner_id"]
        control["lease"] = {"owner_id": None, "token_hash": None, "expires_at": None, "heartbeat_at": None, "process_id": None}
        _commit(root, control, snapshot, "round_handed_to_human", {"outcome": outcome, "released_owner": owner}, round_id=round_id)
        _write_working_set(root, control, snapshot)
    _print_compact(control, round_outcome=outcome, human_review_required=True)
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    control, snapshot = _read_state(root)
    ids = [item for item in (args.ids or "").split(",") if item]
    limit = min(MAX_CANDIDATES, max(1, args.limit))
    if args.kind == "control":
        value: Any = control
    elif args.kind == "working-set":
        value = read_json(root / "runtime" / "working_set.json") if (root / "runtime" / "working_set.json").is_file() else None
    elif args.kind == "node":
        lookup = _node_lookup(snapshot)
        value = [lookup[item] for item in ids if item in lookup] if ids else snapshot["nodes"][-limit:]
    elif args.kind == "cluster":
        data = {row["cluster_id"]: row for row in read_jsonl(root / "runtime" / "cluster_registry.jsonl")}
        value = [data[item] for item in ids if item in data] if ids else list(data.values())[-limit:]
    elif args.kind == "result":
        lookup = _node_lookup(snapshot)
        data = {}
        for row in read_jsonl(root / "runtime" / "result_index.jsonl"):
            node_quality = (lookup.get(row.get("node_id"), {}).get("result_quality") or {})
            current = {**row}
            if node_quality:
                current["eligible_for_downstream"] = node_quality.get("eligible_for_downstream", current.get("eligible_for_downstream", True))
                current["quality_flags"] = sorted(set(current.get("quality_flags") or []) | set(node_quality.get("quality_flags") or []))
            data[row["result_ref"]] = current
        value = [data[item] for item in ids if item in data] if ids else list(data.values())[-limit:]
    elif args.kind == "insight":
        data = {row["insight_id"]: row for row in read_jsonl(root / "runtime" / "insight_index.jsonl")}
        value = [data[item] for item in ids if item in data] if ids else list(data.values())[-limit:]
    else:
        value = _candidate_cells(root, control, snapshot)[:limit]
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


def cmd_node_inspect(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    control, snapshot = _read_state(root)
    node = _node_lookup(snapshot).get(args.node_id)
    if not node:
        raise ValueError("Unknown Node")
    downstream = [item["node_id"] for item in snapshot["nodes"] if args.node_id in item["input_nodes"]]
    print(json.dumps({"node": node, "downstream_nodes": downstream, "control_revision": control["revision"]}, ensure_ascii=False, indent=2))
    return 0


def cmd_node_cancel(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    _require_control_authority(root, args.control_key)
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        node = _node_lookup(snapshot).get(args.node_id)
        if not node or node["status"] != "pending":
            raise ValueError("Only a pending Node can be cancelled")
        downstream = [item for item in snapshot["nodes"] if args.node_id in item["input_nodes"] and item["status"] not in {"cancelled", "failed"}]
        if downstream:
            raise ValueError(f"Active downstream Nodes prevent cancellation: {[item['node_id'] for item in downstream]}")
        node.update({"status": "cancelled", "assigned_round": None, "finished_at": utc_now(), "result_quality": {"validation_passed": False, "eligible_for_downstream": False, "quality_flags": ["human_cancelled"]}})
        _commit(root, control, snapshot, "pending_node_cancelled_by_human", {"reason": args.reason}, round_id=control.get("active_round_id"), node_id=node["node_id"])
    return 0


def cmd_result_disable(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    _require_control_authority(root, args.control_key)
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        node = _node_lookup(snapshot).get(args.node_id)
        if not node or node["status"] != "succeeded":
            raise ValueError("Only a succeeded Node result can be disabled downstream")
        descendants: set[str] = set()
        frontier = {args.node_id}
        while frontier:
            discovered = {
                item["node_id"]
                for item in snapshot["nodes"]
                if item["node_id"] not in descendants
                and any(parent in frontier for parent in item["input_nodes"])
            }
            descendants.update(discovered)
            frontier = discovered
        running = [item["node_id"] for item in snapshot["nodes"] if item["node_id"] in descendants and item["status"] == "running"]
        if running:
            raise ValueError(f"Running downstream Nodes must finish or be reconciled before disabling this result: {running}")
        cancelled = []
        for item in snapshot["nodes"]:
            if item["node_id"] in descendants and item["status"] == "pending":
                item.update({"status": "cancelled", "assigned_round": None, "finished_at": utc_now(), "result_quality": {"validation_passed": False, "eligible_for_downstream": False, "quality_flags": ["upstream_human_disabled"]}})
                cancelled.append(item["node_id"])
        node["result_quality"] = {**(node.get("result_quality") or {}), "eligible_for_downstream": False, "quality_flags": sorted(set((node.get("result_quality") or {}).get("quality_flags", [])) | {"human_disabled"}), "human_reason": args.reason}
        interpretation_invalidated = False
        round_id = control.get("active_round_id")
        if round_id:
            record = snapshot["rounds"][round_id]
            interpretation_id = record.get("current_interpretation_node")
            interpretation_node = _node_lookup(snapshot).get(interpretation_id) if interpretation_id else None
            report_path = Path(interpretation_node["output_ref"]) / "interpretation.json" if interpretation_node else None
            if report_path and report_path.is_file():
                report = read_json(report_path)
                if any(card.get("node_id") == node["node_id"] for card in report.get("result_catalog") or []):
                    record.update({"interpretation_revision_required": True, "latest_audit": None, "report_revision_reason": f"Human disabled {node['node_id']}: {args.reason}"})
                    if control["round_state"] == "AWAITING_HUMAN_REVIEW":
                        control["round_state"] = "FINALIZING"
                        record["state"] = "FINALIZING"
                    interpretation_invalidated = True
        _commit(root, control, snapshot, "result_disabled_by_human", {"reason": args.reason, "downstream_nodes": sorted(descendants), "cancelled_pending_nodes": cancelled, "interpretation_invalidated": interpretation_invalidated}, round_id=round_id, node_id=node["node_id"])
    print(json.dumps({"node_id": args.node_id, "downstream_nodes": sorted(descendants), "cancelled_pending_nodes": cancelled, "interpretation_invalidated": interpretation_invalidated}, ensure_ascii=False, indent=2))
    return 0


def cmd_insight_attention(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    _require_control_authority(root, args.control_key)
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        rows = read_jsonl(root / "runtime" / "insight_index.jsonl")
        current = next((row for row in reversed(rows) if row["insight_id"] == args.insight_id), None)
        if not current:
            raise ValueError("Unknown Insight")
        revised = {**current, "revision": int(current["revision"]) + 1, "attention": args.attention, "human_note": args.reason, "updated_at": utc_now()}
        append_jsonl_fsync(root / "runtime" / "insight_index.jsonl", revised)
        _commit(root, control, snapshot, "insight_attention_changed_by_human", {"insight_id": args.insight_id, "attention": args.attention, "reason": args.reason}, round_id=control.get("active_round_id"))
    return 0


def cmd_request_checkpoint(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    _require_control_authority(root, args.control_key)
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        if control["round_state"] != "ACTIVE":
            raise ValueError("A human checkpoint can be requested only during ACTIVE")
        snapshot["rounds"][control["active_round_id"]]["human_checkpoint_requested"] = True
        snapshot["rounds"][control["active_round_id"]]["checkpoint_reason"] = args.reason
        _commit(root, control, snapshot, "human_checkpoint_requested", {"reason": args.reason}, round_id=control["active_round_id"])
    _print_compact(control, checkpoint_requested=True)
    return 0


def _action_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--lease-token", required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CONDUCTOR 0.1.5 deterministic Runtime Controller")
    commands = parser.add_subparsers(dest="command", required=True)

    item = commands.add_parser("init")
    item.add_argument("--input", required=True)
    item.add_argument("--smiles-column", help="SMILES column in the input CSV; required only when deterministic inference is ambiguous")
    item.add_argument("--endpoint", required=True)
    item.add_argument("--higher-is-better", action=argparse.BooleanOptionalAction, required=True)
    item.add_argument("--endpoint-unit")
    item.add_argument("--endpoint-transform", help="Metadata describing a transform already applied to the endpoint column; Runtime does not transform values")
    item.add_argument("--project", required=True)
    item.add_argument("--parallel-limit", type=int, required=True)
    item.add_argument("--available-cpu-cores", type=int, default=DEFAULT_AVAILABLE_CPU_CORES)
    item.add_argument("--run-id")
    item.add_argument("--output-dir")
    item.set_defaults(func=cmd_init)

    item = commands.add_parser("prepare-round")
    item.add_argument("--run-root", required=True)
    item.add_argument("--objective", required=True)
    item.add_argument("--optional-direction", action="append")
    item.add_argument("--human-priority", action="append")
    item.add_argument("--omission", action="append")
    item.add_argument("--walltime-minutes", type=int, default=480)
    item.add_argument("--parallel-limit", type=int)
    item.add_argument("--available-cpu-cores", type=int)
    item.add_argument("--max-additional-nodes", type=int, default=100)
    item.add_argument("--interpretation-iterations", type=int, default=3)
    item.add_argument("--approve-high-cost", action="store_true")
    item.add_argument("--required-deliverables-json")
    item.set_defaults(func=cmd_prepare_round)

    item = commands.add_parser("authorize-round")
    item.add_argument("--run-root", required=True)
    item.add_argument("--control-key", required=True)
    item.add_argument("--request-file", required=True)
    item.add_argument("--authorization-token", required=True)
    item.set_defaults(func=cmd_authorize_round)

    item = commands.add_parser("resume-round")
    item.add_argument("--run-root", required=True)
    item.add_argument("--control-key", required=True)
    item.add_argument("--owner-id", required=True)
    item.add_argument("--process-id", type=int)
    item.add_argument("--lease-minutes", type=int, default=DEFAULT_LEASE_MINUTES)
    item.add_argument("--smiles-column", help="Populate missing SMILES metadata when resuming a legacy Run; an existing value is immutable")
    item.set_defaults(func=cmd_resume_round)

    item = commands.add_parser("continue-round")
    item.add_argument("--run-root", required=True)
    item.add_argument("--control-key", required=True)
    item.add_argument("--additional-walltime-minutes", type=int, required=True)
    item.add_argument("--reason", required=True)
    item.set_defaults(func=cmd_continue_round)

    item = commands.add_parser("revise-report")
    item.add_argument("--run-root", required=True)
    item.add_argument("--control-key", required=True)
    item.add_argument("--reason", required=True)
    item.set_defaults(func=cmd_revise_report)

    item = commands.add_parser("accept-round")
    item.add_argument("--run-root", required=True)
    item.add_argument("--control-key", required=True)
    item.add_argument("--note", default="")
    item.set_defaults(func=cmd_accept_round)

    item = commands.add_parser("approve-high-cost")
    item.add_argument("--run-root", required=True)
    item.add_argument("--control-key", required=True)
    decision = item.add_mutually_exclusive_group(required=True)
    decision.add_argument("--approve", action="store_true")
    decision.add_argument("--reject", dest="approve", action="store_false")
    item.add_argument("--rationale", required=True)
    item.set_defaults(func=cmd_approve_high_cost)

    item = commands.add_parser("request-checkpoint")
    item.add_argument("--run-root", required=True)
    item.add_argument("--control-key", required=True)
    item.add_argument("--reason", required=True)
    item.set_defaults(func=cmd_request_checkpoint)

    item = commands.add_parser("verify-return")
    item.add_argument("--run-root", required=True)
    item.add_argument("--confirm-returned", action="store_true")
    item.add_argument("--control-key")
    item.add_argument("--owner-id")
    item.add_argument("--start-revision", type=int)
    item.set_defaults(func=cmd_verify_return)

    item = commands.add_parser("release-lease")
    _action_args(item)
    item.add_argument("--reason", required=True)
    item.set_defaults(func=cmd_release_lease)

    item = commands.add_parser("heartbeat")
    _action_args(item)
    item.add_argument("--lease-minutes", type=int, default=DEFAULT_LEASE_MINUTES)
    item.set_defaults(func=cmd_heartbeat)

    for name, function in (("plan-basic", cmd_plan_basic), ("plan-exploration", cmd_plan_exploration)):
        item = commands.add_parser(name)
        _action_args(item)
        item.set_defaults(func=function)

    item = commands.add_parser("scientific-decision")
    _action_args(item)
    item.add_argument("--candidate-ids")
    item.add_argument("--rationale", required=True)
    item.add_argument("--finish-reason", choices=["no_eligible_work", "contract_satisfied"])
    item.set_defaults(func=cmd_apply_scientific_decision)

    item = commands.add_parser("prepare-execution-packet")
    _action_args(item)
    item.add_argument("--node-ids")
    item.add_argument("--timeout-minutes", type=int, default=DEFAULT_EXECUTION_TIMEOUT_MINUTES)
    item.add_argument("--clean-scratch", action=argparse.BooleanOptionalAction, default=True)
    item.set_defaults(func=cmd_prepare_execution_packet)

    item = commands.add_parser("execute-packet")
    item.add_argument("--run-root", required=True)
    item.add_argument("--packet", required=True)
    item.set_defaults(func=cmd_execute_packet)

    item = commands.add_parser("reconcile-running")
    _action_args(item)
    item.set_defaults(func=cmd_reconcile_running)

    item = commands.add_parser("retry-node")
    _action_args(item)
    item.add_argument("--node-id", required=True)
    item.add_argument("--reason", required=True)
    item.set_defaults(func=cmd_retry_node)

    item = commands.add_parser("enter-finalizing")
    _action_args(item)
    item.set_defaults(func=cmd_enter_finalizing)

    item = commands.add_parser("prepare-interpretation")
    _action_args(item)
    item.add_argument("--focus")
    item.add_argument("--rereview-result-ref", action="append")
    item.add_argument("--detailed-limit", type=int, default=60)
    item.set_defaults(func=cmd_prepare_interpretation)

    item = commands.add_parser("commit-interpretation")
    _action_args(item)
    item.add_argument("--node-id", required=True)
    item.add_argument("--draft")
    item.set_defaults(func=cmd_commit_interpretation)

    item = commands.add_parser("audit")
    item.add_argument("--run-root", required=True)
    item.add_argument("--mode", choices=["quick", "full"], default="quick")
    item.add_argument("--register", action="store_true")
    item.add_argument("--lease-token")
    item.set_defaults(func=cmd_audit)

    item = commands.add_parser("complete-finalizing")
    _action_args(item)
    item.set_defaults(func=cmd_complete_finalizing)

    item = commands.add_parser("query")
    item.add_argument("--run-root", required=True)
    item.add_argument("--kind", choices=["control", "working-set", "node", "cluster", "result", "insight", "candidates"], required=True)
    item.add_argument("--ids")
    item.add_argument("--limit", type=int, default=20)
    item.set_defaults(func=cmd_query)

    item = commands.add_parser("node-inspect")
    item.add_argument("--run-root", required=True)
    item.add_argument("--node-id", required=True)
    item.set_defaults(func=cmd_node_inspect)

    item = commands.add_parser("node-cancel")
    item.add_argument("--run-root", required=True)
    item.add_argument("--control-key", required=True)
    item.add_argument("--node-id", required=True)
    item.add_argument("--reason", required=True)
    item.set_defaults(func=cmd_node_cancel)

    item = commands.add_parser("result-disable")
    item.add_argument("--run-root", required=True)
    item.add_argument("--control-key", required=True)
    item.add_argument("--node-id", required=True)
    item.add_argument("--reason", required=True)
    item.set_defaults(func=cmd_result_disable)

    item = commands.add_parser("insight-attention")
    item.add_argument("--run-root", required=True)
    item.add_argument("--control-key", required=True)
    item.add_argument("--insight-id", required=True)
    item.add_argument("--attention", choices=["pinned", "active", "watch", "background"], required=True)
    item.add_argument("--reason", required=True)
    item.set_defaults(func=cmd_insight_attention)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
