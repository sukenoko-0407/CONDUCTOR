from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import math
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VERSION = "0.1.8"
REQUEST_PATTERN = re.compile(r"^REQ(\d{6,})$")
FOCUS_PATTERN = re.compile(r"^[A-Z][A-Z0-9_-]*\d+$")
MAX_FOCUS_MATCHES = 100
MAX_FIGURES = 12
MAX_FIGURE_POINTS = 5000


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def frozen_state_errors(control: dict[str, Any], snapshot: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    active_round = control.get("active_round_id")
    round_state = control.get("round_state")
    if round_state in {"ACTIVE", "FINALIZING"}:
        errors.append(f"mutable Round state: {round_state} ({active_round})")
    elif round_state not in {"AWAITING_HUMAN_REVIEW", "CLOSED", "NO_ACTIVE_ROUND"}:
        errors.append(f"unsupported Round state: {round_state}")
    running = [
        str(node.get("node_id"))
        for node in snapshot.get("nodes") or []
        if node.get("status") == "running"
    ]
    if running:
        errors.append("running Nodes exist: " + ", ".join(running[:20]))
    lease = control.get("lease") or {}
    owner = lease.get("owner_id")
    expiry = parse_datetime(lease.get("expires_at"))
    if owner and (expiry is None or expiry > datetime.now(timezone.utc)):
        errors.append(f"live Orchestrator lease exists: {owner}")
    return errors


def validate_run_root(value: str) -> tuple[Path, Path, Path, dict[str, Any], dict[str, Any]]:
    run_root = Path(value).expanduser().resolve()
    control_path = run_root / "conductor_control.json"
    snapshot_path = run_root / "runtime" / "dag_snapshot.json"
    if not control_path.is_file() or not snapshot_path.is_file():
        raise FileNotFoundError("conductor_control.json or runtime/dag_snapshot.json is missing")
    control, snapshot = load_json(control_path), load_json(snapshot_path)
    if control.get("conductor_version") != VERSION or not isinstance(snapshot.get("nodes"), list):
        raise ValueError(f"The supplied directory is not a supported CONDUCTOR {VERSION} Run Root")
    errors = frozen_state_errors(control, snapshot)
    if errors:
        raise RuntimeError("Run is not frozen; concierge request refused: " + "; ".join(errors))
    return run_root, control_path, snapshot_path, control, snapshot


def path_from_state(value: str, run_root: Path) -> Path | None:
    raw = Path(value).expanduser()
    candidates = [raw] if raw.is_absolute() else [run_root / raw]
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.exists() and is_relative_to(resolved, run_root):
            return resolved
    return None


def candidate_sources(control_path: Path, snapshot_path: Path, snapshot: dict[str, Any], run_root: Path) -> list[Path]:
    candidates: list[Path] = [control_path, snapshot_path]
    nodes = snapshot.get("nodes") or []
    for node in nodes:
        if node.get("kind") != "interpretation" or node.get("status") != "succeeded":
            continue
        output_value = node.get("output_ref")
        if not isinstance(output_value, str):
            continue
        output_dir = path_from_state(output_value, run_root)
        if output_dir is None or not output_dir.is_dir():
            continue
        for name in ["interpretation.json", "interpretation.md", "interpretation.html", "quality_report.json"]:
            path = output_dir / name
            if path.is_file():
                candidates.append(path.resolve())
    unique: dict[str, Path] = {}
    concierge_root = (run_root / "concierge").resolve()
    for path in candidates:
        if path.is_file() and is_relative_to(path, run_root) and not is_relative_to(path, concierge_root):
            unique[str(path)] = path
    return sorted(unique.values(), key=str)


def focus_matches(paths: list[Path], focus_ids: list[str], run_root: Path) -> list[dict[str, Any]]:
    if not focus_ids:
        return []
    matches: list[dict[str, Any]] = []
    for path in paths:
        if path.suffix.lower() not in {".json", ".md", ".html", ".csv", ".yaml", ".yml"}:
            continue
        if path.stat().st_size > 20 * 1024 * 1024:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        found = [focus_id for focus_id in focus_ids if focus_id in text]
        if found:
            matches.append({"path": path.relative_to(run_root).as_posix(), "focus_ids": found})
        if len(matches) >= MAX_FOCUS_MATCHES:
            break
    return matches


def state_context(control: dict[str, Any], snapshot: dict[str, Any], source_paths: list[Path], focus_ids: list[str], run_root: Path) -> dict[str, Any]:
    nodes = snapshot.get("nodes") or []
    by_stage: dict[str, Counter[str]] = defaultdict(Counter)
    for node in nodes:
        by_stage[str(node.get("kind", "unknown"))][str(node.get("status", "unknown"))] += 1
    rounds = list(snapshot.get("rounds", {}).values())
    interpretations = [
        {
            "node_id": node.get("node_id"),
            "round_id": node.get("created_in_round"),
            "status": node.get("status"),
            "output_dir": node.get("output_ref"),
            "finished_at": node.get("finished_at"),
        }
        for node in nodes
        if node.get("kind") == "interpretation"
    ]
    return {
        "generated_at": utc_now(),
        "run": control.get("run") or {},
        "rounds": rounds,
        "active_round_id": control.get("active_round_id"),
        "node_counts": {stage: dict(sorted(counts.items())) for stage, counts in sorted(by_stage.items())},
        "interpretation_nodes": interpretations,
        "focus_ids": focus_ids,
        "focus_matches": focus_matches(source_paths, focus_ids, run_root),
        "captured_sources": [path.relative_to(run_root).as_posix() for path in source_paths],
        "instructions": [
            "Read control_snapshot.json and dag_snapshot.json instead of live Runtime files after prepare.",
            "Register every additional artifact with add-source before reading it.",
            "Write only response_draft.json inside this request directory.",
        ],
    }


def allocate_request_dir(run_root: Path) -> tuple[str, Path]:
    root = run_root / "concierge"
    root.mkdir(parents=True, exist_ok=True)
    existing = []
    for child in root.iterdir():
        match = REQUEST_PATTERN.match(child.name) if child.is_dir() else None
        if match:
            existing.append(int(match.group(1)))
    candidate = max(existing, default=0) + 1
    while True:
        request_id = f"REQ{candidate:06d}"
        request_dir = root / request_id
        try:
            request_dir.mkdir()
            return request_id, request_dir.resolve()
        except FileExistsError:
            candidate += 1


def source_entry(path: Path, run_root: Path, kind: str = "artifact") -> dict[str, Any]:
    return {
        "path": path.relative_to(run_root).as_posix(),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "kind": kind,
    }


def run_inventory(run_root: Path) -> list[dict[str, Any]]:
    """Capture cheap mutation evidence for every run file outside concierge/."""
    concierge_root = (run_root / "concierge").resolve()
    entries: list[dict[str, Any]] = []
    for path in run_root.rglob("*"):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if is_relative_to(resolved, concierge_root):
            continue
        stat = resolved.stat()
        entries.append(
            {
                "path": resolved.relative_to(run_root).as_posix(),
                "bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    return sorted(entries, key=lambda item: item["path"])


def resolve_request_dir(value: str) -> tuple[Path, Path, dict[str, Any]]:
    request_dir = Path(value).expanduser().resolve()
    if not request_dir.is_dir() or not REQUEST_PATTERN.match(request_dir.name):
        raise ValueError(f"Invalid concierge request directory: {request_dir}")
    request_path = request_dir / "request.json"
    if not request_path.is_file():
        raise FileNotFoundError(f"Missing request.json: {request_path}")
    request = load_json(request_path)
    run_root = Path(str(request.get("run_root", ""))).expanduser().resolve()
    expected_root = (run_root / "concierge").resolve()
    if request_dir.parent != expected_root or Path(str(request.get("control_path", ""))).resolve() != run_root / "conductor_control.json":
        raise ValueError("Request directory is not bound to its recorded Run Root")
    if request.get("request_id") != request_dir.name:
        raise ValueError("request_id does not match its directory")
    return request_dir, run_root, request


def read_request_text(args: argparse.Namespace) -> str:
    if args.request is not None:
        value = args.request
    else:
        request_file = Path(args.request_file).expanduser().resolve()
        if not request_file.is_file():
            raise FileNotFoundError(f"Request file does not exist: {request_file}")
        value = request_file.read_text(encoding="utf-8")
    value = value.strip()
    if not value:
        raise ValueError("Human request must not be empty")
    return value


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    if not args.explicit_request:
        raise ValueError("prepare requires --explicit-request")
    run_root, control_path, snapshot_path, control, snapshot = validate_run_root(args.run_root)
    if (run_root / "concierge").resolve() == run_root:
        raise ValueError("Invalid run_root")
    focus_ids = list(dict.fromkeys(args.focus_id or []))
    for focus_id in focus_ids:
        if not FOCUS_PATTERN.match(focus_id):
            raise ValueError(f"Invalid focus ID: {focus_id}")
    question = read_request_text(args)
    paths = candidate_sources(control_path, snapshot_path, snapshot, run_root)
    inventory = run_inventory(run_root)
    request_id, request_dir = allocate_request_dir(run_root)
    manifest = {
        "schema_version": "1.0.0",
        "request_id": request_id,
        "captured_at": utc_now(),
        "run_root": str(run_root),
        "sources": [source_entry(path, run_root, "runtime" if path in {control_path, snapshot_path} else "artifact") for path in paths],
    }
    request = {
        "schema_version": "1.0.0",
        "request_id": request_id,
        "status": "prepared",
        "created_at": utc_now(),
        "finalized_at": None,
        "control_path": str(control_path),
        "snapshot_path": str(snapshot_path),
        "run_root": str(run_root),
        "human_request": question,
        "focus_ids": focus_ids,
        "write_scope": str(request_dir),
        "outputs": {},
    }
    draft = {
        "title": "CONDUCTOR結果コンシェルジュ回答",
        "request_summary": question,
        "answer_markdown": "REPLACE_WITH_EVIDENCE_BASED_ANSWER",
        "focus_ids": focus_ids,
        "source_paths": ["conductor_control.json", "runtime/dag_snapshot.json"],
        "figures": [],
        "limitations": [],
        "suggested_next_round_prompt": None,
    }
    write_json(request_dir / "request.json", request)
    write_json(request_dir / "source_manifest.json", manifest)
    write_json(request_dir / "run_inventory.json", {"captured_at": utc_now(), "files": inventory})
    write_json(request_dir / "control_snapshot.json", control)
    write_json(request_dir / "dag_snapshot.json", snapshot)
    write_json(request_dir / "context.json", state_context(control, snapshot, paths, focus_ids, run_root))
    write_json(request_dir / "response_draft.json", draft)
    (request_dir / "scratch").mkdir(exist_ok=True)
    return {
        "status": "prepared",
        "request_id": request_id,
        "request_dir": str(request_dir),
        "context": str(request_dir / "context.json"),
        "draft": str(request_dir / "response_draft.json"),
        "scratch": str(request_dir / "scratch"),
        "captured_source_count": len(paths),
        "inventoried_run_file_count": len(inventory),
    }


def run_helper(args: argparse.Namespace) -> dict[str, Any]:
    """Run one request-local Python helper without granting writes to the frozen Run."""
    request_dir, run_root, request = resolve_request_dir(args.request_dir)
    validate_run_root(str(run_root))
    if request.get("status") not in {"prepared", "completed"}:
        raise ValueError(f"Unsupported concierge request status: {request.get('status')}")
    scratch = (request_dir / "scratch").resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    script = Path(args.script).expanduser().resolve()
    if not script.is_file() or not is_relative_to(script, scratch) or script.suffix.lower() != ".py":
        raise ValueError("Helper must be an existing Python file below request_dir/scratch/")
    helper_args = list(args.script_args or [])
    if helper_args[:1] == ["--"]:
        helper_args = helper_args[1:]
    invocation_id = datetime.now(timezone.utc).strftime("HELPER_%Y%m%dT%H%M%S%fZ")
    invocation_dir = scratch / invocation_id
    invocation_dir.mkdir(parents=True, exist_ok=False)
    temporary = invocation_dir / "tmp"
    temporary.mkdir()
    command = [sys.executable, str(script), *helper_args]
    environment = os.environ.copy()
    environment.update({
        "TMPDIR": str(temporary),
        "TMP": str(temporary),
        "TEMP": str(temporary),
        "JOBLIB_TEMP_FOLDER": str(temporary / "joblib"),
        "MPLCONFIGDIR": str(temporary / "matplotlib"),
        "NUMBA_CACHE_DIR": str(temporary / "numba"),
        "PYTHONPYCACHEPREFIX": str(temporary / "pycache"),
    })
    timeout_seconds = min(28800, max(1, int(args.timeout_seconds)))
    write_json(invocation_dir / "command.json", {
        "schema_version": "1.0.0",
        "script": str(script.relative_to(request_dir)),
        "script_sha256": sha256_file(script),
        "arguments": helper_args,
        "working_directory": str(scratch),
        "timeout_seconds": timeout_seconds,
        "created_at": utc_now(),
    })
    returncode = 124
    timed_out = False
    with (invocation_dir / "stdout.log").open("w", encoding="utf-8") as stdout, (invocation_dir / "stderr.log").open("w", encoding="utf-8") as stderr:
        try:
            completed = subprocess.run(
                command,
                cwd=scratch,
                env=environment,
                stdout=stdout,
                stderr=stderr,
                timeout=timeout_seconds,
                check=False,
            )
            returncode = int(completed.returncode)
        except subprocess.TimeoutExpired:
            timed_out = True
    result = {
        "status": "succeeded" if returncode == 0 else "error",
        "request_id": request_dir.name,
        "returncode": returncode,
        "timed_out": timed_out,
        "invocation_dir": str(invocation_dir),
        "stdout": str(invocation_dir / "stdout.log"),
        "stderr": str(invocation_dir / "stderr.log"),
    }
    write_json(invocation_dir / "result.json", result)
    return result


def resolve_source(value: str, run_root: Path) -> Path:
    raw = Path(value).expanduser()
    candidates = [raw] if raw.is_absolute() else [Path.cwd() / raw, run_root / raw]
    source = next((candidate.resolve() for candidate in candidates if candidate.resolve().is_file()), None)
    if source is None:
        raise FileNotFoundError(f"Source file does not exist: {value}")
    concierge_root = (run_root / "concierge").resolve()
    if not is_relative_to(source, run_root) or is_relative_to(source, concierge_root):
        raise ValueError("Source must be a read-only file under run_root and outside concierge/")
    return source


def add_source(args: argparse.Namespace) -> dict[str, Any]:
    request_dir, run_root, request = resolve_request_dir(args.request_dir)
    if request.get("status") != "prepared":
        raise RuntimeError("Sources cannot be added after finalization")
    manifest_path = request_dir / "source_manifest.json"
    manifest = load_json(manifest_path)
    by_path = {entry["path"]: entry for entry in manifest.get("sources") or []}
    added = []
    for value in args.source:
        source = resolve_source(value, run_root)
        relative = source.relative_to(run_root).as_posix()
        entry = source_entry(source, run_root)
        previous = by_path.get(relative)
        if previous and previous.get("sha256") != entry["sha256"]:
            raise RuntimeError(f"Previously captured source changed: {relative}")
        if not previous:
            by_path[relative] = entry
            added.append(relative)
    manifest["sources"] = [by_path[key] for key in sorted(by_path)]
    manifest["updated_at"] = utc_now()
    write_json(manifest_path, manifest)
    return {"status": "ok", "request_id": request_dir.name, "added": added, "source_count": len(by_path)}


def verify_source_manifest(request_dir: Path, run_root: Path) -> list[dict[str, Any]]:
    manifest = load_json(request_dir / "source_manifest.json")
    problems = []
    for entry in manifest.get("sources") or []:
        relative = entry.get("path")
        if not isinstance(relative, str):
            problems.append({"path": relative, "problem": "invalid path"})
            continue
        path = (run_root / relative).resolve()
        if not is_relative_to(path, run_root) or is_relative_to(path, (run_root / "concierge").resolve()):
            problems.append({"path": relative, "problem": "outside frozen source scope"})
        elif not path.is_file():
            problems.append({"path": relative, "problem": "missing"})
        else:
            actual = sha256_file(path)
            if actual != entry.get("sha256"):
                problems.append({"path": relative, "problem": "hash changed", "actual_sha256": actual})
    return problems


def inventory_drift(request_dir: Path, run_root: Path) -> list[dict[str, Any]]:
    expected_path = request_dir / "run_inventory.json"
    if not expected_path.is_file():
        return [{"problem": "missing run_inventory.json"}]
    expected = {entry["path"]: entry for entry in load_json(expected_path).get("files") or []}
    current = {entry["path"]: entry for entry in run_inventory(run_root)}
    problems: list[dict[str, Any]] = []
    for relative in sorted(set(expected) | set(current)):
        if relative not in current:
            problems.append({"path": relative, "problem": "deleted after prepare"})
        elif relative not in expected:
            problems.append({"path": relative, "problem": "created after prepare"})
        elif current[relative] != expected[relative]:
            problems.append({"path": relative, "problem": "size or modification time changed after prepare"})
    return problems


def validate_draft(draft: dict[str, Any], captured: set[str]) -> None:
    required = {
        "title", "request_summary", "answer_markdown", "focus_ids", "source_paths",
        "figures", "limitations", "suggested_next_round_prompt",
    }
    if set(draft) != required:
        raise ValueError(f"response_draft.json fields must be exactly: {', '.join(sorted(required))}")
    for key in ["title", "request_summary", "answer_markdown"]:
        if not isinstance(draft[key], str) or not draft[key].strip():
            raise ValueError(f"{key} must be a non-empty string")
    if "REPLACE_WITH_" in draft["answer_markdown"]:
        raise ValueError("response_draft.json still contains its placeholder answer")
    for key in ["focus_ids", "source_paths", "figures", "limitations"]:
        if not isinstance(draft[key], list):
            raise ValueError(f"{key} must be an array")
    if not all(isinstance(item, str) for item in draft["focus_ids"] + draft["source_paths"] + draft["limitations"]):
        raise ValueError("focus_ids, source_paths, and limitations must contain strings")
    if len(draft["source_paths"]) != len(set(draft["source_paths"])):
        raise ValueError("source_paths must be unique")
    missing = set(draft["source_paths"]) - captured
    if missing:
        raise ValueError("Draft cites uncaptured sources: " + ", ".join(sorted(missing)))
    if draft["suggested_next_round_prompt"] is not None and not isinstance(draft["suggested_next_round_prompt"], str):
        raise ValueError("suggested_next_round_prompt must be a string or null")
    if len(draft["figures"]) > MAX_FIGURES:
        raise ValueError(f"At most {MAX_FIGURES} figures are allowed")
    seen_ids: set[str] = set()
    for figure in draft["figures"]:
        if not isinstance(figure, dict):
            raise ValueError("Each figure must be an object")
        keys = {"figure_id", "kind", "title", "x", "y", "x_label", "y_label", "caption", "source_paths"}
        if set(figure) != keys:
            raise ValueError(f"Figure fields must be exactly: {', '.join(sorted(keys))}")
        figure_id = figure["figure_id"]
        if not isinstance(figure_id, str) or not re.fullmatch(r"FIG\d{3,}", figure_id) or figure_id in seen_ids:
            raise ValueError(f"Invalid or duplicate figure_id: {figure_id}")
        seen_ids.add(figure_id)
        if figure["kind"] not in {"bar", "line", "scatter"}:
            raise ValueError(f"Unsupported figure kind: {figure['kind']}")
        x_values, y_values = figure["x"], figure["y"]
        if not isinstance(x_values, list) or not isinstance(y_values, list) or len(x_values) != len(y_values):
            raise ValueError(f"{figure_id}: x and y must be equal-length arrays")
        if not x_values or len(x_values) > MAX_FIGURE_POINTS:
            raise ValueError(f"{figure_id}: point count must be 1..{MAX_FIGURE_POINTS}")
        if not all(isinstance(value, (int, float)) and math.isfinite(float(value)) for value in y_values):
            raise ValueError(f"{figure_id}: y must contain finite numbers")
        if figure["kind"] in {"line", "scatter"} and not all(
            isinstance(value, (int, float)) and math.isfinite(float(value)) for value in x_values
        ):
            raise ValueError(f"{figure_id}: {figure['kind']} x values must be finite numbers")
        if not isinstance(figure["source_paths"], list) or not figure["source_paths"]:
            raise ValueError(f"{figure_id}: source_paths must not be empty")
        missing = set(figure["source_paths"]) - captured
        if missing:
            raise ValueError(f"{figure_id} cites uncaptured sources: {', '.join(sorted(missing))}")


def svg_text(value: Any) -> str:
    return html.escape(str(value), quote=True)


def render_figure_svg(figure: dict[str, Any]) -> str:
    width, height = 900, 500
    left, right, top, bottom = 92, 38, 68, 92
    plot_w, plot_h = width - left - right, height - top - bottom
    y_values = [float(value) for value in figure["y"]]
    y_min, y_max = min(y_values), max(y_values)
    if y_min == y_max:
        padding = abs(y_min) * 0.1 or 1.0
        y_min, y_max = y_min - padding, y_max + padding
    else:
        padding = (y_max - y_min) * 0.08
        y_min, y_max = y_min - padding, y_max + padding
    if figure["kind"] == "bar":
        x_numbers = [float(index) for index in range(len(figure["x"]))]
        labels = [str(value) for value in figure["x"]]
    else:
        x_numbers = [float(value) for value in figure["x"]]
        labels = []
    x_min, x_max = min(x_numbers), max(x_numbers)
    if x_min == x_max:
        x_min, x_max = x_min - 0.5, x_max + 0.5

    def sx(value: float) -> float:
        return left + (value - x_min) / (x_max - x_min) * plot_w

    def sy(value: float) -> float:
        return top + (y_max - value) / (y_max - y_min) * plot_h

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#fbfaf7"/>',
        f'<text x="{left}" y="34" font-family="Segoe UI, sans-serif" font-size="22" font-weight="600" fill="#304957">{svg_text(figure["title"])}</text>',
    ]
    for tick in range(6):
        value = y_min + (y_max - y_min) * tick / 5
        y = sy(value)
        parts.append(f'<line x1="{left}" y1="{y:.2f}" x2="{left + plot_w}" y2="{y:.2f}" stroke="#d9d5cc" stroke-width="1"/>')
        parts.append(f'<text x="{left - 10}" y="{y + 4:.2f}" text-anchor="end" font-family="Segoe UI, sans-serif" font-size="12" fill="#68747b">{value:.4g}</text>')
    parts.extend([
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="#304957" stroke-width="2"/>',
        f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="#304957" stroke-width="2"/>',
    ])
    colour = "#607a78"
    if figure["kind"] == "bar":
        bar_width = max(2.0, plot_w / max(len(x_numbers), 1) * 0.62)
        zero_y = sy(max(y_min, min(0.0, y_max)))
        for index, (x_value, y_value) in enumerate(zip(x_numbers, y_values)):
            x = sx(x_value) - bar_width / 2
            y = min(sy(y_value), zero_y)
            h = max(abs(zero_y - sy(y_value)), 1.0)
            parts.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_width:.2f}" height="{h:.2f}" rx="2" fill="{colour}"/>')
            if len(labels) <= 30:
                parts.append(f'<text x="{sx(x_value):.2f}" y="{top + plot_h + 20}" text-anchor="middle" font-family="Segoe UI, sans-serif" font-size="11" fill="#68747b">{svg_text(labels[index][:18])}</text>')
    else:
        points = [(sx(x), sy(y)) for x, y in zip(x_numbers, y_values)]
        if figure["kind"] == "line":
            path = " ".join(("M" if index == 0 else "L") + f" {x:.2f} {y:.2f}" for index, (x, y) in enumerate(points))
            parts.append(f'<path d="{path}" fill="none" stroke="{colour}" stroke-width="3"/>')
        radius = 4 if len(points) <= 500 else 2
        for x, y in points:
            parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius}" fill="#9a6a50" fill-opacity="0.78"/>')
    parts.extend([
        f'<text x="{left + plot_w / 2}" y="{height - 28}" text-anchor="middle" font-family="Segoe UI, sans-serif" font-size="14" fill="#304957">{svg_text(figure["x_label"])}</text>',
        f'<text x="24" y="{top + plot_h / 2}" text-anchor="middle" transform="rotate(-90 24 {top + plot_h / 2})" font-family="Segoe UI, sans-serif" font-size="14" fill="#304957">{svg_text(figure["y_label"])}</text>',
        '</svg>',
    ])
    return "\n".join(parts) + "\n"


