from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


REQUEST_SCHEMA_VERSION = "1.0.0"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require(mapping: dict[str, Any], key: str, context: str) -> Any:
    value = mapping.get(key)
    if value is None or value == "":
        raise ValueError(f"Execution Request is missing {context}.{key}")
    return value


def _inputs(request: dict[str, Any], role: str) -> list[dict[str, Any]]:
    return [item for item in request.get("inputs", []) if item.get("role") == role]


def _one(request: dict[str, Any], role: str, required: bool = True) -> dict[str, Any] | None:
    matches = _inputs(request, role)
    if len(matches) > 1:
        raise ValueError(f"Execution Request has more than one {role!r} input")
    if required and not matches:
        raise ValueError(f"Execution Request is missing required input role: {role}")
    return matches[0] if matches else None


def _path(item: dict[str, Any], key: str = "path") -> str:
    raw = _require(item, key, "input")
    path = Path(str(raw)).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Execution Request input does not exist: {path}")
    return str(path)


def _append_value(arguments: list[str], option: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, bool):
        if value:
            arguments.append(option)
    elif isinstance(value, (str, int, float)):
        arguments.extend([option, str(value)])
    else:
        raise ValueError(f"Unsupported scalar parameter for {option}: {type(value).__name__}")


def _common_arguments(request: dict[str, Any]) -> list[str]:
    identity = request["identity"]
    output = request["output"]
    arguments = [
        "--conductor",
        "--project", str(_require(identity, "project", "identity")),
        "--run-id", str(_require(identity, "run_id", "identity")),
        "--round-id", str(_require(identity, "round_id", "identity")),
        "--node-id", str(_require(identity, "node_id", "identity")),
        "--attempt-id", str(_require(identity, "attempt_id", "identity")),
        "--output-dir", str(Path(str(_require(output, "directory", "output"))).resolve()),
    ]
    if bool(output.get("overwrite", False)):
        arguments.append("--overwrite")
    return arguments


def _columns(arguments: list[str], request: dict[str, Any], *, endpoint: bool, smiles: bool) -> None:
    columns = request.get("columns", {})
    if columns.get("compound_id"):
        arguments += ["--id-column", str(columns["compound_id"])]
    if smiles and columns.get("smiles"):
        arguments += ["--smiles-column", str(columns["smiles"])]
    if endpoint:
        arguments += ["--property-column", str(_require(columns, "endpoint", "columns"))]
        higher = request.get("endpoint", {}).get("higher_is_better")
        if not isinstance(higher, bool):
            raise ValueError("Execution Request endpoint.higher_is_better must be Boolean")
        arguments.append("--higher-is-better" if higher else "--no-higher-is-better")


def _parameters(arguments: list[str], request: dict[str, Any], excluded: set[str] | None = None) -> None:
    excluded = set(excluded or set())
    excluded.update(request.get("resources", {}).get("skill_options", {}))
    for key, value in sorted(request.get("parameters", {}).items()):
        if key in excluded or value is None:
            continue
        option = "--" + key.replace("_", "-")
        if isinstance(value, list):
            for item in value:
                _append_value(arguments, option, item)
        else:
            _append_value(arguments, option, value)


def _profile(capability: dict[str, Any]) -> str:
    contract = capability.get("conductor_request", {})
    adapter = contract.get("adapter")
    if not adapter:
        raise ValueError(
            f"Capability {capability.get('capability_id')} has no explicit conductor_request.adapter"
        )
    return str(adapter)


def _resource_arguments(arguments: list[str], request: dict[str, Any]) -> None:
    for key, value in sorted(request.get("resources", {}).get("skill_options", {}).items()):
        _append_value(arguments, "--" + key.replace("_", "-"), value)


def _description(request: dict[str, Any], capability: dict[str, Any]) -> list[str]:
    arguments = _common_arguments(request)
    arguments += ["--input", _path(_one(request, "dataset"))]
    _columns(arguments, request, endpoint=False, smiles=True)
    _resource_arguments(arguments, request)
    _parameters(arguments, request)
    return arguments


