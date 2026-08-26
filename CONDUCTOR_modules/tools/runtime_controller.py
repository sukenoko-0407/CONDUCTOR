from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import importlib.util
import json
import math
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


VERSION = "0.2.0"
PROTOCOL_VERSION = "0.2.0"
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
SCREENING_RUBRIC_VERSION = "2.0.0"
DEFAULT_SCREENING_BATCH_SIZE = 8
DEFAULT_SCREENING_CONTEXT_BYTES = 64 * 1024
MAX_SIBLING_BUNDLE_CARDS = 16
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
ASSESSMENT_AXES = (
    "favorable_signal", "context_deviation", "chemical_actionability",
    "independent_support", "follow_up_leverage",
)
COMPARISON_PARAMETER_EXCLUSIONS = {
    "target_cluster", "comparison_cluster", "scope_mode", "scope_compound_set_hash",
    "clustering_node_id", "clustering_representation", "membership", "role",
    "min_local_samples",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def parse_time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            # Access denied means a process exists but cannot be queried. Treat it
            # as live so a lock/Worker is never stolen from another principal.
            return ctypes.get_last_error() == 5
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
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
    """Return the human-declared CPU allocation or the new-Run default."""
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


def atomic_replace(source: Path, target: Path, timeout_seconds: float = 5.0) -> None:
    """Replace a file or directory atomically, tolerating brief scanner locks.

    Windows sync clients and antivirus scanners can open a freshly written
    temporary file between ``fsync`` and ``os.replace``.  The operation remains
    atomic; only the transient sharing violation is retried for a bounded time.
    """
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    delay = 0.01
    while True:
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(delay)
            delay = min(0.25, delay * 2.0)


def atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    atomic_replace(temporary, path)


def write_json(path: Path, value: Any) -> None:
    atomic_bytes(path, json.dumps(clean(value), ensure_ascii=False, indent=2, default=str).encode("utf-8") + b"\n")


def append_jsonl_fsync(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(canonical_bytes(row) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())


def append_jsonl_rows_atomic(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    """Append a bounded logical batch without exposing a partially validated index."""
    additions = list(rows)
    if not additions:
        return
    combined = [*read_jsonl(path), *additions]
    payload = b"".join(canonical_bytes(row) + b"\n" for row in combined)
    atomic_bytes(path, payload)


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
    atomic_replace(temporary, path)


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
    control = read_json(control_path(root))
    snapshot = read_json(snapshot_path(root))
    if control.get("conductor_version") != VERSION:
        raise ValueError(
            f"Run version {control.get('conductor_version')!r} is not compatible with "
            f"CONDUCTOR {VERSION}; start a new Run instead of mutating an older Run"
        )
    return control, snapshot


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


def _round_report_mode(root: Path, control: dict[str, Any], snapshot: dict[str, Any] | None = None) -> str:
    """Return the human-authorized handoff mode for the active Round."""
    contract = _active_contract(root, control)
    mode = (contract or {}).get("report_mode")
    if mode in {"screening", "full"}:
        return str(mode)
    return "full"


def _screening_enabled(root: Path, control: dict[str, Any], snapshot: dict[str, Any]) -> bool:
    """0.2.0 requires Bundle assessment for every active Round."""
    round_id = control.get("active_round_id")
    return bool(round_id and str(round_id) in snapshot.get("rounds", {}))


def _round_analysis_limit(root: Path, control: dict[str, Any], snapshot: dict[str, Any]) -> int:
    safety_limit, _batch_size = _analysis_planning_limits()
    contract = _active_contract(root, control)
    requested = int((contract or {}).get("budgets", {}).get("max_additional_nodes", 50))
    return min(safety_limit, max(0, requested))


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


def _packet_status_path(packet_path: Path) -> Path:
    return packet_path.resolve().parent / "worker_status.json"


def _read_packet_status(packet_path: Path) -> dict[str, Any] | None:
    path = _packet_status_path(packet_path)
    if not path.is_file():
        return None
    status = read_json(path)
    validate(status, "runtime_worker_status.schema.json")
    return status


def _write_packet_status(packet_path: Path, status: dict[str, Any]) -> None:
    status["updated_at"] = utc_now()
    validate(status, "runtime_worker_status.schema.json")
    write_json(_packet_status_path(packet_path), status)


def _validate_execution_packet_authentic(root: Path, packet_path: Path) -> dict[str, Any]:
    """Validate immutable packet identity without requiring its old Control revision.

    A claimed packet must remain inspectable after ``batch_started`` advances the
    Control revision.  Initial claiming still uses the stricter
    ``_validate_execution_packet`` check.
    """
    packet_path = packet_path.resolve()
    packet_root = (root / "runtime" / "scratch" / "packets").resolve()
    if packet_root not in packet_path.parents:
        raise PermissionError("Execution packet is outside the Runtime packet directory")
    packet = read_json(packet_path)
    validate(packet, "execution_packet.schema.json")
    if not hmac.compare_digest(packet["signature"], _packet_signature(root, packet)):
        raise PermissionError("Execution packet signature is invalid")
    control = read_json(control_path(root))
    if packet["run_id"] != control["run"]["run_id"]:
        raise PermissionError("Execution packet belongs to another Run")
    return packet


def _require_packet_status_identity(packet: dict[str, Any], status: dict[str, Any]) -> None:
    expected = (packet["packet_id"], packet["run_id"], packet["round_id"], list(packet["node_ids"]))
    actual = (status.get("packet_id"), status.get("run_id"), status.get("round_id"), list(status.get("node_ids") or []))
    if actual != expected:
        raise PermissionError("Runtime Worker status identity does not match its signed packet")


def _require_worker_followup(snapshot: dict[str, Any], packet: dict[str, Any]) -> None:
    """Require the exact claimed Attempts; do not depend on an LLM lease."""
    lookup = _node_lookup(snapshot)
    for contract in packet["execution_contracts"]:
        node = lookup.get(contract["node_id"])
        if not node or node.get("status") != "running":
            raise PermissionError(f"Claimed Runtime Worker Node is not running: {contract['node_id']}")
        if node.get("current_attempt_id") != contract["attempt_id"]:
            raise PermissionError(f"Claimed Runtime Worker Attempt changed: {contract['node_id']}")
        attempt = next(
            (item for item in node.get("attempts") or [] if item.get("attempt_id") == contract["attempt_id"]),
            None,
        )
        if not attempt or attempt.get("packet_id") != packet["packet_id"]:
            raise PermissionError(f"Runtime Worker packet binding changed: {contract['node_id']}")


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
        execution_owner="runtime_worker",
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
        elif kind == "screening_completed":
            satisfied, summary_ref = _screening_summary_fresh(root, snapshot, control["active_round_id"])
            evidence = [summary_ref] if summary_ref else []
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
    maximum_analysis_nodes = _round_analysis_limit(root, control, snapshot)
    round_analysis_nodes = [
        node for node in snapshot["nodes"]
        if node["kind"] == "analysis"
        and (node.get("created_in_round") == round_id or node.get("assigned_round") == round_id)
    ]
    # Reaching the planning ceiling prevents creation of more Operator Nodes; it
    # must not discard the final planned slice before its pending Nodes execute.
    # Failed/cancelled Nodes remain terminal and can still lead to a partial handoff.
    analysis_work_terminal = all(node["status"] in {"succeeded", "failed", "cancelled"} for node in round_analysis_nodes)
    basic_was_planned = bool(snapshot.get("plans", {}).get(str(round_id), {}).get("basic_compute"))
    if basic_was_planned and analysis_work_terminal and _round_analysis_work_count(snapshot, round_id) >= maximum_analysis_nodes:
        return True, "analysis_node_budget_exhausted"
    if record.get("finish_reason") in {"no_eligible_work", "contract_satisfied", "analysis_node_budget_exhausted"}:
        return True, record["finish_reason"]
    deliverables = _deliverable_status(root, control, snapshot)
    if deliverables and all(item["satisfied"] or item.get("human_acceptance_required") for item in deliverables if item["type"] not in {"interpretation_completed", "screening_completed"}):
        if record.get("scientific_finish_requested"):
            return True, "contract_satisfied"
    return False, "eligible work or unfulfilled contract remains"


def _running_action(root: Path, snapshot: dict[str, Any], running: list[dict[str, Any]]) -> dict[str, Any]:
    """Distinguish normal waiting from recovery without adding a Node state."""
    live_owner = False
    packet_ids: set[str] = set()
    for node in running:
        attempt = next(
            (item for item in node.get("attempts") or [] if item.get("attempt_id") == node.get("current_attempt_id")),
            None,
        )
        if not attempt:
            continue
        packet_id = attempt.get("packet_id")
        if packet_id:
            packet_ids.add(str(packet_id))
            packet_path = root / "runtime" / "scratch" / "packets" / str(packet_id) / "execution_packet.json"
            try:
                status = _read_packet_status(packet_path)
            except Exception:
                status = None
            if status:
                worker_pid = int(status.get("worker_pid") or -1)
                launcher_pid = int(status.get("launcher_pid") or -1)
                if status.get("status") in {"running", "launching", "claimed", "claiming"} and (
                    pid_alive(worker_pid) or pid_alive(launcher_pid)
                ):
                    live_owner = True
        process_path = Path(str(attempt.get("scratch") or "")) / "process.json"
        try:
            process_record = read_json(process_path) if process_path.is_file() else {}
        except Exception:
            process_record = {}
        if not process_record.get("finished_at") and pid_alive(int(process_record.get("pid", -1))):
            live_owner = True
    node_ids = [node["node_id"] for node in running[:20]]
    if live_owner:
        return {
            "code": "WAIT_RUNNING",
            "reason": "A Runtime Worker or its scientific process is live. Do not launch another Worker or reconcile it as failed.",
            "node_ids": node_ids,
            "packet_ids": sorted(packet_ids),
        }
    return {
        "code": "RECONCILE_RUNNING",
        "reason": "Running Attempts have no live Runtime Worker or scientific process and require one recovery pass.",
        "node_ids": node_ids,
        "packet_ids": sorted(packet_ids),
    }


def _required_action(root: Path, control: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    round_id = control.get("active_round_id")
    if not round_id:
        return {"code": "AWAIT_HUMAN_ROUND", "reason": "No active Round. Only a human-authorized Main Orchestrator operation can start one."}
    if control["round_state"] == "AWAITING_HUMAN_REVIEW":
        return {"code": "HUMAN_REVIEW_REQUIRED", "reason": "The contracted Round handoff artifact and audit are ready. Human continuation, report revision, or acceptance is required."}
    if control["round_state"] == "CLOSED":
        return {"code": "AWAIT_HUMAN_ROUND", "reason": "The previous Round is closed. A new Round requires explicit human authorization."}
    running = [node for node in snapshot["nodes"] if node["status"] == "running"]
    if running:
        return _running_action(root, snapshot, running)
    if _screening_enabled(root, control, snapshot):
        blocker = control.get("blocker") or {}
        if blocker.get("code") == "RESULT_SCREENING_RETRY_EXHAUSTED":
            return {
                "code": "RESULT_SCREENING_BLOCKED",
                "reason": "The bounded Result Screening retry budget is exhausted. Human correction or retry authorization is required.",
                "batch_id": blocker.get("batch_id"),
                "failure_pointer": blocker.get("failure_pointer"),
            }
        current_batch = snapshot.get("rounds", {}).get(round_id, {}).get("current_screening_batch")
        if current_batch:
            return {
                "code": "WRITE_RESULT_SCREENING",
                "reason": "A bounded Result Screening draft is required before more scientific work is scheduled.",
                "batch_id": current_batch.get("batch_id"),
                "context_path": current_batch.get("context_path"),
                "draft_path": current_batch.get("draft_path"),
            }
        pending_screening = _pending_screening_bundles(root, snapshot, round_id)
        if pending_screening:
            return {
                "code": "PREPARE_RESULT_SCREENING",
                "reason": "New eligible Result Cards require bounded Screening before more scientific work is scheduled.",
                "unassessed_count": len(pending_screening),
            }
    if control["round_state"] == "FINALIZING":
        summary_ref: str | None = None
        if _screening_enabled(root, control, snapshot):
            summary_fresh, summary_ref = _screening_summary_fresh(root, snapshot, round_id)
            if not summary_fresh:
                return {"code": "WRITE_SCREENING_SUMMARY", "reason": "Write the compact Result Screening summary before Round handoff."}
        if _round_report_mode(root, control, snapshot) == "screening":
            marker = f"screening:{summary_ref}"
            audit = snapshot.get("rounds", {}).get(round_id, {}).get("latest_audit")
            if not audit or audit.get("status") != "pass" or audit.get("after_handoff_ref") != marker:
                return {"code": "RUN_FULL_AUDIT", "reason": "A passing Audit newer than the Screening Summary is required."}
            return {"code": "COMPLETE_FINALIZING", "reason": "Screening Summary and Full Audit satisfy the Round handoff gate."}
        if (control.get("blocker") or {}).get("code") == "INTERPRETATION_RETRY_EXHAUSTED":
            return {"code": "INTERPRETATION_BLOCKED", "reason": "The bounded Interpreter retry budget is exhausted. Human correction or report-revision authorization is required.", "node_id": control["blocker"].get("node_id")}
        fresh, interpretation_node = _interpretation_fresh(snapshot, round_id)
        if not fresh:
            existing = [node for node in snapshot["nodes"] if node["kind"] == "interpretation" and node.get("assigned_round") == round_id and node["status"] in {"pending", "failed"}]
            if existing:
                return {"code": "WRITE_INTERPRETATION", "reason": "A current Interpretation is mandatory before Round handoff.", "node_id": existing[-1]["node_id"]}
            return {"code": "PLAN_INTERPRETATION", "reason": "Create the Round commit Interpretation Node."}
        audit = snapshot.get("rounds", {}).get(round_id, {}).get("latest_audit")
        audit_marker = (audit or {}).get("after_handoff_ref") or (f"interpretation:{audit.get('after_interpretation_node')}" if audit and audit.get("after_interpretation_node") else None)
        if not audit or audit.get("status") != "pass" or audit_marker != f"interpretation:{interpretation_node}":
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
            "reason": "A deterministic failure or exhausted retry requires human repair before same-Node retry. If the Round budget ends first, Runtime may hand off a partial Round for human review.",
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
    if (
        _round_analysis_work_count(snapshot, round_id) < _round_analysis_limit(root, control, snapshot)
        and _candidate_cells(root, control, snapshot)
    ):
        return {"code": "PLAN_EXPLORATION", "reason": "Plan the next bounded exploration slice within the same human-authorized Round budget."}
    allowed, reason = _finalize_allowed(root, control, snapshot)
    if allowed:
        return {"code": "ENTER_FINALIZING", "reason": reason}
    return {"code": "SCIENTIFIC_DECISION", "reason": "Select an evidence-led follow-up from the bounded Working Set, or finalize this Round."}


def _refresh_control(root: Path, control: dict[str, Any], snapshot: dict[str, Any]) -> None:
    counts = Counter(node["status"] for node in snapshot["nodes"])
    counts.update({f"kind_{kind}": sum(node["kind"] == kind for node in snapshot["nodes"]) for kind in ("description", "clustering", "analysis", "interpretation")})
    maximum_analysis_nodes = _round_analysis_limit(root, control, snapshot) if control.get("active_round_id") else _analysis_planning_limits()[0]
    pending_assessments = len(_pending_screening_bundles(root, snapshot, control["active_round_id"])) if control.get("active_round_id") and _screening_enabled(root, control, snapshot) else 0
    assessed_results = len(_round_current_assessments(root, snapshot, control["active_round_id"])) if control.get("active_round_id") and _screening_enabled(root, control, snapshot) else 0
    counts.update({
        "round_analysis_nodes": _round_analysis_work_count(snapshot, control.get("active_round_id")),
        "round_analysis_node_limit": maximum_analysis_nodes,
        "round_assessed_results": assessed_results,
        "round_unassessed_results": pending_assessments,
    })
    control["counts"] = dict(sorted(counts.items()))
    deliverables = _deliverable_status(root, control, snapshot) if control.get("active_round_id") else []
    fresh, interpretation_node = _interpretation_fresh(snapshot, control["active_round_id"]) if control.get("active_round_id") else (False, None)
    audit = snapshot.get("rounds", {}).get(str(control.get("active_round_id")), {}).get("latest_audit") if control.get("active_round_id") else None
    handoff_marker = _handoff_marker(root, control, snapshot) if control.get("active_round_id") else None
    audit_marker = (audit or {}).get("after_handoff_ref") or (f"interpretation:{audit.get('after_interpretation_node')}" if audit and audit.get("after_interpretation_node") else None)
    control["closure"] = {
        "contract_satisfied": bool(deliverables and all(item["satisfied"] or item.get("human_acceptance_required") for item in deliverables)),
        "interpretation_ready": fresh,
        "audit_ready": bool(audit and audit.get("status") == "pass" and audit_marker == handoff_marker),
        "outcome": control.get("closure", {}).get("outcome", "undetermined"),
    }
    control["required_action"] = _required_action(root, control, snapshot)
    control["pointers"].update({
        "round_contract": f"rounds/{control['active_round_id']}/round_contract.json" if control.get("active_round_id") else None,
        "working_set": "runtime/working_set.json",
        "dag_snapshot": "runtime/dag_snapshot.json",
        "event_ledger": "runtime/event_ledger.jsonl",
        "result_index": "runtime/result_index.jsonl",
        "result_assessment_index": "runtime/result_assessment_index.jsonl",
        "review_bundle_index": "runtime/review_bundle_index.jsonl",
    })


def _signature(capability_id: str, input_nodes: list[str], scope: dict[str, Any], parameters: dict[str, Any]) -> str:
    return value_hash({"capability_id": capability_id, "input_nodes": sorted(input_nodes), "scope": scope, "parameters": parameters})


def _analysis_planning_limits() -> tuple[int, int]:
    settings = profile().get("runtime_planning") or {}
    maximum = int(settings.get("max_new_analysis_nodes_per_round", 50))
    batch_size = int(settings.get("analysis_activation_batch_size", min(25, maximum)))
    if maximum < 50 or batch_size < 1 or batch_size > maximum:
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
    if kind == "analysis" and not _analysis_scope_supported(capability, scope, parameters):
        raise ValueError(
            f"{capability_id} does not support Runtime scope={scope.get('mode')} "
            f"with role={parameters.get('role')}"
        )
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
    for path in (root / "runtime" / "result_index.jsonl", root / "runtime" / "result_assessment_index.jsonl", root / "runtime" / "review_bundle_index.jsonl", root / "runtime" / "insight_index.jsonl", root / "runtime" / "cluster_registry.jsonl", root / "runtime" / "event_ledger.jsonl"):
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
        "pointers": {"round_contract": None, "working_set": "runtime/working_set.json", "dag_snapshot": "runtime/dag_snapshot.json", "event_ledger": "runtime/event_ledger.jsonl", "result_index": "runtime/result_index.jsonl", "result_assessment_index": "runtime/result_assessment_index.jsonl", "review_bundle_index": "runtime/review_bundle_index.jsonl"},
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


def _default_deliverables(snapshot: dict[str, Any], report_mode: str) -> list[dict[str, Any]]:
    first_comprehensive = not any(node["status"] == "succeeded" for node in snapshot["nodes"])
    items: list[dict[str, Any]] = []
    if first_comprehensive:
        p = profile()
        items.append({"deliverable_id": "DELIV_BASIC", "type": "planned_node_coverage", "description": "計画された基本計算Nodeを可能な範囲で完了する。", "parameters": {"plan_key": "basic_compute"}, "human_acceptance_required": False})
        items.append({"deliverable_id": "DELIV_GLOBAL", "type": "capability_coverage", "description": "Global Operatorを優先的に探索する。", "parameters": {"capability_ids": p["exploration"]["global_operator_capabilities"], "scope_modes": ["global"]}, "human_acceptance_required": False})
    if report_mode == "screening":
        items.append({"deliverable_id": "DELIV_SCREENING", "type": "screening_completed", "description": "当該RoundのResult Screeningとcompact summaryを完了する。", "parameters": {}, "human_acceptance_required": False})
    else:
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
        cumulative = bool(getattr(args, "cumulative_interpretation", False))
        historical_rescreening = bool(getattr(args, "historical_rescreening", False))
        if cumulative and historical_rescreening:
            raise ValueError("Cumulative Interpretation and historical re-Screening are separate Round types")
        requested_source_rounds = sorted(set(getattr(args, "source_round_id", None) or []))
        if requested_source_rounds and not (cumulative or historical_rescreening):
            raise ValueError("--source-round-id requires --cumulative-interpretation or --historical-rescreening")
        if cumulative or historical_rescreening:
            if cumulative and args.report_mode != "full":
                raise ValueError("Cumulative Interpretation requires --report-mode full")
            if historical_rescreening and args.report_mode != "screening":
                raise ValueError("Historical re-Screening requires --report-mode screening")
            if args.required_deliverables_json:
                raise ValueError("Report-only and re-Screening Rounds use a fixed deliverable")
            if historical_rescreening and not requested_source_rounds:
                raise ValueError("Historical re-Screening requires at least one explicit --source-round-id")
            source_rounds = requested_source_rounds or sorted(
                source_id for source_id, record in snapshot.get("rounds", {}).items()
                if record.get("state") == "CLOSED"
            )
            unknown = sorted(set(source_rounds) - set(snapshot.get("rounds", {})))
            not_closed = sorted(
                source_id for source_id in source_rounds
                if source_id in snapshot.get("rounds", {}) and snapshot["rounds"][source_id].get("state") != "CLOSED"
            )
            if unknown:
                raise ValueError(f"Unknown source Round: {unknown}")
            if not_closed:
                raise ValueError(f"Source Rounds must be CLOSED: {not_closed}")
            if not source_rounds:
                raise ValueError("At least one CLOSED source Round is required")
        else:
            source_rounds = []
        historical_bundles: list[dict[str, Any]] = []
        if historical_rescreening:
            historical_bundles = _historical_review_bundles(root, snapshot, source_rounds)
            if not historical_bundles:
                raise ValueError("No usable Review Bundle is available in the selected CLOSED source Rounds")
        round_id = f"RND{control['next_round_number']:04d}"
        request_payload = {
            "objective": args.objective,
            "report_mode": args.report_mode,
            "optional_directions": args.optional_direction or [],
            "human_priorities": args.human_priority or [],
            "budgets": {
                "walltime_minutes": args.walltime_minutes,
                "parallel_limit": args.parallel_limit or control["run"]["parallel_limit"],
                "available_cpu_cores": args.available_cpu_cores or _available_cpu_cores(control),
                "max_additional_nodes": 0 if (cumulative or historical_rescreening) else args.max_additional_nodes,
                "interpretation_iterations": args.interpretation_iterations,
            },
            "omissions": args.omission or [],
            "high_cost_bundle_approved": bool(args.approve_high_cost),
        }
        if cumulative:
            request_payload.update({
                "interpretation_scope": "cumulative_unreported",
                "source_round_ids": source_rounds,
            })
        elif historical_rescreening:
            request_payload.update({
                "screening_scope": "historical_closed_rounds",
                "source_round_ids": source_rounds,
                "target_bundle_ids": [bundle["bundle_id"] for bundle in historical_bundles],
                "target_bundle_set_hash": _review_bundle_set_hash(historical_bundles),
            })
        request_hash = value_hash(request_payload)
        if cumulative:
            required_deliverables = [{"deliverable_id": "DELIV_INTERPRETATION", "type": "interpretation_completed", "description": "既報Bundleを除外した累積Interpretationを生成する。", "parameters": {"source_round_ids": source_rounds}, "human_acceptance_required": False}]
        elif historical_rescreening:
            required_deliverables = [{"deliverable_id": "DELIV_HISTORICAL_RESCREENING", "type": "screening_completed", "description": "選択したCLOSED RoundのReview Bundleを再Screeningする。", "parameters": {"source_round_ids": source_rounds, "target_bundle_count": len(historical_bundles)}, "human_acceptance_required": False}]
        else:
            required_deliverables = _default_deliverables(snapshot, args.report_mode)
        contract = {"schema_version": "1.0.0", "round_id": round_id, **request_payload, "required_deliverables": required_deliverables, "request_hash": request_hash, "created_at": utc_now()}
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
        cumulative = contract.get("interpretation_scope") == "cumulative_unreported"
        historical_rescreening = contract.get("screening_scope") == "historical_closed_rounds"
        if historical_rescreening:
            available = _historical_review_bundles(root, snapshot, list(contract.get("source_round_ids") or []))
            if [bundle["bundle_id"] for bundle in available] != list(contract.get("target_bundle_ids") or []) or _review_bundle_set_hash(available) != contract.get("target_bundle_set_hash"):
                raise ValueError("Historical Review Bundle set changed after prepare-round; prepare a new authorization request")
        round_dir = root / "rounds" / round_id
        round_dir.mkdir(parents=True, exist_ok=False)
        write_json(round_dir / "round_contract.json", contract)
        started = datetime.now(timezone.utc)
        total_minutes = contract["budgets"]["walltime_minutes"]
        reserve = min(90, max(5, total_minutes // 5), max(1, total_minutes - 1))
        deadline = started + timedelta(minutes=contract["budgets"]["walltime_minutes"])
        snapshot["rounds"][round_id] = {"state": "ACTIVE", "runtime_version": VERSION, "report_mode": contract.get("report_mode", "full"), "interpretation_scope": contract.get("interpretation_scope", "current_round"), "screening_scope": contract.get("screening_scope", "current_round"), "source_round_ids": list(contract.get("source_round_ids") or []), "target_bundle_ids": list(contract.get("target_bundle_ids") or []), "started_at": started.isoformat(), "deadline_at": deadline.isoformat(), "soft_stop_at": (deadline - timedelta(minutes=reserve)).isoformat(), "scientific_finish_requested": False, "finish_reason": None, "human_checkpoint_requested": cumulative or historical_rescreening, "latest_audit": None, "current_interpretation_node": None, "current_screening_batch": None, "screening_summary_ref": None, "no_progress_returns": 0}
        if historical_rescreening:
            snapshot["rounds"][round_id]["result_rescreening"] = {
                "request_id": f"HRSCR-{round_id}",
                "status": "active",
                "reason": "Human-authorized historical re-Screening Round",
                "batch_size": int((profile().get("runtime_planning") or {}).get("screening_batch_size", 4)),
                "source_round_ids": list(contract.get("source_round_ids") or []),
                "target_bundle_ids": list(contract.get("target_bundle_ids") or []),
                "initial_target_count": len(contract.get("target_bundle_ids") or []),
                "requested_at": utc_now(),
                "completed_at": None,
            }
        maximum_analysis_nodes = min(_analysis_planning_limits()[0], int(contract["budgets"]["max_additional_nodes"]))
        snapshot["plans"][round_id] = {
            "basic_compute": False,
            "exploration": False,
            "exploration_nodes_planned": 0,
            "analysis_node_limit": maximum_analysis_nodes,
            "scope_sequence": ["global", "global", "local"],
        }
        # Assessment and Bundle indices are append-only Runtime-owned records.
        assessment_index = _assessment_index_path(root)
        if not assessment_index.exists():
            atomic_bytes(assessment_index, b"")
        control["conductor_version"] = VERSION
        control.setdefault("pointers", {})["result_assessment_index"] = str(
            assessment_index.relative_to(root)
        ).replace("\\", "/")
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
        report_mode = _round_report_mode(root, control, snapshot)
        now = datetime.now(timezone.utc)
        minutes = args.additional_walltime_minutes
        reserve = min(90, max(5, minutes // 5), max(1, minutes - 1))
        record.update({"state": "ACTIVE", "deadline_at": (now + timedelta(minutes=minutes)).isoformat(), "soft_stop_at": (now + timedelta(minutes=minutes - reserve)).isoformat(), "scientific_finish_requested": False, "finish_reason": None, "latest_audit": None, "screening_summary_ref": None})
        if report_mode == "full":
            record.update({"interpretation_revision_required": True, "interpretation_revision_serial": int(record.get("interpretation_revision_serial", 0)) + 1})
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
        if _round_report_mode(root, control, snapshot) != "full":
            raise ValueError("Report revision applies only to a full Interpretation Round")
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
        report_mode = _round_report_mode(root, control, snapshot)
        if report_mode == "screening":
            summary_fresh, summary_ref = _screening_summary_fresh(root, snapshot, round_id)
            expected_marker = f"screening:{summary_ref}" if summary_fresh and summary_ref else None
            if not summary_fresh or audit.get("status") != "pass" or audit.get("after_handoff_ref") != expected_marker:
                raise ValueError("Screening Summary and passing Full Audit are required")
        else:
            expected_marker = f"interpretation:{interpretation}" if interpretation else None
            audit_marker = audit.get("after_handoff_ref") or (f"interpretation:{audit.get('after_interpretation_node')}" if audit.get("after_interpretation_node") else None)
            if not interpretation or audit.get("status") != "pass" or audit_marker != expected_marker:
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


def _supports_standard_local_scope(capability: dict[str, Any]) -> bool:
    """Return whether the ordinary local-Operator planner may use this capability.

    Projection overlays, multi-scope models, and MMP local analysis have dedicated
    planners.  This guard prevents a Global-only Operator such as A012 from being
    materialized with a target Cluster merely because it appears in a human-managed
    profile list.
    """
    supported = set(capability.get("scope_support") or [])
    return bool(supported & {"within-cluster", "between-clusters"})


def _analysis_scope_supported(capability: dict[str, Any], scope: dict[str, Any], parameters: dict[str, Any]) -> bool:
    """Validate Runtime scope semantics before an Analysis Node is registered."""
    supported = set(capability.get("scope_support") or [])
    mode = str(scope.get("mode") or "global")
    defaults = capability.get("default_parameters") if isinstance(capability.get("default_parameters"), dict) else {}
    role = str(parameters.get("role") or defaults.get("role") or "")
    if mode == "global":
        required = role if role in {"projection-fit", "global-model"} else "global"
    elif mode == "projection":
        required = "cluster-overlay"
    elif mode == "single_cluster":
        required = "within-cluster"
    elif mode == "cluster_vs_cluster":
        required = "between-clusters"
    elif mode == "multi_scope":
        required = "cluster-survey"
    elif mode == "global_vs_cluster":
        required = "within-cluster"
    else:
        return False
    return required in supported


def _mmp_enabled_for_active_round(control: dict[str, Any], snapshot: dict[str, Any]) -> bool:
    """Keep A014 available only while a Runtime-owned Round is active."""
    round_id = control.get("active_round_id")
    return bool(round_id and str(round_id) in snapshot.get("rounds", {}))


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


def _exploration_local_specs(root: Path, control: dict[str, Any], snapshot: dict[str, Any], global_nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
                if not _supports_standard_local_scope(capability):
                    continue
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
                        # A Cluster overlay retains the complete Global projection
                        # and highlights one Cluster.  It is not a local-subset fit.
                        "scope": {"mode": "projection", "cluster_ids": [cluster_id]},
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
    _maximum, batch_size = _analysis_planning_limits()
    budget = _round_analysis_limit(root, control, snapshot)
    already_planned = _round_analysis_work_count(snapshot, control["active_round_id"])
    remaining_total = max(0, budget - already_planned)
    slice_budget = min(batch_size, remaining_total)
    settings = profile()["exploration"]
    global_slots = min(slice_budget, (2 * slice_budget + 2) // 3)
    global_specs = _history_balanced_specs(snapshot, _exploration_global_specs(control, snapshot), int(settings["random_seed"]))
    planned_global, _deferred_global = _materialize_analysis_specs(
        snapshot, control, global_specs, "exploration", batch_limit=global_slots, preserve_order=True,
    )
    lookup = _node_lookup(snapshot)
    global_nodes = [lookup[node_id] for node_id in planned_global]
    global_nodes.extend(node for node in _succeeded(snapshot, "analysis") if node.get("scope", {}).get("mode") == "global")
    remaining = max(0, slice_budget - len(planned_global))
    local_specs = _history_balanced_specs(snapshot, _exploration_local_specs(root, control, snapshot, global_nodes), int(settings["random_seed"]) + 1)
    planned_local, _deferred_local = _materialize_analysis_specs(
        snapshot, control, local_specs, "exploration", batch_limit=remaining, preserve_order=True,
    )
    planned = list(dict.fromkeys([*planned_global, *planned_local]))
    plan = snapshot["plans"][control["active_round_id"]]
    plan.update({
        "exploration": True,
        "exploration_nodes_planned": int(plan.get("exploration_nodes_planned", 0)) + len(planned),
        "global_nodes_planned": int(plan.get("global_nodes_planned", 0)) + len(planned_global),
        "local_nodes_planned": int(plan.get("local_nodes_planned", 0)) + len(planned_local),
        "selection_seed": int(settings["random_seed"]),
        "scope_sequence": list(settings["scope_sequence"]),
    })
    return planned


def _candidate_cells(root: Path, control: dict[str, Any], snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    p = profile()
    contract = _active_contract(root, control)
    round_plan = snapshot.get("plans", {}).get(str(control.get("active_round_id")), {})
    maximum = _round_analysis_limit(root, control, snapshot)
    if _round_analysis_work_count(snapshot, control["active_round_id"]) >= maximum:
        return []
    if contract and _round_analysis_work_count(snapshot, control["active_round_id"]) >= maximum:
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
            # The regular DAG contains one reusable Global A014 Database only.
            # Cluster-projected MMP interpretation is an explicit, read-only I002 request.
            if capability_id == "A014" and scope_mode == "local":
                continue
            for input_nodes in _analysis_inputs(capability, descriptions, clusterings, scope_mode):
                scopes = [{"mode": "global"}] if scope_mode == "global" else [{"mode": "single_cluster", "cluster_ids": [row["cluster_id"]]} for row in _cluster_rows(root, next((item for item in input_nodes if _node_lookup(snapshot)[item]["kind"] == "clustering"), None))[:4]]
                for scope in scopes:
                    if capability_id == "A014":
                        parameters = {"role": "global-build"}
                    else:
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
        maximum = _round_analysis_limit(root, control, snapshot)
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
            deliverables = [item for item in _deliverable_status(root, control, snapshot) if item["type"] not in {"interpretation_completed", "screening_completed"}]
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

    _result_path_value, result = _canonical_result(node)
    path = _primary_payload(node)
    frame = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path, dtype={"compound_id": "string"})
    if "compound_id" not in frame.columns:
        return None
    declared = [str(column) for column in result.get("feature_columns") or []]
    missing = [column for column in declared if column not in frame.columns]
    if missing:
        raise ValueError(f"Description payload is missing canonical feature columns: {missing[:10]}")
    if declared:
        features = declared
    else:
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
    # A003/A004 Cluster overlays preserve every point from the prior Global
    # projection and only mark Cluster membership.  Older planners recorded
    # these Nodes as single_cluster, so normalize by scientific role as well as by
    # the corrected projection scope used for newly planned Nodes.
    if node.get("capability_id") in {"A003", "A004"} and node.get("parameters", {}).get("role") == "cluster-overlay":
        scope_mode = "projection"
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


def _finite_scalar(value: Any) -> Any:
    value = clean(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value if value is None or isinstance(value, (str, int, float, bool)) else None


def _metric_source_value(details: dict[str, Any], source: str) -> Any:
    """Resolve a dotted path; ``a|b`` declares deterministic fallbacks."""
    for candidate in source.split("|"):
        value: Any = details
        found = True
        for part in candidate.split("."):
            if not isinstance(value, dict) or part not in value:
                found = False
                break
            value = value[part]
        if found:
            scalar = _finite_scalar(value)
            if scalar is not None:
                return scalar
    return None


def _compact_operator_details(details: dict[str, Any], limit: int = 24) -> dict[str, Any]:
    """Preserve small provenance fields without duplicating large result payloads."""
    compact: dict[str, Any] = {}
    for key in sorted(details):
        value = clean(details[key])
        scalar = _finite_scalar(value)
        if scalar is not None:
            compact[str(key)] = scalar
        elif isinstance(value, list) and len(value) <= 10 and all(_finite_scalar(item) is not None for item in value):
            compact[str(key)] = [_finite_scalar(item) for item in value]
        elif isinstance(value, dict) and len(value) <= 8 and all(_finite_scalar(item) is not None for item in value.values()):
            compact[str(key)] = {str(name): _finite_scalar(item) for name, item in value.items()}
        if len(compact) >= limit:
            break
    return compact


def _comparison_parameters(node: dict[str, Any]) -> dict[str, Any]:
    return {str(key): clean(value) for key, value in sorted((node.get("parameters") or {}).items()) if key not in COMPARISON_PARAMETER_EXCLUSIONS}


def _comparison_family_id(control: dict[str, Any], node: dict[str, Any], subject: dict[str, Any], metric: str | None, profile_id: str) -> str:
    basis = {
        "capability_id": node["capability_id"],
        "profile_id": profile_id,
        "endpoint": {"column": control["run"]["endpoint"], "unit": control["run"].get("endpoint_unit"), "transform": control["run"].get("endpoint_transform"), "higher_is_better": bool(control["run"]["higher_is_better"])},
        "analysis_description_nodes": sorted(subject.get("analysis_description_nodes") or []),
        "metric": metric,
        "operator_parameters": _comparison_parameters(node),
        "reference_population": control["run"].get("input_hash"),
    }
    return "CFM" + value_hash(basis)[:16]


def _result_card_v2(control: dict[str, Any], node: dict[str, Any], subject: dict[str, Any], summary: dict[str, Any], result_ref: str, artifact_links: dict[str, str | None]) -> dict[str, Any]:
    capability = catalog()[node["capability_id"]]
    interpretation_profile = capability.get("interpretation_profile")
    if not isinstance(interpretation_profile, dict):
        raise ValueError(f"{node['capability_id']} has no Operator Interpretation Profile")
    validate(interpretation_profile, "operator_interpretation_profile.schema.json")
    details = dict(summary.get("key_metrics") or {})
    if node["capability_id"] == "A014":
        details.pop("mmp_reference_candidates", None)
        details["specialized_interpretation"] = "cs-analysis-interpret-mmp"
    comparison_metrics = []
    for spec in interpretation_profile["comparison_metrics"]:
        raw_metric = _metric_source_value(details, spec["source"])
        normalized: float | None = None
        if isinstance(raw_metric, (int, float)) and not isinstance(raw_metric, bool):
            if spec["direction"] == "favorable":
                normalized = float(raw_metric) if control["run"]["higher_is_better"] else -float(raw_metric)
            elif spec["direction"] == "higher":
                normalized = float(raw_metric)
            elif spec["direction"] == "lower":
                normalized = -float(raw_metric)
        comparison_metrics.append({"name": spec["name"], "value": raw_metric, "normalized_favorable_value": normalized, "unit": spec.get("unit"), "direction": spec["direction"], "comparison_scope": spec["comparison_scope"]})
    metric_by_name = {item["name"]: item for item in comparison_metrics}
    primary_name = interpretation_profile.get("primary_favorable_metric")
    primary = metric_by_name.get(primary_name) if primary_name else None
    raw_value = primary.get("value") if primary and isinstance(primary.get("value"), (int, float)) and not isinstance(primary.get("value"), bool) else None
    favorable_value = primary.get("normalized_favorable_value") if primary else None
    normalization = "higher_is_better" if primary and primary["direction"] == "favorable" else "profile_fixed" if primary and primary["direction"] in {"higher", "lower"} else "not_applicable"
    minimum = interpretation_profile["minimum_support"]["global" if subject["scope_mode"] == "global" else "local"]
    analyzed = int(subject["analyzed_count"])
    population = int(subject["population_count"])
    quality_flags = ["negative_result"] if details.get("negative_result") is True else []
    available_metric_count = sum(
        1
        for item in comparison_metrics
        if isinstance(item.get("value"), (int, float)) and not isinstance(item.get("value"), bool)
    )
    if comparison_metrics and available_metric_count == 0:
        quality_flags.append("missing_comparison_metrics")
    if primary_name is not None and favorable_value is None:
        quality_flags.append("missing_primary_favorable_metric")
    if analyzed < int(minimum):
        quality_flags.append("below_interpretation_minimum_support")
    card = {
        "schema_version": "2.0.0", "result_ref": result_ref, "node_id": node["node_id"], "capability_id": node["capability_id"], "round_id": node["assigned_round"],
        "analysis_subject": subject,
        "endpoint": {"column": control["run"]["endpoint"], "higher_is_better": bool(control["run"]["higher_is_better"]), "unit": control["run"].get("endpoint_unit"), "transform": control["run"].get("endpoint_transform")},
        "metric": summary.get("metric"), "headline": str(summary.get("headline") or f"{node['capability_id']} completed"),
        "result_role": interpretation_profile["result_role"], "interpretation_profile_id": interpretation_profile["profile_id"],
        "comparison_family_id": _comparison_family_id(control, node, subject, summary.get("metric"), interpretation_profile["profile_id"]),
        "favorable_payload": {"applicable": primary_name is not None, "normalization": normalization, "source_metric": primary_name, "raw_value": raw_value, "favorable_value": favorable_value, "favorable_effect": None, "direction_confidence": "derived" if favorable_value is not None else "unknown" if primary_name else "not_applicable"},
        "comparison_metrics": comparison_metrics, "operator_details": _compact_operator_details(details),
        "quality": {"population_count": population, "endpoint_valid_count": int(subject["endpoint_valid_count"]), "analyzed_count": analyzed, "excluded_count": int(subject["excluded_count"]), "sample_fraction": analyzed / max(1, population), "minimum_support_met": analyzed >= int(minimum)},
        "validation_passed": True, "eligible_for_downstream": True, "quality_flags": sorted(set(quality_flags)), "limitations": [str(item) for item in (summary.get("limitations") or [])],
        "artifact_links": artifact_links, "attention": "watch", "created_at": utc_now(),
    }
    validate(card, "result_card.schema.json")
    return card


def _promote_a005_oof_artifact(
    node: dict[str, Any],
    skill_output: Path,
    output: Path,
    artifacts: dict[str, dict[str, Any]],
) -> str | None:
    if node.get("capability_id") != "A005" or "oof_predictions" not in artifacts:
        return None
    prediction = artifacts["oof_predictions"]
    role = node.get("parameters", {}).get("role") or "global-model"
    expected_name = "global_oof_predictions.csv" if role == "global-model" else "cluster_oof_predictions.csv"
    if Path(prediction["path"]).name != expected_name:
        raise ValueError(f"A005 OOF Artifact filename mismatch: expected {expected_name}")
    _copy_artifact(
        _skill_artifact_path(skill_output, prediction["path"]),
        output / expected_name,
        prediction["sha256"],
    )
    return expected_name


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
        card = _result_card_v2(control, node, subject, summary, result_ref, artifact_links)
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
                local_links = {"result": _run_relative_artifact(root, final / local_relative), "report": _run_relative_artifact(root, final / report_name), "detail": _run_relative_artifact(root, final / detail_name) if detail_name else None}
                local_card = _result_card_v2(control, local_node, local_subject, local_summary, str(local_summary["result_ref"]), local_links)
                card_file = f"result_card_{cluster_id}.json"
                write_json(temporary / card_file, local_card)
                result_card_files.append(card_file)
                result_cards.append(local_card)
        result_payloads = {"detail_report": detail_name} if detail_name else {}
        result_payloads.update(mmp_payloads)
        result = {"document_type": "analysis_result", "schema_version": "1.0.0", "node_id": node["node_id"], "capability_id": node["capability_id"], "analysis_subject": subject, "primary_payload": primary_name, "report": report_name, "result_cards": result_card_files, "payloads": result_payloads, "created_at": utc_now()}
        validate(result, "analysis_result.schema.json")
        write_json(temporary / "result.json", result)
        _promote_a005_oof_artifact(node, skill_output, temporary, artifacts)
        for name in ("cluster_model_comparison.csv", "projection.png"):
            if (skill_output / name).is_file():
                _copy_artifact(skill_output / name, temporary / name)
    else:
        raise ValueError("Interpretation is committed through the dedicated gate")
    if final.exists():
        raise FileExistsError(f"Committed Node output already exists: {final}")
    final.parent.mkdir(parents=True, exist_ok=True)
    atomic_replace(temporary, final)
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


def _successful_node_quality(node: dict[str, Any], *, recovered: bool = False) -> dict[str, Any]:
    """Return post-validation quality without retaining an earlier failed Attempt."""
    current = node.get("result_quality") or {}
    if node.get("kind") == "clustering" and current.get("validation_passed"):
        quality = dict(current)
    else:
        quality = {"validation_passed": True, "eligible_for_downstream": True, "quality_flags": []}
    if recovered:
        quality["quality_flags"] = sorted(set(quality.get("quality_flags") or []) | {"recovered_after_interruption"})
    return quality


def _claim_execution_packet(root: Path, packet_path: Path) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """Atomically bind a packet to Attempts before starting an OS worker."""
    selected: list[tuple[dict[str, Any], dict[str, Any], Path, list[str]]] = []
    prepared_commands: list[tuple[dict[str, Any], str, Path, list[str], list[str]]] = []
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        existing = _read_packet_status(packet_path)
        if existing and existing["status"] != "claiming":
            packet = _validate_execution_packet_authentic(root, packet_path)
            _require_packet_status_identity(packet, existing)
            return packet, existing, False
        if existing and existing["status"] == "claiming":
            packet = _validate_execution_packet_authentic(root, packet_path)
            _require_packet_status_identity(packet, existing)
            lookup = _node_lookup(snapshot)
            already_bound = all(
                (node := lookup.get(contract["node_id"]))
                and node.get("status") == "running"
                and node.get("current_attempt_id") == contract["attempt_id"]
                and any(
                    attempt.get("attempt_id") == contract["attempt_id"]
                    and attempt.get("packet_id") == packet["packet_id"]
                    for attempt in node.get("attempts") or []
                )
                for contract in packet["execution_contracts"]
            )
            if already_bound:
                existing["status"] = "claimed"
                _write_packet_status(packet_path, existing)
                return packet, existing, False
        packet = _validate_execution_packet(root, control, packet_path)
        timeout_minutes = int(packet["timeout_minutes"])
        if timeout_minutes < 1:
            raise ValueError("Node timeout must be at least one minute")
        soft_stop = parse_time(snapshot["rounds"][control["active_round_id"]].get("soft_stop_at"))
        now = datetime.now(timezone.utc)
        if soft_stop and now >= soft_stop:
            raise ValueError("Scientific execution window has ended; refresh control and enter finalizing")
        remaining_seconds = max(1, int((soft_stop - now).total_seconds())) if soft_stop else timeout_minutes * 60
        execution_timeout_seconds = min(timeout_minutes * 60, remaining_seconds)
        runnable = {node["node_id"]: node for node in _runnable(control, snapshot)}
        requested = list(packet["node_ids"])
        if not requested:
            raise ValueError("No runnable Nodes")
        if set(requested) - set(runnable):
            raise ValueError(f"Requested Nodes are not currently runnable: {sorted(set(requested) - set(runnable))}")
        requested = _select_execution_nodes(requested, runnable, control)
        if requested != list(packet["node_ids"]):
            raise PermissionError("Execution packet selection changed after packet creation")
        contract_lookup = {item["node_id"]: item for item in packet.get("execution_contracts", [])}
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
        status = {
            "schema_version": "1.0.0", "protocol_version": PROTOCOL_VERSION,
            "packet_id": packet["packet_id"], "run_id": packet["run_id"], "round_id": packet["round_id"],
            "status": "claiming", "node_ids": requested, "worker_pid": None,
            "worker_host": None, "launcher_pid": os.getpid(),
            "execution_timeout_seconds": execution_timeout_seconds,
            "clean_scratch": bool(packet["clean_scratch"]), "created_at": utc_now(), "updated_at": utc_now(),
        }
        _write_packet_status(packet_path, status)
        for node, attempt_id, scratch, command, resolved_command in prepared_commands:
            if not scratch.exists():
                scratch.mkdir(parents=True, exist_ok=False)
            attempt = {
                "attempt_id": attempt_id, "packet_id": packet["packet_id"], "status": "running",
                "started_at": utc_now(), "finished_at": None, "command_argv": command,
                "scratch": str(scratch),
                "log": str((root / "runtime" / "logs" / f"{node['node_id']}_{attempt_id}.log").relative_to(root)),
            }
            node["attempts"].append(attempt)
            node["current_attempt_id"] = attempt_id
            node["status"] = "running"
            selected.append((node, attempt, scratch, resolved_command))
        control["lease"]["expires_at"] = (
            now + timedelta(seconds=execution_timeout_seconds, minutes=EXECUTION_LEASE_GRACE_MINUTES)
        ).isoformat()
        _commit(
            root, control, snapshot, "batch_started",
            {
                "packet_id": packet["packet_id"],
                "nodes": [{"node_id": node["node_id"], "attempt_id": attempt["attempt_id"], "command_argv": attempt["command_argv"]} for node, attempt, _scratch, _resolved_command in selected],
                "execution_timeout_seconds": execution_timeout_seconds,
            },
            round_id=control["active_round_id"],
        )
        status["status"] = "claimed"
        _write_packet_status(packet_path, status)
    return packet, status, True


def _runtime_worker_selection(root: Path, packet: dict[str, Any]) -> tuple[dict[str, Any], list[tuple[dict[str, Any], dict[str, Any], Path, list[str]]]]:
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        _require_worker_followup(snapshot, packet)
        lookup = _node_lookup(snapshot)
        contracts = {item["node_id"]: item for item in packet["execution_contracts"]}
        selected: list[tuple[dict[str, Any], dict[str, Any], Path, list[str]]] = []
        for node_id in packet["node_ids"]:
            node = lookup[node_id]
            contract = contracts[node_id]
            attempt = next(item for item in node["attempts"] if item["attempt_id"] == contract["attempt_id"])
            scratch = Path(attempt["scratch"])
            command = _resolve_skill_command(list(contract["command_argv"]))
            if value_hash(attempt["command_argv"]) != contract["command_hash"]:
                raise PermissionError(f"Claimed command changed: {node_id}")
            selected.append((node, attempt, scratch, command))
        return control, selected


def _commit_packet_outcomes(root: Path, packet: dict[str, Any], outcomes: dict[str, dict[str, Any]], clean_scratch: bool) -> tuple[dict[str, Any], list[str], list[str]]:
    committed: list[str] = []
    failed: list[str] = []
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        _require_worker_followup(snapshot, packet)
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
                node.update({"status": "succeeded", "current_attempt_id": None, "finished_at": utc_now(), "result_quality": _successful_node_quality(node)})
                attempt.update({"status": "succeeded", "finished_at": node["finished_at"]})
                committed.append(node_id)
                event_payload.append({"node_id": node_id, "attempt_id": attempt["attempt_id"], "status": "succeeded", "result_refs": [card["result_ref"] for card in cards]})
                if clean_scratch:
                    shutil.rmtree(scratch, ignore_errors=True)
            except Exception as exc:
                failure_path = _write_failure_packet(root, node, attempt, outcome, exc)
                failure_packet = read_json(failure_path)
                node.update({"status": "failed", "current_attempt_id": None, "finished_at": utc_now(), "result_quality": {"validation_passed": False, "eligible_for_downstream": False, "quality_flags": ["technical_failure"]}})
                attempt.update({"status": "failed", "finished_at": node["finished_at"], "error": str(exc), "returncode": outcome["returncode"], "failure_classification": failure_packet["classification"], "failure_packet": str(failure_path.relative_to(root))})
                failed.append(node_id)
                event_payload.append({"node_id": node_id, "attempt_id": attempt["attempt_id"], "status": "failed", "failure_code": failure_packet["classification"], "recoverable": failure_packet["recoverable"], "failure_pointer": str(failure_path.relative_to(root))})
        control["lease"]["heartbeat_at"] = utc_now()
        control["lease"]["expires_at"] = (datetime.now(timezone.utc) + timedelta(minutes=DEFAULT_LEASE_MINUTES)).isoformat()
        _commit(root, control, snapshot, "batch_reconciled", {"packet_id": packet["packet_id"], "outcomes": event_payload}, round_id=control["active_round_id"])
        _write_working_set(root, control, snapshot)
    return control, committed, failed


def _run_claimed_packet_worker(root: Path, packet_path: Path) -> int:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    packet = _validate_execution_packet_authentic(root, packet_path)
    with writer_lock(root):
        status = _read_packet_status(packet_path)
        if not status or status["status"] not in {"claimed", "launching", "running"}:
            raise PermissionError("Runtime Worker packet is not in a claimed state")
        _require_packet_status_identity(packet, status)
        status.update({"status": "running", "worker_pid": os.getpid(), "worker_host": socket.gethostname(), "launcher_pid": None, "started_at": status.get("started_at") or utc_now()})
        _write_packet_status(packet_path, status)
    control, selected = _runtime_worker_selection(root, packet)
    outcomes: dict[str, dict[str, Any]] = {}
    timeout_seconds = int(status["execution_timeout_seconds"])
    with ThreadPoolExecutor(max_workers=len(selected)) as executor:
        futures = {
            executor.submit(
                _run_one, command, root / attempt["log"], scratch / "process.json", timeout_seconds,
                value_hash(attempt["command_argv"]), _node_cpu_allocation(control, node),
                _available_cpu_cores(control), _native_thread_limit(control, node),
            ): (node, attempt, scratch)
            for node, attempt, scratch, command in selected
        }
        for future in as_completed(futures):
            node, attempt, scratch = futures[future]
            try:
                outcome = future.result()
            except Exception as exc:
                outcome = {"returncode": 125, "timed_out": False, "started_at": attempt["started_at"], "finished_at": utc_now(), "runner_error": str(exc)}
            outcomes[node["node_id"]] = {**outcome, "attempt_id": attempt["attempt_id"], "scratch": str(scratch)}
    control, committed, failed = _commit_packet_outcomes(root, packet, outcomes, bool(status["clean_scratch"]))
    status.update({
        "status": "terminal", "finished_at": utc_now(), "succeeded_count": len(committed),
        "failed_count": len(failed), "affected_node_ids": committed + failed,
        "returncode": 1 if failed and not committed else 0, "error": None,
    })
    _write_packet_status(packet_path, status)
    return int(status["returncode"])


def _spawn_runtime_worker(root: Path, packet_path: Path) -> dict[str, Any]:
    with writer_lock(root):
        packet = _validate_execution_packet_authentic(root, packet_path)
        status = _read_packet_status(packet_path)
        if not status:
            raise FileNotFoundError("Runtime Worker status is missing")
        _require_packet_status_identity(packet, status)
        if status["status"] == "terminal":
            return status
        if status.get("worker_pid") and pid_alive(int(status["worker_pid"])):
            return status
        if status["status"] == "launching" and status.get("launcher_pid") and int(status["launcher_pid"]) != os.getpid() and pid_alive(int(status["launcher_pid"])):
            return status
        if status["status"] not in {"claimed", "claiming", "launching"}:
            return status
        status.update({"status": "launching", "launcher_pid": os.getpid()})
        _write_packet_status(packet_path, status)
        worker_log = packet_path.parent / "worker.log"
        command = [sys.executable, str(Path(__file__).resolve()), "_worker-execute-packet", "--run-root", str(root), "--packet", str(packet_path)]
        popen_options: dict[str, Any] = {"cwd": project_root(), "stdin": subprocess.DEVNULL, "close_fds": True}
        if os.name == "posix":
            popen_options["start_new_session"] = True
        elif os.name == "nt":
            popen_options["creationflags"] = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
        try:
            with worker_log.open("a", encoding="utf-8", errors="replace") as log_handle:
                process = subprocess.Popen(command, stdout=log_handle, stderr=subprocess.STDOUT, **popen_options)
        except Exception as exc:
            status.update({"status": "worker_start_failed", "finished_at": utc_now(), "returncode": 125, "error": str(exc)[:2000]})
            _write_packet_status(packet_path, status)
            raise
        status.update({"status": "running", "worker_pid": process.pid, "worker_host": socket.gethostname(), "launcher_pid": None, "started_at": status.get("started_at") or utc_now()})
        _write_packet_status(packet_path, status)
    return status


def _wait_for_packet(root: Path, packet_path: Path, poll_seconds: float = 5.0) -> tuple[dict[str, Any], dict[str, Any]]:
    packet = _validate_execution_packet_authentic(root, packet_path)
    while True:
        status = _read_packet_status(packet_path)
        if not status:
            raise FileNotFoundError("Runtime Worker status is missing")
        _require_packet_status_identity(packet, status)
        if status["status"] in {"terminal", "worker_start_failed"}:
            return read_json(control_path(root)), status
        worker_pid = int(status.get("worker_pid") or -1)
        launcher_pid = int(status.get("launcher_pid") or -1)
        if not pid_alive(worker_pid) and not pid_alive(launcher_pid):
            control, snapshot = _read_state(root)
            lookup = _node_lookup(snapshot)
            terminal_attempts: list[tuple[str, str]] = []
            for contract in packet["execution_contracts"]:
                node = lookup.get(contract["node_id"])
                attempt = next(
                    (item for item in (node or {}).get("attempts", []) if item.get("attempt_id") == contract["attempt_id"] and item.get("packet_id") == packet["packet_id"]),
                    None,
                )
                if not node or not attempt or node.get("status") == "running" or attempt.get("status") not in {"succeeded", "failed"}:
                    terminal_attempts = []
                    break
                terminal_attempts.append((node["node_id"], attempt["status"]))
            if terminal_attempts and len(terminal_attempts) == len(packet["execution_contracts"]):
                succeeded = [node_id for node_id, attempt_status in terminal_attempts if attempt_status == "succeeded"]
                failed = [node_id for node_id, attempt_status in terminal_attempts if attempt_status == "failed"]
                status.update({
                    "status": "terminal", "finished_at": utc_now(), "succeeded_count": len(succeeded),
                    "failed_count": len(failed), "affected_node_ids": succeeded + failed,
                    "returncode": 1 if failed and not succeeded else 0, "error": None,
                })
                _write_packet_status(packet_path, status)
                return control, status
            return control, {**status, "status": "worker_start_failed", "returncode": 125, "error": "Runtime Worker disappeared before publishing a terminal result"}
        time.sleep(max(1.0, poll_seconds))


def _record_worker_boundary_failure(
    root: Path,
    packet_path: Path,
    failure_status: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Persist a lost-worker boundary without guessing a scientific outcome."""
    with writer_lock(root):
        _recover_transaction(root)
        packet = _validate_execution_packet_authentic(root, packet_path)
        current = _read_packet_status(packet_path)
        if not current:
            raise FileNotFoundError("Runtime Worker status is missing")
        _require_packet_status_identity(packet, current)
        if current["status"] == "terminal":
            return read_json(control_path(root)), current
        current.update(
            {
                "status": "worker_start_failed",
                "finished_at": failure_status.get("finished_at") or utc_now(),
                "returncode": int(failure_status.get("returncode") or 125),
                "error": str(failure_status.get("error") or "Runtime Worker boundary failure")[:2000],
            }
        )
        _write_packet_status(packet_path, current)
        control, snapshot = _read_state(root)
        lookup = _node_lookup(snapshot)
        affected = [
            contract["node_id"]
            for contract in packet["execution_contracts"]
            if (node := lookup.get(contract["node_id"]))
            and node.get("status") == "running"
            and node.get("current_attempt_id") == contract["attempt_id"]
        ]
        running_nodes = [item for item in snapshot["nodes"] if item.get("status") == "running"]
        effective = _running_action(root, snapshot, running_nodes) if running_nodes else control["required_action"]
        if affected and control["required_action"].get("code") != effective.get("code"):
            _commit(
                root,
                control,
                snapshot,
                "runtime_worker_boundary_failure",
                {
                    "packet_id": packet["packet_id"],
                    "node_ids": affected,
                    "error": current["error"],
                },
                round_id=packet["round_id"],
            )
            control = read_json(control_path(root))
        return control, current


def cmd_execute_packet(args: argparse.Namespace) -> int:
    """Idempotently submit and await a detached deterministic Runtime Worker."""
    root = resolve_root(args.run_root)
    packet_path = Path(args.packet).resolve()
    packet, status, claimed = _claim_execution_packet(root, packet_path)
    if status["status"] not in {"terminal", "worker_start_failed"}:
        status = _spawn_runtime_worker(root, packet_path)
    control, terminal = _wait_for_packet(root, packet_path)
    if terminal["status"] == "worker_start_failed":
        control, terminal = _record_worker_boundary_failure(root, packet_path, terminal)
    _print_compact(
        control,
        detail_pointer=str((root / "runtime" / "logs").relative_to(root)),
        packet_id=packet["packet_id"], worker_status=terminal["status"],
        worker_pid=terminal.get("worker_pid"), succeeded_count=int(terminal.get("succeeded_count") or 0),
        failed_count=int(terminal.get("failed_count") or 0), affected_node_ids=(terminal.get("affected_node_ids") or [])[:50],
        state_changed=claimed, error=terminal.get("error"),
        reconcile_required=(control.get("required_action") or {}).get("code") == "RECONCILE_RUNNING",
    )
    return int(terminal.get("returncode") or 0)


def cmd_worker_execute_packet(args: argparse.Namespace) -> int:
    try:
        return _run_claimed_packet_worker(resolve_root(args.run_root), Path(args.packet).resolve())
    except Exception as exc:
        root = resolve_root(args.run_root)
        packet_path = Path(args.packet).resolve()
        try:
            _record_worker_boundary_failure(
                root,
                packet_path,
                {"status": "worker_start_failed", "finished_at": utc_now(), "returncode": 125, "error": str(exc)[:2000]},
            )
        except Exception:
            # Last-resort diagnostic persistence when the signed packet itself
            # cannot be validated. Do not guess or mutate a Node outcome.
            with writer_lock(root):
                status = _read_packet_status(packet_path)
                if status and status["status"] != "terminal":
                    status.update({"status": "worker_start_failed", "finished_at": utc_now(), "returncode": 125, "error": str(exc)[:2000]})
                    _write_packet_status(packet_path, status)
        finally:
            print(f"Runtime Worker failure: {exc}", file=sys.stderr)
        return 125


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
        _require_action(control, args.lease_token, {"WAIT_RUNNING", "RECONCILE_RUNNING"})
        running_nodes = [item for item in snapshot["nodes"] if item["status"] == "running"]
        effective = _running_action(root, snapshot, running_nodes) if running_nodes else control["required_action"]
        if running_nodes and effective["code"] == "WAIT_RUNNING":
            _print_compact(
                control,
                state_changed=False,
                worker_state="live",
                affected_node_ids=effective.get("node_ids", []),
                packet_ids=effective.get("packet_ids", []),
            )
            return 0
        for node in running_nodes:
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
                node.update({"status": "succeeded", "current_attempt_id": None, "finished_at": utc_now(), "result_quality": _successful_node_quality(node, recovered=True)})
                attempt.update({"status": "succeeded", "finished_at": node["finished_at"], "recovered": True})
                reconciled.append({"node_id": node["node_id"], "status": "succeeded", "result_refs": result_refs})
            except Exception as exc:
                final = Path(node["output_ref"])
                if final.exists():
                    quarantine = root / "runtime" / "quarantine" / f"{node['node_id']}_{timestamp()}"
                    quarantine.parent.mkdir(parents=True, exist_ok=True)
                    atomic_replace(final, quarantine)
                node.update({"status": "failed", "current_attempt_id": None, "finished_at": utc_now(), "result_quality": {"validation_passed": False, "eligible_for_downstream": False, "quality_flags": ["interrupted_without_committable_result"]}})
                attempt.update({"status": "failed", "finished_at": node["finished_at"], "error": str(exc), "recovered": True})
                reconciled.append({"node_id": node["node_id"], "status": "failed", "error": str(exc)})
        if reconciled:
            _commit(root, control, snapshot, "running_attempts_reconciled", {"outcomes": reconciled}, round_id=control["active_round_id"])
            _write_working_set(root, control, snapshot)
    _print_compact(control, outcome_count=len(reconciled), outcomes=reconciled[:50])
    return 0


def cmd_retry_node(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        action = control["required_action"]["code"]
        human_override = action == "EXECUTE_RUNNABLE_BATCH" and bool(args.control_key)
        if human_override:
            _require_action(control, args.lease_token)
            _require_control_authority(root, args.control_key)
            if any(item["status"] == "running" for item in snapshot["nodes"]):
                raise ValueError("Wait for every running Node to become terminal before a human-authorized retry")
        else:
            _require_action(control, args.lease_token, {"RETRY_FAILED_NODE", "FAILED_NODE_REPAIR_REQUIRED"})
        if control["round_state"] != "ACTIVE":
            raise ValueError("A scientific Node can be retried only while the Round is ACTIVE")
        node = _node_lookup(snapshot).get(args.node_id)
        if not node or node["status"] != "failed":
            raise ValueError("Only a failed Node can be retried")
        if not human_override and control["required_action"].get("node_id") != node["node_id"]:
            raise ValueError("Runtime selected a different failed Node for bounded retry")
        human_repair = action == "FAILED_NODE_REPAIR_REQUIRED" or human_override
        if len(node.get("attempts") or []) >= MAX_EXECUTION_ATTEMPTS and not human_repair:
            raise ValueError("The bounded retry allowance for this Node is exhausted")
        node["status"] = "pending"
        node["finished_at"] = None
        node["assigned_round"] = control["active_round_id"]
        _commit(
            root,
            control,
            snapshot,
            "node_retry_requested",
            {"reason": args.reason, "human_override": human_override},
            round_id=control["active_round_id"],
            node_id=node["node_id"],
        )
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


def _assessment_index_path(root: Path) -> Path:
    return root / "runtime" / "result_assessment_index.jsonl"


def _bundle_index_path(root: Path) -> Path:
    return root / "runtime" / "review_bundle_index.jsonl"


def _latest_assessments(root: Path) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(_assessment_index_path(root)):
        previous = latest.get(row["bundle_id"])
        if previous is None or int(row.get("revision", 0)) >= int(previous.get("revision", 0)):
            latest[row["bundle_id"]] = row
    return latest


def _assessment_is_current(bundle: dict[str, Any], assessment: dict[str, Any] | None) -> bool:
    return bool(
        assessment
        and assessment.get("source_hash") == bundle.get("source_hash")
        and assessment.get("rubric_version") == SCREENING_RUBRIC_VERSION
        and assessment.get("assessment_status") in {"evaluated", "not_scorable", "awaiting_comparator"}
    )


def _usable_result_cards(root: Path, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    lookup = _node_lookup(snapshot)
    cards: dict[str, dict[str, Any]] = {}
    for card in read_jsonl(root / "runtime" / "result_index.jsonl"):
        source = lookup.get(card.get("node_id"))
        if source and source.get("kind") == "analysis" and source.get("status") == "succeeded" and (source.get("result_quality") or {}).get("eligible_for_downstream", True):
            cards[card["result_ref"]] = card
    return sorted(cards.values(), key=lambda card: card["result_ref"])


def _review_bundle_set_hash(bundles: list[dict[str, Any]]) -> str:
    """Freeze the exact historical Bundle versions authorized by a human."""
    return value_hash([
        (bundle["bundle_id"], bundle["source_hash"], bundle["round_id"])
        for bundle in sorted(bundles, key=lambda item: item["bundle_id"])
    ])


def _historical_review_bundles(
    root: Path,
    snapshot: dict[str, Any],
    source_round_ids: list[str],
) -> list[dict[str, Any]]:
    """Load immutable evidence Bundles from CLOSED Rounds for a new re-Screening Round."""
    source_set = set(source_round_ids)
    latest_stored: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(_bundle_index_path(root)):
        if row.get("round_id") in source_set and row.get("comparison_status") != "awaiting_comparator":
            latest_stored[str(row["bundle_id"])] = row
    usable_refs = {card["result_ref"] for card in _usable_result_cards(root, snapshot)}
    unavailable: list[str] = []
    resolved: list[dict[str, Any]] = []
    for row in latest_stored.values():
        bundle = json.loads(json.dumps(row))
        missing_refs = set(bundle.get("all_result_refs") or []) - usable_refs
        if missing_refs:
            unavailable.append(f"{bundle['bundle_id']}:{','.join(sorted(missing_refs)[:3])}")
            continue
        profile_value = catalog()[bundle["capability_id"]]["interpretation_profile"]
        bundle["evaluation_anchors"] = {
            axis: list(profile_value.get("anchors", {}).get(axis) or [])
            for axis in bundle.get("applicable_axes") or []
        }
        # The historical Result evidence and comparisons remain frozen.  Only
        # the current rubric anchors are attached, making their change visible
        # through source_hash and therefore through Assessment freshness.
        bundle["source_hash"] = value_hash({
            key: value for key, value in bundle.items()
            if key not in {"source_hash", "created_at"}
        })
        validate(bundle, "review_bundle.schema.json")
        resolved.append(bundle)
    if unavailable:
        raise ValueError(
            "Historical re-Screening cannot use Review Bundles whose Result evidence is unavailable or disabled: "
            + "; ".join(sorted(unavailable)[:20])
        )
    return sorted(resolved, key=lambda item: (item["capability_id"], item["bundle_type"], item["bundle_id"]))


def _screening_bundles(root: Path, snapshot: dict[str, Any], round_id: str) -> list[dict[str, Any]]:
    """Resolve the bounded Bundle space owned by the active Round type."""
    record = snapshot.get("rounds", {}).get(round_id, {})
    if record.get("screening_scope") != "historical_closed_rounds":
        return _current_round_bundles(root, snapshot, round_id)
    bundles = _historical_review_bundles(root, snapshot, list(record.get("source_round_ids") or []))
    targets = set(record.get("target_bundle_ids") or [])
    selected = [bundle for bundle in bundles if bundle["bundle_id"] in targets]
    if {bundle["bundle_id"] for bundle in selected} != targets:
        raise ValueError("Authorized historical Review Bundle set is no longer available")
    return selected


def _sample_support(sample_count: int, minimum: int) -> str:
    if sample_count < minimum:
        return "insufficient"
    if sample_count < minimum * 2:
        return "limited"
    if sample_count < minimum * 4:
        return "moderate"
    return "strong"


def _cluster_overlap_status(root: Path, cluster_ids: list[str]) -> str:
    if len(cluster_ids) < 2:
        return "not_applicable"
    path = root / "runtime" / "cluster_membership.csv"
    if not path.is_file():
        return "unknown"
    selected = set(cluster_ids)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not selected.issubset(set(reader.fieldnames or [])):
            return "unknown"
        for row in reader:
            count = sum(str(row.get(cluster_id, "")).strip().lower() in {"1", "true", "yes"} for cluster_id in selected)
            if count > 1:
                return "overlapping"
    return "independent"


def _comparison_row(card: dict[str, Any], global_card: dict[str, Any] | None = None) -> dict[str, Any]:
    favorable = card.get("favorable_payload") or {}
    global_favorable = (global_card or {}).get("favorable_payload") or {}
    value = favorable.get("favorable_value")
    baseline = global_favorable.get("favorable_value")
    effect = float(value) - float(baseline) if isinstance(value, (int, float)) and isinstance(baseline, (int, float)) else None
    return {
        "result_ref": card["result_ref"],
        "scope_mode": card["analysis_subject"]["scope_mode"],
        "cluster_ids": list(card["analysis_subject"].get("cluster_ids") or []),
        "analyzed_count": int(card["analysis_subject"]["analyzed_count"]),
        "favorable_value": value,
        "favorable_effect_vs_global": effect,
        "metrics": {item["name"]: {"value": item.get("value"), "normalized_favorable_value": item.get("normalized_favorable_value"), "unit": item.get("unit")} for item in card.get("comparison_metrics") or []},
        "minimum_support_met": bool((card.get("quality") or {}).get("minimum_support_met")),
    }


def _make_review_bundle(
    root: Path,
    round_id: str,
    bundle_type: str,
    target_cards: list[dict[str, Any]],
    comparator_cards: list[dict[str, Any]],
    comparison_status: str,
) -> dict[str, Any]:
    all_cards = list({card["result_ref"]: card for card in [*target_cards, *comparator_cards]}.values())
    first = target_cards[0]
    capability_profile = catalog()[first["capability_id"]]["interpretation_profile"]
    cluster_ids = sorted({cluster_id for card in all_cards for cluster_id in card["analysis_subject"].get("cluster_ids") or []})
    global_card = next((card for card in comparator_cards if card["analysis_subject"]["scope_mode"] == "global"), None)
    min_count = min(int(card["analysis_subject"]["analyzed_count"]) for card in target_cards)
    minimum_key = "global" if bundle_type == "global" else "local"
    minimum = int(capability_profile["minimum_support"][minimum_key])
    refs = sorted(card["result_ref"] for card in all_cards)
    identity = {"type": bundle_type, "family": first["comparison_family_id"], "targets": sorted(card["result_ref"] for card in target_cards), "comparators": sorted(card["result_ref"] for card in comparator_cards)}
    bundle_id = "RVB" + value_hash(identity)[:16]
    comparison_table = [
        _comparison_row(card, global_card)
        for card in sorted(all_cards, key=lambda item: item["result_ref"])
    ]
    if bundle_type == "sibling_cluster":
        local_rows = [row for row in comparison_table if row["scope_mode"] != "global"]
        favorable_values = sorted(
            float(row["favorable_value"])
            for row in local_rows
            if isinstance(row.get("favorable_value"), (int, float))
            and not isinstance(row.get("favorable_value"), bool)
        )
        if favorable_values:
            midpoint = len(favorable_values) // 2
            sibling_median = (
                favorable_values[midpoint]
                if len(favorable_values) % 2
                else (favorable_values[midpoint - 1] + favorable_values[midpoint]) / 2.0
            )
            sibling_mean = sum(favorable_values) / len(favorable_values)
            sibling_variance = sum((value - sibling_mean) ** 2 for value in favorable_values) / len(favorable_values)
            ranked = sorted(set(favorable_values), reverse=True)
            for row in local_rows:
                value = row.get("favorable_value")
                row.update({
                    "sibling_count": len(local_rows),
                    "sibling_median_favorable_value": sibling_median,
                    "sibling_favorable_variance": sibling_variance,
                    "sibling_rank": ranked.index(float(value)) + 1 if isinstance(value, (int, float)) and not isinstance(value, bool) else None,
                    "sibling_deviation_from_median": float(value) - sibling_median if isinstance(value, (int, float)) and not isinstance(value, bool) else None,
                })
    has_favorable_value = any(
        isinstance(card.get("favorable_payload", {}).get("favorable_value"), (int, float))
        and not isinstance(card.get("favorable_payload", {}).get("favorable_value"), bool)
        for card in target_cards
    )
    comparable_value_counts: dict[str, int] = defaultdict(int)
    for row in comparison_table:
        for metric_name, metric in (row.get("metrics") or {}).items():
            value = metric.get("value")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                comparable_value_counts[str(metric_name)] += 1
    has_comparable_metric = any(count >= 2 for count in comparable_value_counts.values())
    applicable_axes = sorted(
        axis for axis in capability_profile["allowed_axes"]
        if not (
            (axis in {"context_deviation", "independent_support"} and bundle_type == "global")
            or (axis == "context_deviation" and comparison_status != "ready")
            or (axis == "context_deviation" and not has_comparable_metric)
            or (axis == "favorable_signal" and not has_favorable_value)
        )
    )
    bundle = {
        "schema_version": "1.0.0", "bundle_id": bundle_id, "bundle_type": bundle_type, "round_id": round_id,
        "capability_id": first["capability_id"], "interpretation_profile_id": first["interpretation_profile_id"], "comparison_family_id": first["comparison_family_id"],
        "target_result_refs": sorted(card["result_ref"] for card in target_cards), "comparator_result_refs": sorted(card["result_ref"] for card in comparator_cards), "all_result_refs": refs,
        "cluster_ids": cluster_ids, "comparison_status": comparison_status,
        "applicable_axes": applicable_axes,
        # Flatten the capability-specific anchors into the Bundle.  A short-lived
        # local Interpreter must not infer which separate Profile applies to a
        # row or fall back to the example draft as a scoring template.
        "evaluation_anchors": {
            axis: list(capability_profile.get("anchors", {}).get(axis) or [])
            for axis in applicable_axes
        },
        "comparison_table": comparison_table,
        "runtime_facts": {
            "sample_support": _sample_support(min_count, minimum),
            "comparator_validity": "matched" if global_card else "partial" if bundle_type == "sibling_cluster" else "none",
            "overlap_status": _cluster_overlap_status(root, cluster_ids) if bundle_type == "sibling_cluster" else "not_applicable",
            "minimum_support_met": min_count >= minimum,
        },
        "source_hash": "", "created_at": utc_now(),
    }
    # Assessment freshness depends on the complete deterministic comparison
    # payload, not only on the underlying Cards.  In particular, Cluster
    # overlap and support facts can change when membership records are repaired.
    bundle["source_hash"] = value_hash({key: value for key, value in bundle.items() if key not in {"source_hash", "created_at"}})
    validate(bundle, "review_bundle.schema.json")
    return bundle


def _current_round_bundles(root: Path, snapshot: dict[str, Any], round_id: str) -> list[dict[str, Any]]:
    current = _current_round_cards(root, snapshot, round_id)
    current_refs = {card["result_ref"] for card in current}
    usable = _usable_result_cards(root, snapshot)
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for card in usable:
        by_family[card["comparison_family_id"]].append(card)
    bundles: dict[str, dict[str, Any]] = {}
    for card in current:
        profile_value = catalog()[card["capability_id"]]["interpretation_profile"]
        scope = card["analysis_subject"]["scope_mode"]
        family_cards = by_family[card["comparison_family_id"]]
        globals_ = [item for item in family_cards if item["analysis_subject"]["scope_mode"] == "global"]
        if scope == "global":
            bundle = _make_review_bundle(root, round_id, "global", [card], [], "ready")
        else:
            comparator = sorted(globals_, key=lambda item: item["result_ref"])[-1:] if globals_ else []
            required = profile_value["global_comparator"] == "required_for_local"
            status = "ready" if comparator else "awaiting_comparator" if required else "not_applicable"
            bundle = _make_review_bundle(root, round_id, "global_local", [card], comparator, status)
        bundles[bundle["bundle_id"]] = bundle
    sibling_groups: dict[tuple[str, tuple[str, ...]], list[dict[str, Any]]] = defaultdict(list)
    for card in usable:
        subject = card["analysis_subject"]
        if subject["scope_mode"] != "global" and subject.get("clustering_nodes"):
            sibling_groups[(card["comparison_family_id"], tuple(sorted(subject["clustering_nodes"])))].append(card)
    for (family, _clustering), cards in sibling_groups.items():
        targets = [card for card in cards if card["result_ref"] in current_refs]
        if not targets or len(cards) < 2:
            continue
        profile_value = catalog()[targets[0]["capability_id"]]["interpretation_profile"]
        if profile_value["sibling_comparison"] == "not_applicable":
            continue
        # Keep each Interpreter context bounded.  The ordinary planning policy
        # creates only a few representative Clusters; this deterministic chunk
        # is a safety valve for human-requested broad surveys.
        target_refs = {item["result_ref"] for item in targets}
        ordered_targets = sorted(targets, key=lambda item: item["result_ref"])
        ordered_others = sorted((card for card in cards if card["result_ref"] not in target_refs), key=lambda item: item["result_ref"])
        global_comparators = sorted(
            (card for card in by_family[family] if card["analysis_subject"]["scope_mode"] == "global"),
            key=lambda item: item["result_ref"],
        )[-1:]
        for offset in range(0, len(ordered_targets), MAX_SIBLING_BUNDLE_CARDS):
            target_chunk = ordered_targets[offset:offset + MAX_SIBLING_BUNDLE_CARDS]
            room = max(0, MAX_SIBLING_BUNDLE_CARDS - len(target_chunk) - len(global_comparators))
            comparator_chunk = [*global_comparators, *ordered_others[:room]]
            if len(target_chunk) + len(comparator_chunk) < 2:
                continue
            bundle = _make_review_bundle(root, round_id, "sibling_cluster", target_chunk, comparator_chunk, "ready")
            bundles[bundle["bundle_id"]] = bundle
    return sorted(bundles.values(), key=lambda item: (item["capability_id"], item["bundle_type"], item["bundle_id"]))


def _pending_screening_bundles(root: Path, snapshot: dict[str, Any], round_id: str) -> list[dict[str, Any]]:
    latest = _latest_assessments(root)
    bundles = _screening_bundles(root, snapshot, round_id)
    rescreening = snapshot.get("rounds", {}).get(round_id, {}).get("result_rescreening") or {}
    forced_ids = set(rescreening.get("target_bundle_ids") or []) if rescreening.get("status") == "active" else set()
    return sorted(
        [
            bundle for bundle in bundles
            if bundle["comparison_status"] != "awaiting_comparator"
            and (
                bundle["bundle_id"] in forced_ids
                or not _assessment_is_current(bundle, latest.get(bundle["bundle_id"]))
            )
        ],
        key=lambda bundle: (bundle["capability_id"], bundle["bundle_type"], bundle["bundle_id"]),
    )


def _round_current_assessments(root: Path, snapshot: dict[str, Any], round_id: str) -> list[dict[str, Any]]:
    latest = _latest_assessments(root)
    rows: list[dict[str, Any]] = []
    for bundle in _screening_bundles(root, snapshot, round_id):
        row = latest.get(bundle["bundle_id"])
        if _assessment_is_current(bundle, row):
            rows.append(row)
    class_order = {"design_lead": 0, "contextual_anomaly": 1, "supporting_evidence": 2, "background": 3, "not_scorable": 4, "awaiting_comparator": 5}
    return sorted(rows, key=lambda row: (class_order.get(row["candidate_class"], 9), row["bundle_id"]))


def _write_round_assessment_csv(root: Path, snapshot: dict[str, Any], round_id: str) -> Path:
    path = root / "rounds" / round_id / "result_assessments.csv"
    headers = [
        "assessment_id", "bundle_id", "bundle_type", "round_id", "source_round_id", "capability_id", "target_result_refs",
        "assessment_status", "candidate_class", "sample_support", "comparator_validity", "effect_stability", "independence",
        "favorable_signal", "context_deviation", "chemical_actionability", "independent_support", "follow_up_leverage", "reason",
        "supporting_result_refs", "counter_result_refs", "rubric_version", "source_hash", "revision", "created_at",
    ]
    rows = []
    for row in _round_current_assessments(root, snapshot, round_id):
        scores = row.get("scores") or {}
        reliability = row.get("reliability") or {}
        rows.append({
            **{key: row.get(key) for key in headers},
            "target_result_refs": ";".join(row.get("target_result_refs") or []),
            "supporting_result_refs": ";".join(row.get("supporting_result_refs") or []),
            "counter_result_refs": ";".join(row.get("counter_result_refs") or []),
            **{key: scores.get(key) for key in ASSESSMENT_AXES},
            **{key: reliability.get(key) for key in ("sample_support", "comparator_validity", "effect_stability", "independence")},
        })
    write_csv(path, headers, rows)
    return path


def _screening_summary_fresh(root: Path, snapshot: dict[str, Any], round_id: str) -> tuple[bool, str | None]:
    record = snapshot.get("rounds", {}).get(round_id, {})
    relative = record.get("screening_summary_ref")
    if not relative:
        return False, None
    path = root / str(relative)
    if not path.is_file() or _pending_screening_bundles(root, snapshot, round_id):
        return False, None
    try:
        summary = read_json(path)
        validate(summary, "screening_summary.schema.json")
    except Exception:
        return False, None
    bundles = _screening_bundles(root, snapshot, round_id)
    return summary.get("bundle_count") == len(bundles) and summary.get("unassessed_count") == 0, str(relative)


def _handoff_marker(root: Path, control: dict[str, Any], snapshot: dict[str, Any]) -> str | None:
    round_id = control.get("active_round_id")
    if not round_id:
        return None
    if _round_report_mode(root, control, snapshot) == "screening":
        fresh, relative = _screening_summary_fresh(root, snapshot, round_id)
        return f"screening:{relative}" if fresh and relative else None
    fresh, node_id = _interpretation_fresh(snapshot, round_id)
    return f"interpretation:{node_id}" if fresh and node_id else None


def _assessment_review_manifest(
    round_id: str,
    bundles: list[dict[str, Any]],
    assessments: dict[str, dict[str, Any]],
    detailed_limit: int,
) -> dict[str, Any]:
    """Select reportable Bundle classes without collapsing scientific axes to a total score."""
    bundle_map = {bundle["bundle_id"]: bundle for bundle in bundles}
    rows = [row for bundle_id, row in assessments.items() if bundle_id in bundle_map]
    class_rank = {"design_lead": 0, "contextual_anomaly": 1, "supporting_evidence": 2, "background": 3, "not_scorable": 4, "awaiting_comparator": 5}
    support_rank = {"strong": 0, "moderate": 1, "limited": 2, "insufficient": 3}
    rows.sort(key=lambda row: (
        class_rank.get(row["candidate_class"], 9),
        support_rank.get((row.get("reliability") or {}).get("sample_support"), 9),
        -int(((row.get("scores") or {}).get("chemical_actionability")) if isinstance((row.get("scores") or {}).get("chemical_actionability"), int) else -1),
        row["capability_id"], row["bundle_id"],
    ))
    selected_bundles: list[str] = []
    selected_refs: list[str] = []
    for row in rows:
        if row["candidate_class"] not in {"design_lead", "contextual_anomaly"}:
            continue
        refs = bundle_map[row["bundle_id"]]["all_result_refs"]
        new_refs = [ref for ref in refs if ref not in selected_refs]
        if selected_bundles and len(selected_refs) + len(new_refs) > detailed_limit:
            continue
        selected_bundles.append(row["bundle_id"])
        selected_refs.extend(new_refs)
        if len(selected_refs) >= detailed_limit:
            break
    selected_set = set(selected_bundles)
    manifest = {
        "schema_version": "2.0.0",
        "round_id": round_id,
        "selected_bundle_ids": selected_bundles,
        "detailed_result_refs": selected_refs,
        "unselected_bundles": [{"bundle_id": bundle["bundle_id"], "candidate_class": (assessments.get(bundle["bundle_id"]) or {}).get("candidate_class", "awaiting_comparator"), "reason": "not_selected_by_report_gate"} for bundle in bundles if bundle["bundle_id"] not in selected_set],
        "candidate_class_counts": dict(Counter(row["candidate_class"] for row in rows)),
        "bundle_type_counts": dict(Counter(bundle["bundle_type"] for bundle in bundles)),
        "operator_counts": dict(Counter(bundle["capability_id"] for bundle in bundles)),
        "selection_method": "candidate_class_reliability_actionability_diversity",
        "created_at": utc_now(),
    }
    validate(manifest, "interpretation_review_manifest.schema.json")
    return manifest


def _candidate_class(profile_value: dict[str, Any], bundle: dict[str, Any], status: str, scores: dict[str, Any] | None) -> str:
    if bundle["comparison_status"] == "awaiting_comparator":
        return "awaiting_comparator"
    if status == "not_scorable" or scores is None:
        return "not_scorable"
    if not bundle["runtime_facts"]["minimum_support_met"]:
        return "background"
    def score(name: str) -> int:
        value = scores.get(name)
        return int(value) if isinstance(value, int) and not isinstance(value, bool) else 0
    standalone = profile_value["standalone_insight"]
    if standalone in {"allowed", "conditional"} and score("favorable_signal") >= 2 and score("chemical_actionability") >= 2:
        return "design_lead"
    comparison_is_valid = bundle["bundle_type"] not in {"global_local", "sibling_cluster"} or bundle["runtime_facts"]["comparator_validity"] in {"partial", "matched"}
    if standalone in {"allowed", "conditional"} and comparison_is_valid and score("context_deviation") >= 2 and score("follow_up_leverage") >= 1:
        return "contextual_anomaly"
    if standalone == "supporting_only" or score("independent_support") >= 1 or score("context_deviation") >= 1:
        return "supporting_evidence"
    return "background"


def _assessment_content_fingerprint(value: dict[str, Any]) -> str:
    """Fingerprint scientific assessment content while deliberately ignoring IDs."""
    reason = " ".join(str(value.get("reason") or "").split()).casefold()
    reliability = value.get("reliability") if isinstance(value.get("reliability"), dict) else {}
    return value_hash({
        "assessment_status": value.get("assessment_status"),
        "scores": value.get("scores"),
        # Draft rows keep these fields at the top level; committed rows place
        # them below reliability.  Normalize both layouts so the append-only
        # history participates in the same duplicate-content guard.
        "effect_stability": value.get("effect_stability", reliability.get("effect_stability")),
        "independence": value.get("independence", reliability.get("independence")),
        "reason": reason,
    })


def _reject_ungrounded_or_duplicated_assessments(
    rows: list[dict[str, Any]],
    latest: dict[str, dict[str, Any]],
) -> None:
    """Reject copy-filled drafts without trying to replace scientific judgment."""
    known: dict[str, set[str]] = defaultdict(set)
    known_reasons: dict[str, set[str]] = defaultdict(set)
    for bundle_id, row in latest.items():
        known[_assessment_content_fingerprint(row)].add(bundle_id)
        known_reasons[" ".join(str(row.get("reason") or "").split()).casefold()].add(bundle_id)
    current: dict[str, set[str]] = defaultdict(set)
    current_reasons: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        bundle_id = str(row.get("bundle_id") or "")
        evidence_refs = [*(row.get("supporting_result_refs") or []), *(row.get("counter_result_refs") or [])]
        if not evidence_refs:
            raise ValueError(f"Assessment must cite at least one Bundle Result as its evidence basis: {bundle_id}")
        fingerprint = _assessment_content_fingerprint(row)
        duplicated = (known.get(fingerprint, set()) | current.get(fingerprint, set())) - {bundle_id}
        if duplicated:
            raise ValueError(
                "Template-like duplicate assessment content is not allowed: "
                f"{bundle_id} duplicates {sorted(duplicated)[:5]}. "
                "Write a Bundle-specific reason grounded in its metric/value or quality facts."
            )
        reason_key = " ".join(str(row.get("reason") or "").split()).casefold()
        duplicated_reason = (known_reasons.get(reason_key, set()) | current_reasons.get(reason_key, set())) - {bundle_id}
        if duplicated_reason:
            raise ValueError(
                "Assessment reason must be Bundle-specific: "
                f"{bundle_id} repeats the reason used by {sorted(duplicated_reason)[:5]}."
            )
        current[fingerprint].add(bundle_id)
        current_reasons[reason_key].add(bundle_id)


def _persist_review_bundles(root: Path, bundles: list[dict[str, Any]]) -> None:
    path = _bundle_index_path(root)
    known = {(row["bundle_id"], row.get("source_hash")) for row in read_jsonl(path)}
    append_jsonl_rows_atomic(path, [bundle for bundle in bundles if (bundle["bundle_id"], bundle["source_hash"]) not in known])


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


def cmd_prepare_result_screening(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        _require_action(control, args.lease_token, {"PREPARE_RESULT_SCREENING"})
        round_id = control["active_round_id"]
        pending = _pending_screening_bundles(root, snapshot, round_id)
        if not pending:
            raise ValueError("No ready Review Bundle requires Screening")
        _persist_review_bundles(root, _screening_bundles(root, snapshot, round_id))
        settings = profile().get("runtime_planning") or {}
        rescreening = snapshot["rounds"][round_id].get("result_rescreening") or {}
        requested_batch_size = rescreening.get("batch_size") if rescreening.get("status") == "active" else None
        batch_size = min(
            DEFAULT_SCREENING_BATCH_SIZE,
            max(1, int(requested_batch_size or settings.get("screening_batch_size", DEFAULT_SCREENING_BATCH_SIZE))),
        )
        byte_limit = int(settings.get("max_screening_context_bytes", DEFAULT_SCREENING_CONTEXT_BYTES))
        targets = pending[:batch_size]
        usable_cards = {card["result_ref"]: card for card in _usable_result_cards(root, snapshot)}
        def make_context(selected: list[dict[str, Any]]) -> dict[str, Any]:
            refs = list(dict.fromkeys(ref for bundle in selected for ref in bundle["all_result_refs"]))
            selected_cards = [usable_cards[ref] for ref in refs if ref in usable_cards]
            selected_profiles = [catalog()[capability_id]["interpretation_profile"] for capability_id in sorted({bundle["capability_id"] for bundle in selected})]
            batch_id = "SCR" + value_hash({
                "round_id": round_id,
                "rubric_version": SCREENING_RUBRIC_VERSION,
                "rescreen_request_id": rescreening.get("request_id"),
                "targets": [(bundle["bundle_id"], bundle["source_hash"]) for bundle in selected],
            })[:16]
            return {
                "schema_version": "2.0.0",
                "mode": "screening",
                "run_id": control["run"]["run_id"],
                "round_id": round_id,
                "batch_id": batch_id,
                "rubric_version": SCREENING_RUBRIC_VERSION,
                "allowed_result_refs": refs,
                "target_bundle_ids": [bundle["bundle_id"] for bundle in selected],
                "review_bundles": selected,
                "result_cards": selected_cards,
                "interpretation_profiles": selected_profiles,
                "rubric": {
                    "score_meaning": "Absolute axis ratings; score only each Bundle's applicable_axes and never sum or rank them against other Bundles.",
                    "axes": {
                        "favorable_signal": "0-3 or not_applicable: evidence for movement in the Runtime-normalized favorable direction",
                        "context_deviation": "0-3 or not_applicable: Global-Local or sibling change that alters interpretation",
                        "chemical_actionability": "0-3 or not_applicable: connection to a manipulable feature, core, region, or transformation",
                        "independent_support": "0-3 or not_applicable: support from meaningfully independent evidence",
                        "follow_up_leverage": "0-3 or not_applicable: ability of a small follow-up to change a decision",
                    },
                    "reliability": "Runtime owns sample_support and comparator_validity. Assess only effect_stability and independence.",
                    "candidate_class": "Runtime derives the fixed candidate class; the Interpreter must not invent one.",
                    "not_scorable": "Use only when the bounded Bundle cannot support a defensible axis assessment.",
                },
                "created_at": utc_now(),
            }

        context = make_context(targets)
        while len(targets) > 1 and len(canonical_bytes(context)) > byte_limit:
            targets.pop()
            context = make_context(targets)
        if len(canonical_bytes(context)) > byte_limit:
            raise ValueError("A single Review Bundle exceeds the bounded Screening context limit")
        validate(context, "screening_batch.schema.json")
        batch_id = context["batch_id"]
        scratch = root / "runtime" / "scratch" / round_id / "screening" / batch_id
        scratch.mkdir(parents=True, exist_ok=True)
        context_path = scratch / "context.json"
        draft_path = scratch / "draft.json"
        write_json(context_path, context)
        write_json(draft_path, {"schema_version": "2.0.0", "batch_id": batch_id, "assessments": []})
        snapshot["rounds"][round_id]["current_screening_batch"] = {
            "batch_id": batch_id,
            "context_path": str(context_path),
            "draft_path": str(draft_path),
            "target_bundle_ids": context["target_bundle_ids"],
            "attempts": 0,
            "prepared_at": utc_now(),
        }
        _commit(root, control, snapshot, "result_screening_prepared", {
            "batch_id": batch_id,
            "target_bundle_ids": context["target_bundle_ids"],
            "context_path": str(context_path.relative_to(root)),
            "draft_path": str(draft_path.relative_to(root)),
        }, round_id=round_id)
        _write_working_set(root, control, snapshot)
    _print_compact(
        control,
        batch_id=batch_id,
        target_count=len(targets),
        context_path=str(context_path),
        draft_path=str(draft_path),
        interpreter_agent="cs-conductor-interpreter",
        interpreter_mode="screening",
    )
    return 0


def cmd_commit_result_screening(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        _require_action(control, args.lease_token, {"WRITE_RESULT_SCREENING"})
        round_id = control["active_round_id"]
        record = snapshot["rounds"][round_id]
        batch = record.get("current_screening_batch") or {}
        if batch.get("batch_id") != args.batch_id:
            raise ValueError("Screening batch is not current")
        draft_path = Path(args.draft).resolve() if args.draft else Path(batch["draft_path"]).resolve()
        if draft_path != Path(batch["draft_path"]).resolve():
            raise ValueError("Draft path does not match the Runtime-prepared Screening workspace")
        try:
            context = read_json(Path(batch["context_path"]))
            draft = read_json(draft_path)
            validate(draft, "screening_draft.schema.json")
            if draft["batch_id"] != batch["batch_id"]:
                raise ValueError("Screening draft batch_id mismatch")
            targets = list(context["target_bundle_ids"])
            by_id = {row["bundle_id"]: row for row in draft["assessments"]}
            if len(by_id) != len(draft["assessments"]) or set(by_id) != set(targets):
                raise ValueError("Screening draft must assess every target Review Bundle exactly once")
            allowed = set(context["allowed_result_refs"])
            bundles = {bundle["bundle_id"]: bundle for bundle in context["review_bundles"]}
            cards = {card["result_ref"]: card for card in context["result_cards"]}
            latest = _latest_assessments(root)
            _reject_ungrounded_or_duplicated_assessments(list(draft["assessments"]), latest)
            existing_ids = {row["assessment_id"] for row in read_jsonl(_assessment_index_path(root))}
            committed: list[dict[str, Any]] = []
            for bundle_id in targets:
                value = by_id[bundle_id]
                bundle = bundles[bundle_id]
                supporting = list(dict.fromkeys(value.get("supporting_result_refs") or []))
                counter = list(dict.fromkeys(value.get("counter_result_refs") or []))
                if set([*supporting, *counter]) - allowed:
                    raise ValueError(f"Assessment references Results outside context: {bundle_id}")
                if set([*supporting, *counter]) - set(bundle["all_result_refs"]):
                    raise ValueError(f"Assessment references Results outside its Review Bundle: {bundle_id}")
                status = value["assessment_status"]
                scores = value.get("scores")
                stability = value.get("effect_stability")
                independence = value.get("independence")
                profile_value = catalog()[bundle["capability_id"]]["interpretation_profile"]
                if status == "evaluated":
                    if not isinstance(scores, dict) or stability not in {"unknown", "unstable", "mixed", "stable"} or independence not in {"unknown", "overlapping", "partially_independent", "independent"}:
                        raise ValueError(f"Evaluated assessment requires scores and reliability judgments: {bundle_id}")
                    allowed_axes = set(bundle["applicable_axes"])
                    for axis in ASSESSMENT_AXES:
                        axis_value = scores[axis]
                        if axis in allowed_axes and not isinstance(axis_value, int):
                            raise ValueError(f"Allowed axis must be scored 0-3: {bundle_id}/{axis}")
                        if axis not in allowed_axes and axis_value != "not_applicable":
                            raise ValueError(f"Disallowed axis must be not_applicable: {bundle_id}/{axis}")
                else:
                    if scores is not None or stability is not None or independence is not None:
                        raise ValueError(f"not_scorable assessment must use null scores and reliability judgments: {bundle_id}")
                source_hash = bundle["source_hash"]
                previous = latest.get(bundle_id)
                revision = int(previous.get("revision", 0)) + 1 if previous else 1
                assessment_id = "ASR" + value_hash([bundle_id, source_hash, SCREENING_RUBRIC_VERSION, revision])[:16]
                quality_flags = sorted({flag for ref in bundle["all_result_refs"] for flag in (cards.get(ref, {}).get("quality_flags") or [])})
                candidate_class = _candidate_class(profile_value, bundle, status, scores)
                row = {
                    "schema_version": "2.0.0", "assessment_id": assessment_id, "bundle_id": bundle_id, "bundle_type": bundle["bundle_type"],
                    "round_id": round_id, "source_round_id": bundle.get("round_id", round_id), "capability_id": bundle["capability_id"], "target_result_refs": bundle["target_result_refs"],
                    "assessment_status": status, "candidate_class": candidate_class, "scores": scores,
                    "reliability": {"sample_support": bundle["runtime_facts"]["sample_support"], "comparator_validity": bundle["runtime_facts"]["comparator_validity"], "effect_stability": stability or "unknown", "independence": independence or "unknown", "quality_flags": quality_flags},
                    "reason": str(value["reason"]).strip(), "supporting_result_refs": supporting, "counter_result_refs": counter,
                    "rubric_version": SCREENING_RUBRIC_VERSION, "source_hash": source_hash, "revision": revision, "created_at": utc_now(),
                }
                validate(row, "result_assessment.schema.json")
                committed.append(row)
            additions = [row for row in committed if row["assessment_id"] not in existing_ids]
            append_jsonl_rows_atomic(_assessment_index_path(root), additions)
        except Exception as exc:
            batch["attempts"] = int(batch.get("attempts", 0)) + 1
            failure_path = Path(batch["draft_path"]).with_name(f"screening_failure_{batch['attempts']:02d}.json")
            write_json(failure_path, {"schema_version": "1.0.0", "batch_id": batch.get("batch_id"), "error": str(exc)[:4000], "created_at": utc_now()})
            exhausted = batch["attempts"] >= MAX_INTERPRETER_ATTEMPTS
            if exhausted:
                control["blocker"] = {"code": "RESULT_SCREENING_RETRY_EXHAUSTED", "batch_id": batch.get("batch_id"), "failure_pointer": str(failure_path.relative_to(root))}
            _commit(root, control, snapshot, "result_screening_rejected", {
                "batch_id": batch.get("batch_id"), "attempts": batch["attempts"],
                "failure_pointer": str(failure_path.relative_to(root)), "retry_exhausted": exhausted,
            }, round_id=round_id)
            _write_working_set(root, control, snapshot)
            _print_compact(control, batch_id=batch.get("batch_id"), screening_status="fail", retry_exhausted=exhausted, failure_pointer=str(failure_path.relative_to(root)))
            return 1
        record["current_screening_batch"] = None
        record["screening_summary_ref"] = None
        rescreening = record.get("result_rescreening") or {}
        if rescreening.get("status") == "active":
            committed_ids = {row["bundle_id"] for row in committed}
            rescreening["target_bundle_ids"] = [
                bundle_id for bundle_id in rescreening.get("target_bundle_ids") or []
                if bundle_id not in committed_ids
            ]
            if not rescreening["target_bundle_ids"]:
                rescreening.update({"status": "completed", "completed_at": utc_now()})
        if (control.get("blocker") or {}).get("code") == "RESULT_SCREENING_RETRY_EXHAUSTED":
            control["blocker"] = None
        csv_path = _write_round_assessment_csv(root, snapshot, round_id)
        _commit(root, control, snapshot, "result_screening_committed", {
            "batch_id": batch["batch_id"],
            "assessment_ids": [row["assessment_id"] for row in committed],
            "source_round_ids": sorted({row.get("source_round_id", row["round_id"]) for row in committed}),
            "assessment_csv": str(csv_path.relative_to(root)),
        }, round_id=round_id)
        _write_working_set(root, control, snapshot)
        remaining = len(_pending_screening_bundles(root, snapshot, round_id))
    _print_compact(control, batch_id=batch["batch_id"], screening_status="pass", assessed_count=len(committed), unassessed_count=remaining)
    return 0


def cmd_request_result_rescreening(args: argparse.Namespace) -> int:
    """Human-authorized append-only reassessment of current-Round Review Bundles."""
    root = resolve_root(args.run_root)
    _require_control_authority(root, args.control_key)
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        if control.get("round_state") not in {"ACTIVE", "AWAITING_HUMAN_REVIEW"}:
            raise ValueError("Result re-Screening requires an ACTIVE or AWAITING_HUMAN_REVIEW Round")
        round_id = control.get("active_round_id")
        if not round_id:
            raise ValueError("No active Round is available for Result re-Screening")
        record = snapshot["rounds"][round_id]
        if record.get("current_screening_batch"):
            raise ValueError("Finish or repair the current Screening batch before requesting re-Screening")
        running = [node["node_id"] for node in snapshot["nodes"] if node.get("status") == "running"]
        if running:
            raise ValueError(f"Result re-Screening requires no running Nodes: {running[:20]}")
        if (record.get("result_rescreening") or {}).get("status") == "active":
            raise ValueError("A Result re-Screening request is already active")
        bundles = [
            bundle for bundle in _current_round_bundles(root, snapshot, round_id)
            if bundle.get("comparison_status") != "awaiting_comparator"
        ]
        by_id = {bundle["bundle_id"]: bundle for bundle in bundles}
        requested_ids = sorted(set(args.bundle_id or []))
        if args.all_current:
            requested_ids = sorted(by_id)
        unknown = sorted(set(requested_ids) - set(by_id))
        if unknown:
            raise ValueError(f"Review Bundles are not eligible in {round_id}: {unknown[:20]}")
        if not requested_ids:
            raise ValueError("No eligible Review Bundle was selected for re-Screening")
        if not 1 <= args.batch_size <= DEFAULT_SCREENING_BATCH_SIZE:
            raise ValueError(f"batch-size must be between 1 and {DEFAULT_SCREENING_BATCH_SIZE}")
        serial = int(record.get("result_rescreening_serial", 0)) + 1
        request_id = f"RSCR{serial:04d}"
        record["result_rescreening_serial"] = serial
        record["result_rescreening"] = {
            "request_id": request_id,
            "status": "active",
            "reason": args.reason,
            "batch_size": args.batch_size,
            "target_bundle_ids": requested_ids,
            "initial_target_count": len(requested_ids),
            "requested_at": utc_now(),
            "completed_at": None,
        }
        # Re-Screening is a bounded human-requested maintenance pass.  Keep the
        # normal Screening gate, then deterministically return to finalization
        # instead of letting the scientific planner add unrelated work.
        record.update({"screening_summary_ref": None, "latest_audit": None, "human_checkpoint_requested": True})
        if _round_report_mode(root, control, snapshot) == "full":
            record.update({
                "interpretation_revision_required": True,
                "interpretation_revision_serial": int(record.get("interpretation_revision_serial", 0)) + 1,
                "report_revision_reason": f"Result re-Screening {request_id}: {args.reason}",
            })
        if control["round_state"] == "AWAITING_HUMAN_REVIEW":
            if args.additional_walltime_minutes is None or args.additional_walltime_minutes < 1:
                raise ValueError("Reopening an AWAITING_HUMAN_REVIEW Round requires --additional-walltime-minutes")
            now = datetime.now(timezone.utc)
            minutes = args.additional_walltime_minutes
            reserve = min(90, max(5, minutes // 5), max(1, minutes - 1))
            record.update({
                "state": "ACTIVE",
                "deadline_at": (now + timedelta(minutes=minutes)).isoformat(),
                "soft_stop_at": (now + timedelta(minutes=minutes - reserve)).isoformat(),
                "scientific_finish_requested": False,
                "finish_reason": None,
            })
        control.update({"round_state": "ACTIVE", "blocker": None})
        control["closure"] = {"contract_satisfied": False, "interpretation_ready": False, "audit_ready": False, "outcome": "undetermined"}
        _commit(root, control, snapshot, "result_rescreening_requested", {
            "request_id": request_id,
            "target_count": len(requested_ids),
            "batch_size": args.batch_size,
            "reason": args.reason,
        }, round_id=round_id)
        _write_working_set(root, control, snapshot)
    _print_compact(control, result_rescreening_requested=True, request_id=request_id, target_count=len(requested_ids), batch_size=args.batch_size)
    return 0


def cmd_reset_result_screening(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    _require_control_authority(root, args.control_key)
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        if (control.get("blocker") or {}).get("code") != "RESULT_SCREENING_RETRY_EXHAUSTED":
            raise ValueError("Result Screening is not blocked")
        round_id = control["active_round_id"]
        batch = snapshot["rounds"][round_id].get("current_screening_batch") or {}
        batch["attempts"] = 0
        control["blocker"] = None
        _commit(root, control, snapshot, "result_screening_retry_authorized", {"batch_id": batch.get("batch_id"), "reason": args.reason}, round_id=round_id)
        _write_working_set(root, control, snapshot)
    _print_compact(control, batch_id=batch.get("batch_id"), screening_retry_authorized=True)
    return 0


def cmd_write_screening_summary(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        _require_action(control, args.lease_token, {"WRITE_SCREENING_SUMMARY"})
        round_id = control["active_round_id"]
        pending = _pending_screening_bundles(root, snapshot, round_id)
        if pending:
            raise ValueError("Screening Summary cannot be written while ready Review Bundles remain unassessed")
        bundles = _screening_bundles(root, snapshot, round_id)
        _persist_review_bundles(root, bundles)
        assessments = _round_current_assessments(root, snapshot, round_id)
        csv_path = _write_round_assessment_csv(root, snapshot, round_id)
        awaiting = [bundle for bundle in bundles if bundle["comparison_status"] == "awaiting_comparator"]
        candidate_counts = Counter(row["candidate_class"] for row in assessments)
        candidate_counts["awaiting_comparator"] += len(awaiting)
        operator_counts = Counter(bundle["capability_id"] for bundle in bundles)
        bundle_type_counts = Counter(bundle["bundle_type"] for bundle in bundles)
        reportable = [{key: row.get(key) for key in ("assessment_id", "bundle_id", "bundle_type", "capability_id", "target_result_refs", "candidate_class", "scores", "reliability", "reason")} for row in assessments if row["candidate_class"] in {"design_lead", "contextual_anomaly"}][:20]
        relative = Path("rounds") / round_id / "screening_summary.json"
        summary = {
            "schema_version": "2.0.0",
            "run_id": control["run"]["run_id"],
            "round_id": round_id,
            "report_mode": _round_report_mode(root, control, snapshot),
            "screening_scope": snapshot["rounds"][round_id].get("screening_scope", "current_round"),
            "source_round_ids": list(snapshot["rounds"][round_id].get("source_round_ids") or [round_id]),
            "bundle_count": len(bundles),
            "evaluated_count": sum(row["assessment_status"] == "evaluated" for row in assessments),
            "not_scorable_count": sum(row["assessment_status"] == "not_scorable" for row in assessments),
            "awaiting_comparator_count": len(awaiting),
            "unassessed_count": 0,
            "candidate_class_counts": dict(sorted(candidate_counts.items())),
            "operator_counts": dict(sorted(operator_counts.items())),
            "bundle_type_counts": dict(sorted(bundle_type_counts.items())),
            "reportable_candidates": reportable,
            "assessment_index_ref": str(_assessment_index_path(root).relative_to(root)).replace("\\", "/"),
            "assessment_csv_ref": str(csv_path.relative_to(root)).replace("\\", "/"),
            "bundle_index_ref": str(_bundle_index_path(root).relative_to(root)).replace("\\", "/"),
            "stop_reason": str(snapshot["rounds"][round_id].get("finalizing_reason") or "contract_satisfied"),
            "created_at": utc_now(),
        }
        validate(summary, "screening_summary.schema.json")
        write_json(root / relative, summary)
        snapshot["rounds"][round_id].update({"screening_summary_ref": relative.as_posix(), "screening_completed_at": utc_now(), "latest_audit": None})
        _commit(root, control, snapshot, "screening_summary_written", {"path": relative.as_posix(), "screening_scope": summary["screening_scope"], "source_round_ids": summary["source_round_ids"], "bundle_count": len(bundles), "evaluated_count": summary["evaluated_count"]}, round_id=round_id)
        _write_working_set(root, control, snapshot)
    _print_compact(control, screening_summary=str(root / relative), evaluated_count=summary["evaluated_count"], awaiting_comparator_count=summary["awaiting_comparator_count"], reportable_count=len(summary["reportable_candidates"]))
    return 0


def _cumulative_interpretation_evidence(
    root: Path,
    snapshot: dict[str, Any],
    source_round_ids: list[str],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    """Resolve current, unreported assessment evidence without reopening source Rounds."""
    source_set = set(source_round_ids)
    latest_assessments = _latest_assessments(root)
    bundle_versions = {
        (row.get("bundle_id"), row.get("source_hash")): row
        for row in read_jsonl(_bundle_index_path(root))
    }
    insight_rows = read_jsonl(root / "runtime" / "insight_index.jsonl")
    reported_bundle_ids = {
        bundle_id
        for row in insight_rows
        for bundle_id in (row.get("review_bundle_ids") or [])
    }
    latest_insights: dict[str, dict[str, Any]] = {}
    for row in insight_rows:
        previous = latest_insights.get(str(row.get("insight_id")))
        if previous is None or int(row.get("revision", 0)) >= int(previous.get("revision", 0)):
            latest_insights[str(row.get("insight_id"))] = row
    prior_summaries = [
        {
            "insight_id": row.get("insight_id"),
            "title": row.get("title"),
            "review_bundle_ids": row.get("review_bundle_ids") or [],
        }
        for row in sorted(latest_insights.values(), key=lambda item: str(item.get("insight_id")))
    ]
    usable_refs = {card["result_ref"] for card in _usable_result_cards(root, snapshot)}
    selected_bundles: list[dict[str, Any]] = []
    selected_assessments: dict[str, dict[str, Any]] = {}
    excluded_reported: list[str] = []
    source_assessment_count = 0
    unavailable_count = 0
    for bundle_id, assessment in sorted(latest_assessments.items()):
        if assessment.get("source_round_id", assessment.get("round_id")) not in source_set:
            continue
        bundle = bundle_versions.get((bundle_id, assessment.get("source_hash")))
        if not bundle or not _assessment_is_current(bundle, assessment):
            unavailable_count += 1
            continue
        source_assessment_count += 1
        if bundle_id in reported_bundle_ids:
            excluded_reported.append(bundle_id)
            continue
        if set(bundle.get("all_result_refs") or []) - usable_refs:
            unavailable_count += 1
            continue
        selected_bundles.append(bundle)
        selected_assessments[bundle_id] = assessment
    metadata = {
        "interpretation_scope": "cumulative_unreported",
        "source_round_ids": sorted(source_set),
        "source_assessment_count": source_assessment_count,
        "previously_reported_count": len(excluded_reported),
        "excluded_previously_reported_bundle_ids": sorted(excluded_reported),
        "unavailable_or_stale_count": unavailable_count,
    }
    return selected_bundles, selected_assessments, metadata, prior_summaries


def cmd_prepare_interpretation(args: argparse.Namespace) -> int:
    root = resolve_root(args.run_root)
    with writer_lock(root):
        _recover_transaction(root)
        control, snapshot = _read_state(root)
        _require_action(control, args.lease_token, {"PLAN_INTERPRETATION"})
        round_id = control["active_round_id"]
        record = snapshot["rounds"][round_id]
        interpretation_scope = record.get("interpretation_scope", "current_round")
        rereview = set(args.rereview_result_ref or [])
        all_cards = {card["result_ref"]: card for card in _usable_result_cards(root, snapshot)}
        prior_reported_insights: list[dict[str, Any]] = []
        manifest_metadata: dict[str, Any] = {
            "interpretation_scope": "current_round",
            "source_round_ids": [round_id],
            "source_assessment_count": 0,
            "previously_reported_count": 0,
            "excluded_previously_reported_bundle_ids": [],
        }
        if interpretation_scope == "cumulative_unreported":
            if rereview:
                raise ValueError("Cumulative Interpretation does not combine with --rereview-result-ref")
            source_round_ids = list(record.get("source_round_ids") or [])
            bundles, latest_assessments, manifest_metadata, prior_reported_insights = _cumulative_interpretation_evidence(
                root, snapshot, source_round_ids
            )
        else:
            bundles = _current_round_bundles(root, snapshot, round_id)
            latest_assessments = _latest_assessments(root)
            manifest_metadata["source_assessment_count"] = len(
                [bundle for bundle in bundles if bundle["bundle_id"] in latest_assessments]
            )
        if rereview:
            historical = {row["bundle_id"]: row for row in read_jsonl(_bundle_index_path(root))}
            for bundle in historical.values():
                if set(bundle.get("all_result_refs") or []) & rereview and bundle not in bundles:
                    bundles.append(bundle)
        configured_limit = int((profile().get("runtime_planning") or {}).get("max_interpretation_result_cards", 50))
        detailed_limit = min(args.detailed_limit, configured_limit)
        review = _assessment_review_manifest(round_id, bundles, latest_assessments, detailed_limit)
        review.update(manifest_metadata)
        validate(review, "interpretation_review_manifest.schema.json")
        selected_refs = set(review["detailed_result_refs"])
        selected_cards = [card for ref, card in all_cards.items() if ref in selected_refs]
        selected_cards.sort(key=lambda card: review["detailed_result_refs"].index(card["result_ref"]))
        selected_bundle_ids = set(review["selected_bundle_ids"])
        selected_bundles = [bundle for bundle in bundles if bundle["bundle_id"] in selected_bundle_ids]
        selected_bundles.sort(key=lambda bundle: review["selected_bundle_ids"].index(bundle["bundle_id"]))
        analysis_nodes = sorted({card["node_id"] for card in selected_cards})
        previous = record.get("current_interpretation_node")
        effective_focus = args.focus or record.get("report_revision_reason")
        if interpretation_scope == "cumulative_unreported" and not effective_focus:
            effective_focus = "過去Roundの最新一次評価から、既報Insightに使用済みのBundleを除外し、新規の活性改善候補または注目すべき違和感を抽出する。"
        revision_serial = int(record.get("interpretation_revision_serial", 0))
        node, _created = _add_node(snapshot, control, "I001", analysis_nodes, "round_commit", {"mode": "multi_scope"}, {"reviewed_bundle_ids": review["selected_bundle_ids"], "reviewed_result_refs": review["detailed_result_refs"], "focus": effective_focus, "revision_serial": revision_serial, "interpretation_scope": interpretation_scope, "source_round_ids": review.get("source_round_ids") or [round_id]}, supersedes=previous)
        scratch = root / "runtime" / "scratch" / round_id / node["node_id"] / "interpretation"
        scratch.mkdir(parents=True, exist_ok=True)
        selected_assessments = {bundle_id: latest_assessments[bundle_id] for bundle_id in review["selected_bundle_ids"] if bundle_id in latest_assessments}
        context = {"schema_version": "2.0.0", "mode": "synthesis", "interpretation_scope": interpretation_scope, "run": control["run"], "round_id": round_id, "node_id": node["node_id"], "focus": effective_focus, "interpretation_policy": str((module_root() / "docs" / "CONDUCTOR_interpretation_policy.md").resolve()), "allowed_result_refs": review["detailed_result_refs"], "result_cards": selected_cards, "review_bundles": selected_bundles, "result_assessments": selected_assessments, "review_manifest": review, "prior_reported_insights": prior_reported_insights, "comparison_batches": [review["selected_bundle_ids"][index:index + 10] for index in range(0, len(review["selected_bundle_ids"]), 10)], "role_contract": {"read_only_evidence_space": True, "scientific_computation_allowed": False, "node_creation_allowed": False, "followups_are_recommendations_only": True, "absolute_axes_not_total_score": True, "reportable_classes": ["design_lead", "contextual_anomaly"], "exclude_previously_reported_bundles": interpretation_scope == "cumulative_unreported"}, "draft_contract": {"scope_is_runtime_derived": True, "formal_ids_are_runtime_assigned": True, "candidate_class_is_runtime_verified": True, "comparison_claim_requires_comparison_results": True, "japanese_human_report": True}, "created_at": utc_now()}
        title = "CONDUCTOR累積解析結果の解釈" if interpretation_scope == "cumulative_unreported" else "CONDUCTOR解析結果の解釈"
        draft = {"title": title, "executive_summary": "", "coverage_summary": "", "insights": []}
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


def _normalise_insight_limitations(value: Any) -> list[str]:
    """Return complete limitation statements, never an iterable of characters."""
    if isinstance(value, str):
        candidates: list[Any] = value.splitlines() or [value]
    elif isinstance(value, (list, tuple)):
        candidates = list(value)
        nonblank = [str(item).strip() for item in candidates if str(item).strip()]
        # A former failure mode converted one string with ``list`` semantics.
        if len(nonblank) >= 2 and all(len(item) == 1 for item in nonblank):
            candidates = ["".join(str(item) for item in candidates)]
    elif value is None:
        candidates = []
    else:
        candidates = [value]

    result: list[str] = []
    for candidate in candidates:
        text = str(candidate).strip()
        text = text.lstrip("-*・• \t").strip()
        if text and text not in result:
            result.append(text)
    return result or ["利用可能なOperator Resultと今回確認した解析範囲に依存する。"]


def _fallback_insight_title(subject: dict[str, Any], fact_panel: dict[str, Any]) -> str:
    mode = subject.get("scope_mode")
    clusters = subject.get("cluster_ids") or []
    if mode == "global":
        scope = "Global"
    elif clusters:
        scope = "Cluster " + "・".join(str(value) for value in clusters[:3])
    else:
        scope = "複数scope"
    operators = "・".join(str(value) for value in fact_panel.get("operators") or []) or "Operator"
    return f"{scope}における{operators}解析のInsight"


def _formalize_insights(root: Path, snapshot: dict[str, Any], draft: dict[str, Any], cards: dict[str, dict[str, Any]], bundles: dict[str, dict[str, Any]], assessments: dict[str, dict[str, Any]], round_id: str, interpretation_node: str) -> list[dict[str, Any]]:
    existing_rows = read_jsonl(root / "runtime" / "insight_index.jsonl")
    latest = {row["insight_id"]: row for row in existing_rows}
    formal: list[dict[str, Any]] = []
    for value in draft.get("insights") or []:
        bundle_ids = list(dict.fromkeys(value.get("review_bundle_ids") or []))
        if not bundle_ids or set(bundle_ids) - set(bundles):
            raise ValueError("Every Insight requires valid review_bundle_ids")
        classes = {(assessments.get(bundle_id) or {}).get("candidate_class") for bundle_id in bundle_ids}
        if not classes or classes - {"design_lead", "contextual_anomaly"}:
            raise ValueError("Insight may use only reportable Review Bundle classes")
        candidate_class = "design_lead" if "design_lead" in classes else "contextual_anomaly"
        supporting = list(dict.fromkeys(value.get("supporting_results") or []))
        comparisons = list(dict.fromkeys(value.get("comparison_results") or []))
        counter = list(dict.fromkeys(value.get("counter_results") or []))
        refs = list(dict.fromkeys([*supporting, *comparisons, *counter]))
        if not supporting:
            raise ValueError("Every Insight requires supporting_results")
        if set(refs) - set(cards):
            raise ValueError(f"Insight references Results outside the Interpretation context: {sorted(set(refs)-set(cards))}")
        bundle_refs = {ref for bundle_id in bundle_ids for ref in bundles[bundle_id]["all_result_refs"]}
        if set(refs) - bundle_refs:
            raise ValueError("Insight Result references must belong to its Review Bundles")
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
        fact_panel = {"operators": sorted({card["capability_id"] for card in selected_cards}), "metrics": sorted({str(card.get("metric")) for card in selected_cards if card.get("metric")}), "analysis_descriptions": description_caps, "cluster_source_descriptions": source_caps, "clustering_method": ", ".join(clustering_caps) if clustering_caps else None, "result_samples": {card["result_ref"]: card["analysis_subject"]["analyzed_count"] for card in selected_cards}, "comparison_families": sorted({card["comparison_family_id"] for card in selected_cards}), "interpretation_profiles": sorted({card["interpretation_profile_id"] for card in selected_cards})}
        title = str(value.get("title") or "").strip() or _fallback_insight_title(subject, fact_panel)
        formal.append({"insight_id": insight_id, "revision": revision, "attention": attention, "candidate_class": candidate_class, "claim_kind": value.get("claim_kind", "single_scope_observation"), "title": title, "analysis_subject": subject, "review_bundle_ids": bundle_ids, "supporting_results": supporting, "comparison_results": comparisons, "counter_results": counter, "observation": str(value.get("observation") or "").strip(), "interpretation": str(value.get("interpretation") or "").strip(), "limitations": _normalise_insight_limitations(value.get("limitations")), "recommended_followups": [{"title": str(item.get("title") or "追加確認").strip(), "rationale": str(item.get("rationale") or "").strip()} for item in value.get("recommended_followups") or []], "fact_panel": fact_panel})
    return formal


def _anticipated_outcome(root: Path, control: dict[str, Any], snapshot: dict[str, Any]) -> str:
    deliverables = _deliverable_status(root, control, snapshot)
    technical_failures = any(node["status"] == "failed" and (node.get("created_in_round") == control["active_round_id"] or node.get("assigned_round") == control["active_round_id"]) for node in snapshot["nodes"])
    unmet = [item for item in deliverables if item["type"] not in {"interpretation_completed", "screening_completed"} and not item["satisfied"] and not item.get("human_acceptance_required")]
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
            bundles = {bundle["bundle_id"]: bundle for bundle in context.get("review_bundles") or []}
            assessments = dict(context.get("result_assessments") or {})
            insights = _formalize_insights(root, candidate_snapshot, draft, cards, bundles, assessments, control["active_round_id"], node["node_id"])
            outcome = _anticipated_outcome(root, control, snapshot)
            report = {"schema_version": "4.0.0", "run_id": control["run"]["run_id"], "round_id": control["active_round_id"], "node_id": node["node_id"], "supersedes": node.get("supersedes"), "title": str(draft.get("title") or "CONDUCTOR解析結果の解釈"), "report_header": {"project": control["run"]["project"], "endpoint": control["run"]["endpoint"], "higher_is_better": control["run"]["higher_is_better"], "endpoint_unit": control["run"].get("endpoint_unit"), "endpoint_transform": control["run"].get("endpoint_transform"), "completion": outcome}, "executive_summary": str(draft.get("executive_summary") or ("今回の範囲では、防御可能なdesign leadまたはcontextual anomalyは得られませんでした。" if not insights else "活性改善に接続し得る主要候補を示します。")), "coverage_summary": str(draft.get("coverage_summary") or f"Runtimeが選択したReview Bundle {len(bundles)}件を確認しました。未選択Bundleとcomparator不足はreview manifestに記録しています。"), "insights": insights, "result_catalog": list(cards.values()), "review_manifest": context["review_manifest"], "created_at": utc_now()}
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
        atomic_replace(temporary, final)
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
    bundle_rows = read_jsonl(_bundle_index_path(root))
    bundle_versions: dict[tuple[str, str], dict[str, Any]] = {}
    invalid_bundles = []
    for row in bundle_rows:
        try:
            validate(row, "review_bundle.schema.json")
            if set(row.get("all_result_refs") or []) - set(result_refs):
                raise ValueError("Review Bundle references a Result absent from Result Index")
            bundle_versions[(row["bundle_id"], row["source_hash"])] = row
        except Exception as exc:
            invalid_bundles.append({"bundle_id": row.get("bundle_id"), "error": str(exc)})
    check("REVIEW_BUNDLE_INDEX", not invalid_bundles, invalid_bundles)
    assessment_rows = read_jsonl(_assessment_index_path(root))
    assessment_ids = [row.get("assessment_id") for row in assessment_rows]
    invalid_assessments = []
    for row in assessment_rows:
        try:
            validate(row, "result_assessment.schema.json")
            if (row.get("bundle_id"), row.get("source_hash")) not in bundle_versions:
                raise ValueError("assessment source Review Bundle is absent from Bundle Index")
            if row.get("round_id") not in snapshot.get("rounds", {}):
                raise ValueError("assessment execution Round is absent from State")
            if row.get("source_round_id", row.get("round_id")) not in snapshot.get("rounds", {}):
                raise ValueError("assessment source Round is absent from State")
        except Exception as exc:
            invalid_assessments.append({"assessment_id": row.get("assessment_id"), "error": str(exc)})
    check("ASSESSMENT_IDS_UNIQUE", len(assessment_ids) == len(set(assessment_ids)))
    check("RESULT_ASSESSMENT_INDEX", not invalid_assessments, invalid_assessments)
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
            report_mode = _round_report_mode(root, control, snapshot)
            if _screening_enabled(root, control, snapshot):
                screening_fresh, screening_ref = _screening_summary_fresh(root, snapshot, control["active_round_id"])
                check("SCREENING_SUMMARY_FRESH", screening_fresh, {"summary_ref": screening_ref})
                pending_screening = _pending_screening_bundles(root, snapshot, control["active_round_id"])
                check("ROUND_RESULTS_ASSESSED", not pending_screening, {"unassessed_count": len(pending_screening)})
            if report_mode == "screening":
                pass
            else:
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
        handoff_ref = _handoff_marker(root, control, snapshot)
        snapshot["rounds"][control["active_round_id"]]["latest_audit"] = {"status": audit["status"], "path": str((output / "audit.json").relative_to(root)), "created_at": audit["created_at"], "after_interpretation_node": interpretation, "after_handoff_ref": handoff_ref}
        _commit(root, control, snapshot, "full_audit_registered", {"status": audit["status"], "path": str(output.relative_to(root)), "after_interpretation_node": interpretation, "after_handoff_ref": handoff_ref}, round_id=control["active_round_id"])
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
        report_mode = _round_report_mode(root, control, snapshot)
        interpretation_node: str | None = None
        screening_summary_ref: str | None = None
        if report_mode == "screening":
            fresh, screening_summary_ref = _screening_summary_fresh(root, snapshot, round_id)
            handoff_marker = f"screening:{screening_summary_ref}" if fresh and screening_summary_ref else None
        else:
            fresh, interpretation_node = _interpretation_fresh(snapshot, round_id)
            handoff_marker = f"interpretation:{interpretation_node}" if fresh and interpretation_node else None
        audit = snapshot["rounds"][round_id].get("latest_audit")
        audit_marker = (audit or {}).get("after_handoff_ref") or (f"interpretation:{audit.get('after_interpretation_node')}" if audit and audit.get("after_interpretation_node") else None)
        if not fresh or not audit or audit.get("status") != "pass" or audit_marker != handoff_marker:
            raise ValueError("Round handoff artifact and Full Audit gate are not satisfied")
        deliverables = _deliverable_status(root, control, snapshot)
        completion = _anticipated_outcome(root, control, snapshot)
        stop_reason = snapshot["rounds"][round_id].get("finalizing_reason") or "contract_satisfied"
        if stop_reason == "analysis_node_budget_exhausted":
            stop_reason = "budget_exhausted"
        if stop_reason not in {"contract_satisfied", "budget_exhausted", "no_eligible_work", "human_checkpoint", "abnormal_interruption", "blocked"}:
            stop_reason = "blocked" if completion == "blocked" else "contract_satisfied"
        outcome = {"schema_version": "1.0.0", "round_id": round_id, "report_mode": report_mode, "completion": completion, "stop_reason": stop_reason, "deliverables": deliverables, "interpretation_node_id": interpretation_node, "screening_summary_ref": screening_summary_ref, "audit_ref": audit["path"], "created_at": utc_now()}
        validate(outcome, "round_outcome.schema.json")
        write_json(root / "rounds" / round_id / "round_outcome.json", outcome)
        if interpretation_node:
            write_json(root / "rounds" / round_id / "interpretation_ref.json", {"schema_version": "1.0.0", "round_id": round_id, "node_id": interpretation_node, "path": str(Path(_node_lookup(snapshot)[interpretation_node]["output_ref"]).relative_to(root)), "created_at": utc_now()})
        elif screening_summary_ref:
            write_json(root / "rounds" / round_id / "screening_ref.json", {"schema_version": "1.0.0", "round_id": round_id, "path": screening_summary_ref, "created_at": utc_now()})
        snapshot["rounds"][round_id].update({"state": "AWAITING_HUMAN_REVIEW", "outcome": completion, "handoff_at": utc_now()})
        control.update({"round_state": "AWAITING_HUMAN_REVIEW", "blocker": None})
        control["closure"] = {"contract_satisfied": completion == "complete", "interpretation_ready": bool(interpretation_node), "audit_ready": True, "outcome": completion}
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
    elif args.kind == "assessment":
        data = _latest_assessments(root)
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
        if not node or node["status"] not in {"pending", "failed"}:
            raise ValueError("Only a pending or failed Node can be cancelled")
        downstream = [item for item in snapshot["nodes"] if args.node_id in item["input_nodes"] and item["status"] not in {"cancelled", "failed"}]
        if downstream:
            raise ValueError(f"Active downstream Nodes prevent cancellation: {[item['node_id'] for item in downstream]}")
        node.update({"status": "cancelled", "assigned_round": None, "finished_at": utc_now(), "result_quality": {"validation_passed": False, "eligible_for_downstream": False, "quality_flags": ["human_cancelled"]}})
        _commit(root, control, snapshot, "node_cancelled_by_human", {"reason": args.reason}, round_id=control.get("active_round_id"), node_id=node["node_id"])
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
    parser = argparse.ArgumentParser(description="CONDUCTOR 0.2.0 deterministic Runtime Controller")
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
    item.add_argument("--max-additional-nodes", type=int, default=50)
    item.add_argument("--report-mode", choices=["screening", "full"], default="screening")
    item.add_argument("--cumulative-interpretation", action="store_true", help="Create a report-only full Round from unreported assessments in prior CLOSED Rounds")
    item.add_argument("--historical-rescreening", action="store_true", help="Create a Screening-only Round over Review Bundles from explicitly selected CLOSED Rounds")
    item.add_argument("--source-round-id", action="append", help="CLOSED source Round for cumulative Interpretation or historical re-Screening; repeatable")
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
    item.add_argument("--smiles-column", help="Populate missing SMILES metadata on a structurally valid current-version Run; an existing value is immutable")
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
    # ``--packet`` is the canonical public spelling.  Accept ``--packet-path``
    # only at this human/LLM-facing boundary because prepare-execution-packet
    # returns a JSON field named ``packet_path``.  Both spellings normalize to
    # one internal destination and do not alter packet identity or signatures.
    item.add_argument("--packet", "--packet-path", dest="packet", required=True)
    item.set_defaults(func=cmd_execute_packet)

    # Internal deterministic OS worker. It is spawned only by execute-packet;
    # Orchestrator and Executor instructions never call it directly.
    item = commands.add_parser("_worker-execute-packet", help=argparse.SUPPRESS)
    item.add_argument("--run-root", required=True)
    item.add_argument("--packet", required=True)
    item.set_defaults(func=cmd_worker_execute_packet)

    item = commands.add_parser("reconcile-running")
    _action_args(item)
    item.set_defaults(func=cmd_reconcile_running)

    item = commands.add_parser("retry-node")
    _action_args(item)
    item.add_argument("--node-id", required=True)
    item.add_argument("--reason", required=True)
    item.add_argument("--control-key")
    item.set_defaults(func=cmd_retry_node)

    item = commands.add_parser("enter-finalizing")
    _action_args(item)
    item.set_defaults(func=cmd_enter_finalizing)

    item = commands.add_parser("prepare-result-screening")
    _action_args(item)
    item.set_defaults(func=cmd_prepare_result_screening)

    item = commands.add_parser("commit-result-screening")
    _action_args(item)
    item.add_argument("--batch-id", required=True)
    item.add_argument("--draft")
    item.set_defaults(func=cmd_commit_result_screening)

    item = commands.add_parser("reset-result-screening")
    item.add_argument("--run-root", required=True)
    item.add_argument("--control-key", required=True)
    item.add_argument("--reason", required=True)
    item.set_defaults(func=cmd_reset_result_screening)

    item = commands.add_parser("request-result-rescreening")
    item.add_argument("--run-root", required=True)
    item.add_argument("--control-key", required=True)
    selection = item.add_mutually_exclusive_group(required=True)
    selection.add_argument("--all-current", action="store_true")
    selection.add_argument("--bundle-id", action="append")
    item.add_argument("--batch-size", type=int, default=4)
    item.add_argument("--additional-walltime-minutes", type=int)
    item.add_argument("--reason", required=True)
    item.set_defaults(func=cmd_request_result_rescreening)

    item = commands.add_parser("write-screening-summary")
    _action_args(item)
    item.set_defaults(func=cmd_write_screening_summary)

    item = commands.add_parser("prepare-interpretation")
    _action_args(item)
    item.add_argument("--focus")
    item.add_argument("--rereview-result-ref", action="append")
    item.add_argument("--detailed-limit", type=int, default=50)
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
    item.add_argument("--kind", choices=["control", "working-set", "node", "cluster", "result", "assessment", "insight", "candidates"], required=True)
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