def inline_markdown(value: str) -> str:
    escaped = html.escape(value)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def markdown_fragment(value: str) -> str:
    output: list[str] = []
    paragraph: list[str] = []
    list_open = False

    def flush_paragraph() -> None:
        if paragraph:
            output.append("<p>" + "<br>".join(inline_markdown(line) for line in paragraph) + "</p>")
            paragraph.clear()

    for raw in value.splitlines():
        line = raw.rstrip()
        if not line:
            flush_paragraph()
            if list_open:
                output.append("</ul>")
                list_open = False
            continue
        heading = re.match(r"^(#{1,4})\s+(.+)$", line)
        bullet = re.match(r"^[-*]\s+(.+)$", line)
        if heading:
            flush_paragraph()
            if list_open:
                output.append("</ul>")
                list_open = False
            level = min(len(heading.group(1)) + 2, 6)
            output.append(f"<h{level}>{inline_markdown(heading.group(2))}</h{level}>")
        elif bullet:
            flush_paragraph()
            if not list_open:
                output.append("<ul>")
                list_open = True
            output.append(f"<li>{inline_markdown(bullet.group(1))}</li>")
        else:
            if list_open:
                output.append("</ul>")
                list_open = False
            paragraph.append(line)
    flush_paragraph()
    if list_open:
        output.append("</ul>")
    return "\n".join(output)


