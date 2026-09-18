"""Create a hash-bound receipt after an operator has completed a preflight."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _implementation_fingerprint(project_root: Path) -> str:
    roots = [
        project_root / ".claude" / "skills",
        project_root / "CONDUCTOR_modules" / "tools",
        project_root / "CONDUCTOR_modules" / "pipeline",
        project_root / "CONDUCTOR_modules" / "schemas",
    ]
    allowed = {".py", ".json", ".toml", ".lock", ".md"}
    excluded = {
        ".pixi", "cache", "pixi-home", "__pycache__", ".pytest_cache",
        "config", "data", "state", "tmp",
    }
    rows: list[tuple[str, str]] = []
    for root in roots:
        for directory, directory_names, file_names in os.walk(root):
            directory_names[:] = [name for name in directory_names if name not in excluded]
            parent = Path(directory)
            for name in file_names:
                path = parent / name
                if path.suffix.lower() in allowed:
                    rows.append((path.relative_to(project_root).as_posix(), _file_sha256(path)))
    defaults = project_root / "CONDUCTOR_modules" / "config" / "defaults.yaml"
    if defaults.is_file():
        rows.append((defaults.relative_to(project_root).as_posix(), _file_sha256(defaults)))
    return _canonical_hash(sorted(rows))


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Record a passed CONDUCTOR 0.2.1 preflight as a bound receipt"
    )
    parser.add_argument("--check-id", choices=("3.2A", "3.2B", "3.3"), required=True)
    parser.add_argument("--run-spec", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--checked-by", required=True)
    parser.add_argument("--evidence-summary", required=True)
    args = parser.parse_args()
    try:
        spec_path = Path(args.run_spec).resolve()
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        required = {
            "schema_version", "project_root", "program_name", "input_csv",
            "endpoint_registry", "endpoint_id", "config_path",
            "provider_config_path", "run_root", "workers",
        }
        missing = required - set(spec)
        if missing or spec.get("schema_version") != "0.2.1":
            raise ValueError(f"Run Spec is invalid; missing={sorted(missing)}")
        project_root = Path(spec["project_root"]).resolve()
        schemas = project_root / "CONDUCTOR_modules" / "schemas"
        if not (schemas / "run_spec.schema.json").is_file():
            raise FileNotFoundError("Run Spec schema is missing from project_root")
        scope = {
            "project_root": str(project_root),
            "program_name": spec["program_name"],
            "input_csv": str(Path(spec["input_csv"]).resolve()),
            "endpoint_registry": str(Path(spec["endpoint_registry"]).resolve()),
            "endpoint_id": spec["endpoint_id"],
            "config_path": str(Path(spec["config_path"]).resolve()),
            "provider_config_path": str(Path(spec["provider_config_path"]).resolve()),
            "run_root": str(Path(spec["run_root"]).resolve()),
            "workers": int(spec["workers"]),
        }
        hashes = {
            "input_csv": _file_sha256(Path(spec["input_csv"]).resolve()),
            "endpoint_registry": _file_sha256(Path(spec["endpoint_registry"]).resolve()),
            "config_path": _file_sha256(Path(spec["config_path"]).resolve()),
            "provider_config_path": _file_sha256(Path(spec["provider_config_path"]).resolve()),
            "run_spec": _file_sha256(spec_path),
        }
        affinity = (
            len(os.sched_getaffinity(0))
            if hasattr(os, "sched_getaffinity")
            else (os.cpu_count() or 1)
        )
        receipt = {
            "schema_version": "0.2.1",
            "check_id": args.check_id,
            "status": "passed",
            "run_scope": scope,
            "input_hashes": hashes,
            "blueprint_sha256": _file_sha256(
                project_root
                / "CONDUCTOR_modules"
                / "pipeline"
                / "production_pipeline.v0.2.1.json"
            ),
            "implementation_sha256": _implementation_fingerprint(project_root),
            "code_version": "0.2.1",
            "machine": {"hostname": socket.gethostname(), "cpu_affinity": affinity},
            "completed_at": _now(),
            "checked_by": args.checked_by,
            "evidence_summary": args.evidence_summary,
        }
        output = Path(args.output)
        if not output.is_absolute():
            raise ValueError("--output must be an absolute path")
        if output.exists():
            raise FileExistsError(f"Receipt already exists: {output}")
        _atomic_write_json(output.resolve(), receipt)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"status": "succeeded", "receipt": str(output.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