def _structure_clustering(request: dict[str, Any], capability: dict[str, Any]) -> list[str]:
    arguments = _common_arguments(request)
    arguments += ["--input", _path(_one(request, "dataset"))]
    _columns(arguments, request, endpoint=False, smiles=True)
    _parameters(arguments, request)
    return arguments


def _vector_clustering(request: dict[str, Any], capability: dict[str, Any]) -> list[str]:
    arguments = _common_arguments(request)
    description = _one(request, "description")
    arguments += ["--input", _path(description)]
    if not description.get("result_path"):
        raise ValueError("Vector Clustering requires description.result_path in the Execution Request")
    arguments += ["--description-result", _path(description, "result_path")]
    if description.get("source_capability_id"):
        arguments += ["--input-representation", str(description["source_capability_id"])]
    # Every Description Skill normalizes its payload identifier to
    # ``compound_id`` even when the Run input used CHEMBL_ID or another name.
    # Passing the original dataset ID column here makes every vector Clustering
    # fail for non-default input schemas.
    arguments += ["--id-column", "compound_id"]
    _parameters(arguments, request, {"input_representation"})
    return arguments


ADAPTERS = {
    "description": _description,
    "structure_clustering": _structure_clustering,
    "vector_clustering": _vector_clustering,
}


def load_request(path: str | Path, capability: dict[str, Any]) -> dict[str, Any]:
    request_path = Path(path).resolve()
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if request.get("schema_version") != REQUEST_SCHEMA_VERSION:
        raise ValueError(f"Unsupported Execution Request schema_version: {request.get('schema_version')}")
    identity = request.get("identity")
    if not isinstance(identity, dict):
        raise ValueError("Execution Request identity must be an object")
    if identity.get("capability_id") != capability.get("capability_id"):
        raise ValueError("Execution Request capability_id does not match this Skill")
    if identity.get("skill_name") != capability.get("skill_name"):
        raise ValueError("Execution Request skill_name does not match this Skill")
    if not isinstance(request.get("inputs"), list):
        raise ValueError("Execution Request inputs must be an array")
    if not isinstance(request.get("parameters"), dict):
        raise ValueError("Execution Request parameters must be an object")
    required_roles = set(capability.get("conductor_request", {}).get("required_input_roles", []))
    supplied_roles = {str(item.get("role")) for item in request["inputs"] if isinstance(item, dict)}
    missing_roles = sorted(required_roles - supplied_roles)
    if missing_roles:
        raise ValueError(
            "Execution Request is missing required input role(s): " + ", ".join(missing_roles)
        )
    for index, item in enumerate(request["inputs"]):
        if not isinstance(item, dict):
            raise ValueError(f"Execution Request inputs[{index}] must be an object")
        for path_key, hash_key in (("path", "sha256"), ("result_path", "result_sha256")):
            raw = item.get(path_key)
            if not raw:
                continue
            input_path = Path(str(raw)).resolve()
            if not input_path.is_file():
                raise FileNotFoundError(f"Execution Request inputs[{index}].{path_key} does not exist: {input_path}")
            declared = item.get(hash_key)
            if not declared:
                raise ValueError(f"Execution Request inputs[{index}].{hash_key} is required for {path_key}")
            if str(declared) != _sha256(input_path):
                raise ValueError(
                    f"Execution Request inputs[{index}].{path_key} hash mismatch; "
                    "the upstream artifact changed after planning"
                )
    return request


def request_to_cli(path: str | Path, capability: dict[str, Any]) -> list[str]:
    request = load_request(path, capability)
    profile = _profile(capability)
    if profile == "passthrough":
        return ["--request", str(Path(path).resolve())]
    adapter = ADAPTERS.get(profile)
    if not adapter:
        raise ValueError(f"Unsupported conductor_request adapter: {profile}")
    return adapter(request, capability)


def canonical_request_hash(request: dict[str, Any]) -> str:
    encoded = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