def markdown_report(request: dict[str, Any], draft: dict[str, Any], figures: list[dict[str, Any]]) -> str:
    lines = [
        f"# {draft['title']}", "",
        f"- Request ID: `{request['request_id']}`",
        f"- Generated: `{request['finalized_at']}`",
        f"- Run root: `{request['run_root']}`", "",
        "## 人間からの依頼", "", draft["request_summary"], "",
        "## 回答", "", draft["answer_markdown"].strip(), "",
    ]
    if figures:
        lines.extend(["## Figure", ""])
        for figure in figures:
            lines.extend([
                f"### {figure['figure_id']}: {figure['title']}", "",
                f"![{figure['title']}](figures/{figure['file_name']})", "",
                figure["caption"], "",
                "Source: " + ", ".join(f"`{path}`" for path in figure["source_paths"]), "",
            ])
    lines.extend(["## 根拠ファイル", ""])
    lines.extend(f"- `{path}`" for path in draft["source_paths"])
    lines.extend(["", "## 制約・留意点", ""])
    if draft["limitations"]:
        lines.extend(f"- {item}" for item in draft["limitations"])
    else:
        lines.append("- 特記事項なし。既存artifactの範囲内で回答した。")
    if draft["suggested_next_round_prompt"]:
        lines.extend(["", "## 次Roundへの提案（未実行）", "", draft["suggested_next_round_prompt"].strip()])
    lines.extend(["", "---", "このreportは既存結果のread-only解説であり、State/DAGには登録されない。", ""])
    return "\n".join(lines)


