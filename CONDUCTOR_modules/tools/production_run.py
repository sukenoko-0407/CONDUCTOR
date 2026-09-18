"""Compile and execute the canonical CONDUCTOR 0.2.1 production DAG.

This module is the only supported compiler for the 3.4A new-Database route.
It intentionally consumes a small Run Spec instead of discovering Skill
contracts or asking an agent to author Execution Requests at run time.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import Any, Self

import yaml

from conductor_stat_core import atomic_write_json, file_sha256, validate_instance


SCHEMA_VERSION = "0.2.1"
EXPECTED_RECEIPTS = {"3.2A", "3.2B", "3.3"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _local_cpu_affinity() -> int:
    return (
        len(os.sched_getaffinity(0))
        if hasattr(os, "sched_getaffinity")
        else (os.cpu_count() or 1)
    )


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def implementation_fingerprint(project_root: Path) -> str:
    """Hash executable contracts while skipping machine-local environments."""
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
            directory_names[:] = [
                name for name in directory_names if name not in excluded
            ]
            parent = Path(directory)
            for name in file_names:
                path = parent / name
                if path.suffix.lower() in allowed:
                    rows.append(
                        (path.relative_to(project_root).as_posix(), file_sha256(path))
                    )
    defaults = project_root / "CONDUCTOR_modules" / "config" / "defaults.yaml"
    if defaults.is_file():
        rows.append((defaults.relative_to(project_root).as_posix(), file_sha256(defaults)))
    return _canonical_hash(sorted(rows))


def _absolute_file(value: str, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{label} must be an absolute path: {value}")
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} does not exist: {path}")
    return path


def _absolute_path(value: str, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{label} must be an absolute path: {value}")
    return path.resolve()


def _scope(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_root": str(Path(spec["project_root"]).resolve()),
        "program_name": spec["program_name"],
        "input_csv": str(Path(spec["input_csv"]).resolve()),
        "endpoint_registry": str(Path(spec["endpoint_registry"]).resolve()),
        "endpoint_id": spec["endpoint_id"],
        "config_path": str(Path(spec["config_path"]).resolve()),
        "provider_config_path": str(Path(spec["provider_config_path"]).resolve()),
        "run_root": str(Path(spec["run_root"]).resolve()),
        "workers": int(spec["workers"]),
    }


def _input_hashes(spec_path: Path, spec: dict[str, Any]) -> dict[str, str]:
    return {
        "input_csv": file_sha256(Path(spec["input_csv"]).resolve()),
        "endpoint_registry": file_sha256(Path(spec["endpoint_registry"]).resolve()),
        "config_path": file_sha256(Path(spec["config_path"]).resolve()),
        "provider_config_path": file_sha256(
            Path(spec["provider_config_path"]).resolve()
        ),
        "run_spec": file_sha256(spec_path),
    }


def load_run_spec(spec_path: Path) -> tuple[dict[str, Any], dict[str, Path]]:
    spec_path = spec_path.resolve()
    project_root_hint = None
    try:
        payload = json.loads(spec_path.read_text(encoding="utf-8"))
        project_root_hint = Path(str(payload.get("project_root", "")))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"Run Spec is not readable JSON: {spec_path}: {exc}") from exc
    if not project_root_hint.is_absolute():
        raise ValueError("project_root must be an absolute path")
    project_root = project_root_hint.resolve()
    schema_dir = project_root / "CONDUCTOR_modules" / "schemas"
    validate_instance(payload, schema_dir / "run_spec.schema.json")

    paths = {
        "spec": spec_path,
        "project_root": project_root,
        "input_csv": _absolute_file(payload["input_csv"], "input_csv"),
        "endpoint_registry": _absolute_file(
            payload["endpoint_registry"], "endpoint_registry"
        ),
        "config_path": _absolute_file(payload["config_path"], "config_path"),
        "provider_config_path": _absolute_file(
            payload["provider_config_path"], "provider_config_path"
        ),
        "run_root": _absolute_path(payload["run_root"], "run_root"),
        "blueprint": project_root
        / "CONDUCTOR_modules"
        / "pipeline"
        / "production_pipeline.v0.2.1.json",
        "schema_dir": schema_dir,
    }
    if not paths["blueprint"].is_file():
        raise FileNotFoundError(f"Canonical pipeline blueprint is missing: {paths['blueprint']}")
    if not (project_root / ".claude" / "skills" / "cs-runtime").is_dir():
        raise FileNotFoundError(f"CONDUCTOR project root is incomplete: {project_root}")
    for receipt in payload["preflight_receipts"]:
        _absolute_file(receipt, "preflight_receipt")
    return payload, paths


def _validate_config(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or config.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Resolved config must be a complete 0.2.1 configuration")
    llm = config.get("llm")
    if not isinstance(llm, dict) or not str(llm.get("command", "")).strip():
        raise ValueError("Resolved config must contain a non-empty llm.command")
    return config


def _freeze_config(
    source: Path, provider_source: Path, destination: Path, provider_destination: Path
) -> None:
    config = _validate_config(source)
    command = str(config["llm"]["command"])
    candidates = {
        str(provider_source),
        provider_source.as_posix(),
    }
    matched = [candidate for candidate in candidates if candidate in command]
    if not matched:
        raise ValueError(
            "llm.command must reference provider_config_path by absolute path so it can be frozen"
        )
    for candidate in sorted(matched, key=len, reverse=True):
        command = command.replace(candidate, str(provider_destination))
    config["llm"]["command"] = command
    destination.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )


def validate_preflight_receipts(
    spec_path: Path, spec: dict[str, Any], paths: dict[str, Path]
) -> list[dict[str, Any]]:
    expected_scope = _scope(spec)
    expected_hashes = _input_hashes(spec_path, spec)
    blueprint_hash = file_sha256(paths["blueprint"])
    implementation_hash = implementation_fingerprint(paths["project_root"])
    hostname = socket.gethostname()
    affinity = _local_cpu_affinity()
    receipts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in spec["preflight_receipts"]:
        receipt_path = Path(value).resolve()
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        validate_instance(
            receipt, paths["schema_dir"] / "preflight_receipt.schema.json"
        )
        check_id = str(receipt["check_id"])
        if check_id in seen:
            raise ValueError(f"Duplicate preflight receipt: {check_id}")
        seen.add(check_id)
        if receipt["run_scope"] != expected_scope:
            raise ValueError(f"Preflight scope mismatch: {check_id}")
        if receipt["input_hashes"] != expected_hashes:
            raise ValueError(f"Preflight input hash mismatch: {check_id}")
        if receipt["blueprint_sha256"] != blueprint_hash:
            raise ValueError(f"Preflight blueprint hash mismatch: {check_id}")
        if receipt["implementation_sha256"] != implementation_hash:
            raise ValueError(f"Preflight implementation hash mismatch: {check_id}")
        if receipt["machine"]["hostname"] != hostname:
            raise ValueError(
                f"Preflight machine mismatch for {check_id}: "
                f"{receipt['machine']['hostname']} != {hostname}"
            )
        if int(receipt["machine"]["cpu_affinity"]) < int(spec["workers"]):
            raise ValueError(f"Preflight CPU affinity is insufficient: {check_id}")
        receipts.append(receipt)
    if seen != EXPECTED_RECEIPTS:
        raise ValueError(
            f"Required preflight receipts are {sorted(EXPECTED_RECEIPTS)}; got {sorted(seen)}"
        )
    if int(spec["workers"]) > affinity:
        raise ValueError(
            f"workers={spec['workers']} exceed current CPU affinity={affinity}"
        )
    return receipts


def _derive_run_id(
    spec: dict[str, Any], spec_path: Path, paths: dict[str, Path]
) -> str:
    if spec.get("run_id"):
        return str(spec["run_id"])
    identity = {
        "scope": _scope(spec),
        "input_hashes": _input_hashes(spec_path, spec),
        "blueprint_sha256": file_sha256(paths["blueprint"]),
        "implementation_sha256": implementation_fingerprint(paths["project_root"]),
        "mode": spec["mode"],
    }
    return f"RUN-{_canonical_hash(identity)[:20].upper()}"


def _expand(value: Any, values: dict[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        key = value[1:]
        if key not in values:
            raise KeyError(f"Unknown blueprint value: {value}")
        return values[key]
    if isinstance(value, list):
        return [_expand(item, values) for item in value]
    if isinstance(value, dict):
        return {key: _expand(item, values) for key, item in value.items()}
    return value


def _resolve_launch(project_root: Path, node: dict[str, Any]) -> Path:
    if node.get("launch") == "canonical_description_node":
        result = project_root / "CONDUCTOR_modules" / "tools" / "description_node.py"
    else:
        result = (
            project_root
            / ".claude"
            / "skills"
            / str(node["skill_name"])
            / "scripts"
            / "launch.py"
        )
    result = result.resolve()
    if not result.is_file():
        raise FileNotFoundError(f"Tracked node launcher is missing: {result}")
    return result


def _validate_blueprint_contracts(
    blueprint: dict[str, Any], project_root: Path
) -> None:
    nodes = blueprint.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("Production blueprint must contain nodes")
    by_id = {str(node.get("node_id")): node for node in nodes}
    if len(by_id) != len(nodes) or "None" in by_id:
        raise ValueError("Production blueprint node_id values must be unique")
    outputs: dict[str, set[str]] = {}
    inputs: dict[str, set[str]] = {}
    for node_id, node in by_id.items():
        dependencies = {str(value) for value in node.get("dependencies", [])}
        unknown = dependencies - set(by_id)
        if unknown:
            raise ValueError(f"Blueprint node {node_id} has unknown dependencies: {sorted(unknown)}")
        skill_name = str(node["skill_name"])
        if node.get("launch") == "canonical_description_node":
            outputs[node_id] = {"feature_spaces"}
            inputs[node_id] = {"dataset", "compounds"}
        else:
            capability_path = (
                project_root / ".claude" / "skills" / skill_name / "capability.json"
            )
            capability = json.loads(capability_path.read_text(encoding="utf-8"))
            outputs[node_id] = {str(value) for value in capability.get("output_roles", [])}
            inputs[node_id] = {
                str(value)
                for value in capability.get("input_roles", [])
                + capability.get("optional_input_roles", [])
            }
        for item in node.get("inputs", []):
            role = str(item["role"])
            if role not in inputs[node_id]:
                raise ValueError(
                    f"Blueprint input role {role!r} is not declared by {skill_name}: {node_id}"
                )
            reference = str(item["ref"])
            if reference.startswith("external://"):
                if reference.removeprefix("external://") not in {
                    "input_csv", "endpoint_registry"
                }:
                    raise ValueError(f"Unknown external blueprint reference: {reference}")
                continue
            if reference.startswith("manifest://"):
                producer = reference.removeprefix("manifest://")
            elif reference.startswith("node://"):
                producer, producer_role = reference.removeprefix("node://").split("/", 1)
                if producer_role not in outputs.get(producer, set()):
                    raise ValueError(
                        f"Blueprint role {producer_role!r} is not produced by {producer}"
                    )
            else:
                raise ValueError(f"Unsupported blueprint reference: {reference}")
            if producer not in dependencies:
                raise ValueError(
                    f"Blueprint reference {reference} is not a declared dependency of {node_id}"
                )
    remaining = set(by_id)
    while remaining:
        ready = {
            node_id
            for node_id in remaining
            if not set(by_id[node_id].get("dependencies", [])).intersection(remaining)
        }
        if not ready:
            raise ValueError(f"Production blueprint contains a dependency cycle: {sorted(remaining)}")
        remaining -= ready


def _compile_payloads(
    spec: dict[str, Any], paths: dict[str, Path], run_id: str
) -> tuple[list[tuple[str, dict[str, Any]]], dict[str, Any], dict[str, Any]]:
    blueprint = json.loads(paths["blueprint"].read_text(encoding="utf-8"))
    if blueprint.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Production blueprint schema_version must be 0.2.1")
    _validate_blueprint_contracts(blueprint, paths["project_root"])
    values = {
        "id_column": spec["id_column"],
        "smiles_column": spec["smiles_column"],
        "program_name": spec["program_name"],
        "description_parameters": spec.get("description_parameters", {}),
        "run_root": str(paths["run_root"]),
    }
    frozen_config = paths["run_root"] / "control" / "resolved_config.yaml"
    requests: list[tuple[str, dict[str, Any]]] = []
    plan_nodes: list[dict[str, Any]] = []
    seed = int(spec.get("random_seed", 20260916))
    external = {
        "input_csv": paths["input_csv"],
        "endpoint_registry": paths["endpoint_registry"],
    }
    for node in blueprint["nodes"]:
        node_id = str(node["node_id"])
        inputs: list[dict[str, Any]] = []
        for item in node.get("inputs", []):
            reference = str(item["ref"])
            if reference.startswith("external://"):
                key = reference.removeprefix("external://")
                source = external[key]
                inputs.append({
                    "role": item["role"],
                    "path": str(source),
                    "sha256": file_sha256(source),
                    "producer_manifest": None,
                })
            else:
                inputs.append({
                    "role": item["role"],
                    "path": reference,
                    "sha256": hashlib.sha256(reference.encode("utf-8")).hexdigest(),
                    "producer_manifest": None,
                })
        parameters = {"operation": node["operation"]}
        parameters.update(_expand(node.get("parameters", {}), values))
        request = {
            "schema_version": SCHEMA_VERSION,
            "identity": {
                "project": spec["project"],
                "run_id": run_id,
                "phase_id": node["phase_id"],
                "node_id": node_id,
                "attempt_id": "TEMPLATE",
                "skill_name": node["skill_name"],
            },
            "endpoint_id": spec["endpoint_id"],
            "config_path": str(frozen_config),
            "random_seed": seed,
            "inputs": inputs,
            "parameters": parameters,
            "resources": {
                "workers": int(spec["workers"]),
                "memory_mb": int(spec["memory_mb"]),
            },
        }
        validate_instance(request, paths["schema_dir"] / "execution_request.schema.json")
        request_path = paths["run_root"] / "control" / "requests" / f"{node_id}.json"
        plan_nodes.append({
            "node_id": node_id,
            "phase_id": node["phase_id"],
            "skill_name": node["skill_name"],
            "dependencies": node.get("dependencies", []),
            "request_template": str(request_path),
            "launch_path": str(_resolve_launch(paths["project_root"], node)),
            "output_directory": str(paths["run_root"] / "nodes" / node_id),
        })
        requests.append((node_id, request))
    plan = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "code_version": SCHEMA_VERSION,
        "blueprint_sha256": file_sha256(paths["blueprint"]),
        "implementation_sha256": implementation_fingerprint(paths["project_root"]),
        "nodes": plan_nodes,
    }
    validate_instance(plan, paths["schema_dir"] / "pipeline_plan.schema.json")
    return requests, plan, blueprint


@dataclass
class ExclusiveLock:
    path: Path
    payload: dict[str, Any]
    descriptor: int | None = None

    def __enter__(self) -> Self:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.descriptor = os.open(
                self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY
            )
        except FileExistsError as exc:
            owner = self.path.read_text(encoding="utf-8", errors="replace")
            raise RuntimeError(f"Active or stale CONDUCTOR lock: {self.path}: {owner}") from exc
        os.write(
            self.descriptor,
            json.dumps(self.payload, ensure_ascii=False, sort_keys=True).encode("utf-8"),
        )
        os.fsync(self.descriptor)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.descriptor is not None:
            os.close(self.descriptor)
            self.descriptor = None
        self.path.unlink(missing_ok=True)


def _locks(paths: dict[str, Path], spec: dict[str, Any], run_id: str) -> list[ExclusiveLock]:
    root = paths["project_root"] / ".conductor" / "locks"
    owner = {
        "run_id": run_id,
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "created_at": _utc_now(),
    }
    program_key = hashlib.sha256(spec["program_name"].encode("utf-8")).hexdigest()[:20]
    run_key = hashlib.sha256(str(paths["run_root"]).encode("utf-8")).hexdigest()[:20]
    return [
        ExclusiveLock(root / f"program-{program_key}.lock", owner),
        ExclusiveLock(root / f"run-{run_key}.lock", owner),
    ]


def _minimal_guards(spec: dict[str, Any], paths: dict[str, Path]) -> None:
    _validate_config(paths["config_path"])
    json.loads(paths["provider_config_path"].read_text(encoding="utf-8"))
    database_root = (
        paths["project_root"]
        / "data"
        / "description_database"
        / str(spec["program_name"])
    )
    if database_root.exists():
        raise FileExistsError(
            f"New-Database mode requires an absent Program Database path: {database_root}"
        )
    if paths["run_root"].exists():
        raise FileExistsError(f"Run root already exists: {paths['run_root']}")


def compile_run(spec_path: Path) -> dict[str, Any]:
    spec, paths = load_run_spec(spec_path)
    receipts = validate_preflight_receipts(paths["spec"], spec, paths)
    _minimal_guards(spec, paths)
    run_id = _derive_run_id(spec, paths["spec"], paths)
    requests, plan, _blueprint = _compile_payloads(spec, paths, run_id)

    paths["run_root"].mkdir(parents=True, exist_ok=False)
    control = paths["run_root"] / "control"
    (control / "requests").mkdir(parents=True, exist_ok=False)
    (control / "preflight_receipts").mkdir(parents=True, exist_ok=False)
    (paths["run_root"] / "nodes").mkdir(parents=True, exist_ok=False)
    frozen_provider = control / "provider_config.json"
    frozen_config = control / "resolved_config.yaml"
    shutil.copy2(paths["provider_config_path"], frozen_provider)
    _freeze_config(paths["config_path"], paths["provider_config_path"], frozen_config, frozen_provider)
    shutil.copy2(paths["spec"], control / "run_spec.json")
    shutil.copy2(paths["blueprint"], control / "production_pipeline.v0.2.1.json")
    for receipt_path in spec["preflight_receipts"]:
        source = Path(receipt_path).resolve()
        receipt = json.loads(source.read_text(encoding="utf-8"))
        shutil.copy2(source, control / "preflight_receipts" / f"{receipt['check_id']}.json")
    for node_id, request in requests:
        atomic_write_json(control / "requests" / f"{node_id}.json", request)
    plan_path = control / "pipeline_plan.json"
    atomic_write_json(plan_path, plan)
    coordinator_request = {
        "schema_version": SCHEMA_VERSION,
        "identity": {
            "project": spec["project"],
            "run_id": run_id,
            "phase_id": "P00",
            "node_id": "COORDINATOR",
            "attempt_id": "ATT-COORDINATOR",
            "skill_name": "cs-runtime",
        },
        "endpoint_id": spec["endpoint_id"],
        "config_path": str(control / "resolved_config.yaml"),
        "random_seed": int(spec.get("random_seed", 20260916)),
        "inputs": [{
            "role": "pipeline_plan",
            "path": str(plan_path),
            "sha256": file_sha256(plan_path),
            "producer_manifest": None,
        }],
        "parameters": {"operation": "coordinate", "lease_seconds": 3600},
        "resources": {
            "workers": int(spec["workers"]),
            "memory_mb": int(spec["memory_mb"]),
        },
    }
    validate_instance(
        coordinator_request, paths["schema_dir"] / "execution_request.schema.json"
    )
    coordinator_path = control / "coordinator_request.json"
    atomic_write_json(coordinator_path, coordinator_request)
    compilation = {
        "schema_version": SCHEMA_VERSION,
        "status": "compiled",
        "run_id": run_id,
        "compiled_at": _utc_now(),
        "node_count": len(requests),
        "workers": int(spec["workers"]),
        "run_spec_sha256": file_sha256(paths["spec"]),
        "source_config_sha256": file_sha256(paths["config_path"]),
        "frozen_config_sha256": file_sha256(frozen_config),
        "provider_config_sha256": file_sha256(frozen_provider),
        "blueprint_sha256": file_sha256(paths["blueprint"]),
        "implementation_sha256": implementation_fingerprint(paths["project_root"]),
        "preflight_checks": sorted(item["check_id"] for item in receipts),
        "pipeline_plan": str(plan_path),
        "coordinator_request": str(coordinator_path),
    }
    atomic_write_json(control / "compilation_manifest.json", compilation)
    return compilation


def execute_run(spec_path: Path, *, compile_only: bool = False) -> dict[str, Any]:
    spec, paths = load_run_spec(spec_path)
    run_id = _derive_run_id(spec, paths["spec"], paths)
    with ExitStack() as stack:
        for lock in _locks(paths, spec, run_id):
            stack.enter_context(lock)
        compilation = compile_run(paths["spec"])
        if compile_only:
            return compilation
        runtime_launch = (
            paths["project_root"]
            / ".claude"
            / "skills"
            / "cs-runtime"
            / "scripts"
            / "launch.py"
        ).resolve()
        completed = subprocess.run(
            [
                sys.executable,
                str(runtime_launch),
                "--request",
                compilation["coordinator_request"],
                "--output-dir",
                str(paths["run_root"]),
                "--workers",
                str(spec["workers"]),
            ],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        control = paths["run_root"] / "control"
        (control / "coordinator_stdout.txt").write_text(
            completed.stdout, encoding="utf-8", newline="\n"
        )
        (control / "coordinator_stderr.txt").write_text(
            completed.stderr, encoding="utf-8", newline="\n"
        )
        runtime_response: dict[str, Any] | None = None
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        if len(lines) == 1:
            try:
                parsed = json.loads(lines[0])
                if isinstance(parsed, dict):
                    runtime_response = parsed
            except json.JSONDecodeError:
                runtime_response = None
        if completed.returncode == 0 and runtime_response is None:
            summary_path = paths["run_root"] / "runtime_summary.json"
            if summary_path.is_file():
                parsed = json.loads(summary_path.read_text(encoding="utf-8"))
                if isinstance(parsed, dict):
                    runtime_response = parsed
        runtime_status = (
            str(runtime_response.get("status"))
            if completed.returncode == 0 and runtime_response is not None
            else "failed"
        )
        result = {
            **compilation,
            "status": runtime_status,
            "returncode": completed.returncode,
            "run_root": str(paths["run_root"]),
            "runtime_response": runtime_response,
        }
        return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile and execute the canonical CONDUCTOR 0.2.1 production DAG"
    )
    parser.add_argument("--run-spec", required=True)
    parser.add_argument("--compile-only", action="store_true")
    args = parser.parse_args()
    try:
        result = execute_run(Path(args.run_spec), compile_only=args.compile_only)
    except Exception as exc:
        print(
            json.dumps(
                {"schema_version": SCHEMA_VERSION, "status": "failed", "error": str(exc)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result["status"] in {"compiled", "succeeded", "needs_design_review"} else 4


if __name__ == "__main__":
    raise SystemExit(main())
