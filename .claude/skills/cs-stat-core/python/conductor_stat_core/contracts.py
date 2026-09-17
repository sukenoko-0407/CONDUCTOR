from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

import jsonschema
import yaml


class SchemaValidationError(ValueError):
    """A versioned request, manifest, schema, or configuration is invalid."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_instance(instance: Any, schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.FormatChecker(),
    )
    errors = sorted(validator.iter_errors(instance), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        location = "/".join(str(value) for value in first.absolute_path) or "<root>"
        raise SchemaValidationError(f"Schema validation failed at {location}: {first.message}")


def _merge_known(base: dict[str, Any], overlay: Mapping[str, Any], prefix: str) -> None:
    for key, value in overlay.items():
        path = f"{prefix}.{key}" if prefix else key
        if key not in base:
            raise ValueError(f"Unknown configuration key: {path}")
        if isinstance(base[key], dict):
            if not isinstance(value, Mapping):
                raise ValueError(f"Configuration section must be an object: {path}")
            _merge_known(base[key], value, path)
        else:
            base[key] = value


def load_resolved_config(
    defaults_path: Path,
    project_path: Path | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    parsed = yaml.safe_load(defaults_path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("Default configuration must be an object")
    result = deepcopy(parsed)
    if project_path is not None:
        project = yaml.safe_load(project_path.read_text(encoding="utf-8"))
        if not isinstance(project, dict):
            raise ValueError("Project configuration must be an object")
        _merge_known(result, project, "")
    if overrides:
        _merge_known(result, overrides, "")
    if result.get("schema_version") != "0.2.1":
        raise ValueError("Resolved configuration schema_version must be 0.2.1")
    return result


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, allow_nan=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def prepare_output_directory(path: Path, overwrite: bool) -> Path:
    resolved = path.expanduser().resolve()
    if resolved.exists() and any(resolved.iterdir()) and not overwrite:
        raise FileExistsError(f"Output directory is not empty: {resolved}")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def safe_artifact_path(manifest_directory: Path, relative_path: str) -> Path:
    candidate = (manifest_directory / relative_path).resolve()
    root = manifest_directory.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"Artifact path escapes manifest directory: {relative_path}")
    return candidate


def verify_request_inputs(request: Mapping[str, Any]) -> None:
    for artifact in request.get("inputs", []):
        path = Path(str(artifact["path"])).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Input artifact does not exist: {path}")
        actual = file_sha256(path)
        if actual != artifact["sha256"]:
            raise ValueError(
                f"Input artifact hash mismatch for role {artifact['role']}: "
                f"expected {artifact['sha256']}, got {actual}"
            )