def html_report(request: dict[str, Any], draft: dict[str, Any], figures: list[dict[str, Any]], request_dir: Path) -> str:
    focus = "".join(f'<span class="tag">{html.escape(value)}</span>' for value in draft["focus_ids"])
    figure_blocks = []
    for figure in figures:
        payload = base64.b64encode((request_dir / "figures" / figure["file_name"]).read_bytes()).decode("ascii")
        sources = ", ".join(f"<code>{html.escape(path)}</code>" for path in figure["source_paths"])
        figure_blocks.append(
            f'<figure><img src="data:image/svg+xml;base64,{payload}" alt="{html.escape(figure["title"])}">'
            f'<figcaption><b>{html.escape(figure["figure_id"])}: {html.escape(figure["title"])}</b><br>'
            f'{html.escape(figure["caption"])}<small>Source: {sources}</small></figcaption></figure>'
        )
    sources = "".join(f"<li><code>{html.escape(path)}</code></li>" for path in draft["source_paths"])
    limitations = "".join(f"<li>{inline_markdown(item)}</li>" for item in draft["limitations"])
    if not limitations:
        limitations = "<li>特記事項なし。既存artifactの範囲内で回答した。</li>"
    next_round = ""
    if draft["suggested_next_round_prompt"]:
        next_round = (
            '<section class="next"><h2>次Roundへの提案（未実行）</h2>'
            f'<pre>{html.escape(draft["suggested_next_round_prompt"].strip())}</pre></section>'
        )
    css = """
:root{--ink:#293940;--navy:#334d59;--muted:#6d787b;--paper:#f1efe9;--surface:#fff;--line:#d7d4cc;--sage:#607a78;--sage-soft:#e7eeeb;--rust:#91634e;--rust-soft:#f2e9e3}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.75 "Yu Gothic UI","Segoe UI",sans-serif}main{max-width:1120px;margin:28px auto;padding:46px 54px 64px;background:var(--surface);box-shadow:0 12px 34px #26364018}header{border-bottom:2px solid var(--navy);padding-bottom:20px}h1,h2,h3{color:var(--navy)}h1{font-size:31px;margin:5px 0}h2{font-size:22px;margin-top:40px;border-bottom:1px solid var(--line);padding-bottom:7px}.meta{color:var(--muted);font-size:13px}.request{margin:24px 0;padding:16px 20px;border-left:5px solid var(--sage);background:var(--sage-soft)}.answer{font-size:16px}.tag{display:inline-block;margin:4px 6px 0 0;padding:3px 9px;background:#edf0ef;border:1px solid var(--line);border-radius:3px;font-size:12px;font-weight:700}figure{margin:22px 0;padding:16px;border:1px solid var(--line);background:#fbfaf7}figure img{display:block;width:100%;height:auto}figcaption{margin-top:10px;color:var(--muted)}figcaption b{color:var(--navy)}figcaption small{display:block;margin-top:5px}code{background:#f1f2ef;padding:1px 4px;word-break:break-all}pre{white-space:pre-wrap;word-break:break-word;padding:16px;background:#f5f4f0;border:1px solid var(--line)}.next{padding:1px 20px 18px;border-left:5px solid var(--rust);background:var(--rust-soft)}.freeze{margin-top:42px;padding:12px 16px;color:var(--muted);border-top:1px solid var(--line);font-size:12px}@media(max-width:720px){main{margin:0;padding:26px 20px}}@media print{body{background:#fff}main{margin:0;box-shadow:none;max-width:none}}
"""
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(draft['title'])}</title><style>{css}</style></head>
<body><main><header><div class="meta">CONDUCTOR Result Concierge · {html.escape(request['request_id'])} · {html.escape(request['finalized_at'])}</div><h1>{html.escape(draft['title'])}</h1><div>{focus}</div></header>
<section class="request"><h2>人間からの依頼</h2><p>{html.escape(draft['request_summary'])}</p></section>
<section class="answer"><h2>回答</h2>{markdown_fragment(draft['answer_markdown'])}</section>
{('<section><h2>Figure</h2>' + ''.join(figure_blocks) + '</section>') if figure_blocks else ''}
<section><h2>根拠ファイル</h2><ul>{sources}</ul></section>
<section><h2>制約・留意点</h2><ul>{limitations}</ul></section>{next_round}
<div class="freeze">このreportは既存結果のread-only解説であり、State/DAGには登録されていません。</div></main></body></html>
"""


def finalize(args: argparse.Namespace) -> dict[str, Any]:
    request_dir, run_root, request = resolve_request_dir(args.request_dir)
    if request.get("status") != "prepared":
        raise RuntimeError(f"Request is not in prepared status: {request.get('status')}")
    control = load_json(Path(request["control_path"]))
    snapshot = load_json(Path(request["snapshot_path"]))
    errors = frozen_state_errors(control, snapshot)
    if errors:
        raise RuntimeError("Run ceased to be frozen; finalize refused: " + "; ".join(errors))
    problems = verify_source_manifest(request_dir, run_root)
    if problems:
        raise RuntimeError("Frozen sources changed after prepare: " + json.dumps(problems, ensure_ascii=False))
    drift = inventory_drift(request_dir, run_root)
    if drift:
        raise RuntimeError("Run files changed after prepare; finalize refused: " + json.dumps(drift[:50], ensure_ascii=False))
    manifest = load_json(request_dir / "source_manifest.json")
    captured = {entry["path"] for entry in manifest.get("sources") or []}
    draft = load_json(request_dir / "response_draft.json")
    validate_draft(draft, captured)

    figures_dir = request_dir / "figures"
    figures = []
    if draft["figures"]:
        figures_dir.mkdir(exist_ok=True)
    for spec in draft["figures"]:
        file_name = f"{spec['figure_id']}.svg"
        atomic_write_text(figures_dir / file_name, render_figure_svg(spec))
        figures.append({**spec, "file_name": file_name})

    request["status"] = "completed"
    request["finalized_at"] = utc_now()
    markdown = markdown_report(request, draft, figures)
    html_text = html_report(request, draft, figures, request_dir)
    atomic_write_text(request_dir / "response.md", markdown)
    atomic_write_text(request_dir / "response.html", html_text)
    if draft["suggested_next_round_prompt"]:
        atomic_write_text(request_dir / "next_round_prompt.md", draft["suggested_next_round_prompt"].strip() + "\n")

    problems = verify_source_manifest(request_dir, run_root)
    if problems:
        raise RuntimeError("Frozen sources changed during rendering: " + json.dumps(problems, ensure_ascii=False))
    drift = inventory_drift(request_dir, run_root)
    if drift:
        raise RuntimeError("Run files changed during rendering: " + json.dumps(drift[:50], ensure_ascii=False))
    output_paths = [request_dir / "response.md", request_dir / "response.html"]
    output_paths.extend(figures_dir / item["file_name"] for item in figures)
    if (request_dir / "next_round_prompt.md").is_file():
        output_paths.append(request_dir / "next_round_prompt.md")
    request["outputs"] = {
        path.relative_to(request_dir).as_posix(): {"sha256": sha256_file(path), "bytes": path.stat().st_size}
        for path in output_paths
    }
    write_json(request_dir / "request.json", request)
    return {
        "status": "completed",
        "request_id": request_dir.name,
        "response_markdown": str(request_dir / "response.md"),
        "response_html": str(request_dir / "response.html"),
        "figure_count": len(figures),
        "state_mutated": False,
    }


def verify(args: argparse.Namespace) -> dict[str, Any]:
    request_dir, run_root, request = resolve_request_dir(args.request_dir)
    output_problems = []
    for relative, expected in (request.get("outputs") or {}).items():
        path = (request_dir / relative).resolve()
        if not is_relative_to(path, request_dir) or not path.is_file():
            output_problems.append({"path": relative, "problem": "missing or outside request directory"})
        elif sha256_file(path) != expected.get("sha256"):
            output_problems.append({"path": relative, "problem": "output hash changed"})
    source_problems = verify_source_manifest(request_dir, run_root)
    run_drift = inventory_drift(request_dir, run_root)
    return {
        "status": "pass" if request.get("status") == "completed" and not output_problems else "fail",
        "request_id": request_dir.name,
        "request_status": request.get("status"),
        "outputs_valid": not output_problems,
        "output_problems": output_problems,
        "sources_unchanged_since_prepare": not source_problems,
        "source_drift": source_problems,
        "run_files_unchanged_since_prepare": not run_drift,
        "run_file_drift": run_drift[:100],
        "note": "Later Rounds may legitimately change live Runtime files; request-local snapshots remain the reporting source.",
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Explain and visualize frozen CONDUCTOR results without mutating analysis State.")
    subparsers = root.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare", help="Create a frozen concierge request workspace.")
    prepare_parser.add_argument("--run-root", required=True, help=f"Explicit path to a completed CONDUCTOR {VERSION} Run Root.")
    request_group = prepare_parser.add_mutually_exclusive_group(required=True)
    request_group.add_argument("--request", help="Human question or explanation request.")
    request_group.add_argument("--request-file", help="UTF-8 file containing the human request.")
    prepare_parser.add_argument("--focus-id", action="append", help="Insight/Next Action/Node/Cluster/Operator result reference; repeatable.")
    prepare_parser.add_argument("--explicit-request", action="store_true", help="Confirm that a human explicitly requested this read-only action.")
    prepare_parser.set_defaults(handler=prepare)

    source_parser = subparsers.add_parser("add-source", help="Capture source hashes before reading additional artifacts.")
    source_parser.add_argument("--request-dir", required=True)
    source_parser.add_argument("--source", action="append", required=True, help="Artifact path; repeatable.")
    source_parser.set_defaults(handler=add_source)

    helper_parser = subparsers.add_parser("run-helper", help="Run a request-local Python helper in an isolated scratch directory.")
    helper_parser.add_argument("--request-dir", required=True)
    helper_parser.add_argument("--script", required=True, help="Python file below request_dir/scratch/.")
    helper_parser.add_argument("--timeout-seconds", type=int, default=1800)
    helper_parser.add_argument("script_args", nargs=argparse.REMAINDER)
    helper_parser.set_defaults(handler=run_helper)

    finalize_parser = subparsers.add_parser("finalize", help="Validate the draft and render Markdown/HTML/Figures.")
    finalize_parser.add_argument("--request-dir", required=True)
    finalize_parser.set_defaults(handler=finalize)

    verify_parser = subparsers.add_parser("verify", help="Verify a finalized concierge request and report later source drift.")
    verify_parser.add_argument("--request-dir", required=True)
    verify_parser.set_defaults(handler=verify)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        result = args.handler(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status") not in {"fail", "error"} else 1
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
