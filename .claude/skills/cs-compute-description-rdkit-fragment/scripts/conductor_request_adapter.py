from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


REQUEST_SCHEMA_VERSION = "1.0.0"


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


def _scope_arguments(arguments: list[str], request: dict[str, Any]) -> None:
    subject = request.get("subject", {})
    mode = subject.get("mode", "global")
    cli_mode = {
        "global": "global",
        "single_cluster": "within-cluster",
        "within-cluster": "within-cluster",
        "cluster_vs_cluster": "between-clusters",
        "between-clusters": "between-clusters",
    }.get(mode)
    if cli_mode:
        arguments += ["--scope-mode", cli_mode]
    target = subject.get("target_cluster_id") or request.get("parameters", {}).get("target_cluster")
    comparison = subject.get("comparison_cluster_id") or request.get("parameters", {}).get("comparison_cluster")
    if target:
        arguments += ["--target-cluster", str(target)]
    if comparison:
        arguments += ["--comparison-cluster", str(comparison)]
    if subject.get("compound_set_hash"):
        arguments += ["--scope-compound-set-hash", str(subject["compound_set_hash"])]


def _profile(capability: dict[str, Any]) -> str:
    contract = capability.get("conductor_request", {})
    if contract.get("adapter"):
        return str(contract["adapter"])
    stage = capability.get("stage")
    if stage == "description":
        return "description"
    if stage == "clustering":
        if capability.get("implementation", {}).get("algorithm") == "categorical":
            return "categorical_clustering"
        return "vector_clustering" if capability.get("family") == "description_vector" else "structure_clustering"
    if capability.get("capability_id") in {"A003", "A004"}:
        return "projection_operator"
    if capability.get("capability_id") == "A005":
        return "multidescription_operator"
    if capability.get("capability_id") == "A014":
        return "mmp_operator"
    return "standard_operator"


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


def _categorical_clustering(request: dict[str, Any], capability: dict[str, Any]) -> list[str]:
    arguments = _common_arguments(request)
    arguments += ["--input", _path(_one(request, "dataset"))]
    _columns(arguments, request, endpoint=False, smiles=False)
    _parameters(arguments, request)
    return arguments


def _vector_clustering(request: dict[str, Any], capability: dict[str, Any]) -> list[str]:
    arguments = _common_arguments(request)
    description = _one(request, "description")
    arguments += ["--input", _path(description)]
    if description.get("result_path"):
        arguments += ["--description-result", _path(description, "result_path")]
    if description.get("source_capability_id"):
        arguments += ["--input-representation", str(description["source_capability_id"])]
    _columns(arguments, request, endpoint=False, smiles=False)
    _parameters(arguments, request)
    return arguments


def _meta_clustering(request: dict[str, Any], capability: dict[str, Any]) -> list[str]:
    arguments = _common_arguments(request)
    arguments += ["--input", _path(_one(request, "cluster_membership_matrix"))]
    _columns(arguments, request, endpoint=False, smiles=False)
    _parameters(arguments, request)
    return arguments


def _operator_base(request: dict[str, Any], capability: dict[str, Any]) -> list[str]:
    arguments = _common_arguments(request)
    arguments += ["--input", _path(_one(request, "dataset"))]
    operator = str(capability.get("implementation", {}).get("operator", ""))
    _columns(arguments, request, endpoint=True, smiles=operator in {"pairwise_structure_similarity", "activity_cliff", "cluster_structural_diversity"})
    return arguments


def _source_provenance(arguments: list[str], item: dict[str, Any], option: str) -> None:
    if item.get("source_node_id"):
        arguments += [option, str(item["source_node_id"])]


def _standard_operator(request: dict[str, Any], capability: dict[str, Any]) -> list[str]:
    arguments = _operator_base(request, capability)
    description = _one(request, "description", required=False)
    clustering = _one(request, "clustering", required=False)
    if description:
        arguments += ["--description", _path(description)]
        _source_provenance(arguments, description, "--description-node-id")
        if description.get("source_capability_id"):
            arguments += ["--evaluation-representation", str(description["source_capability_id"])]
    if clustering:
        arguments += ["--membership", _path(clustering)]
        _source_provenance(arguments, clustering, "--clustering-node-id")
        if clustering.get("source_capability_id"):
            arguments += ["--clustering-representation", str(clustering["source_capability_id"])]
    _scope_arguments(arguments, request)
    _parameters(arguments, request, {"target_cluster", "comparison_cluster"})
    return arguments


def _projection_operator(request: dict[str, Any], capability: dict[str, Any]) -> list[str]:
    arguments = _operator_base(request, capability)
    description = _one(request, "description", required=False)
    clustering = _one(request, "clustering", required=False)
    projection = _one(request, "projection", required=False)
    if description:
        arguments += ["--description", _path(description)]
        if description.get("result_path"):
            arguments += ["--description-result", _path(description, "result_path")]
        _source_provenance(arguments, description, "--description-node-id")
        if description.get("source_capability_id"):
            arguments += ["--evaluation-representation", str(description["source_capability_id"])]
    if clustering:
        arguments += ["--membership", _path(clustering)]
        _source_provenance(arguments, clustering, "--clustering-node-id")
    if projection:
        arguments += ["--projection", _path(projection)]
        _source_provenance(arguments, projection, "--projection-node-id")
    _parameters(arguments, request)
    return arguments


def _multidescription_operator(request: dict[str, Any], capability: dict[str, Any]) -> list[str]:
    arguments = _operator_base(request, capability)
    descriptions = _inputs(request, "description")
    if not descriptions:
        raise ValueError("Multi-Description model requires Description inputs")
    for description in descriptions:
        source_capability = _require(description, "source_capability_id", "description input")
        arguments += ["--description", f"{source_capability}={_path(description)}"]
        _source_provenance(arguments, description, "--description-node-id")
    clustering = _one(request, "clustering", required=False)
    if clustering:
        arguments += ["--membership", _path(clustering)]
        _source_provenance(arguments, clustering, "--clustering-node-id")
    global_model = _one(request, "global_model", required=False)
    if global_model:
        arguments += ["--global-oof", _path(global_model)]
        _source_provenance(arguments, global_model, "--global-model-node-id")
    _parameters(arguments, request)
    return arguments


def _mmp_operator(request: dict[str, Any], capability: dict[str, Any]) -> list[str]:
    role = str(request.get("parameters", {}).get("role") or "global-build")
    if role not in {"global-build", "local-screen", "local-detail"}:
        raise ValueError(f"Unsupported MMP role: {role}")
    arguments = [role, *_common_arguments(request)]
    for item in request.get("inputs", []):
        if item.get("source_node_id"):
            arguments += ["--source-node-id", str(item["source_node_id"])]
    if role == "global-build":
        arguments += ["--input", _path(_one(request, "dataset"))]
        columns = request.get("columns", {})
        arguments += [
            "--id-column", str(_require(columns, "compound_id", "columns")),
            "--smiles-column", str(_require(columns, "smiles", "columns")),
            "--endpoint-column", str(_require(columns, "endpoint", "columns")),
            "--higher-is-better", "true" if request["endpoint"]["higher_is_better"] else "false",
            "--available-cpu-cores", str(request.get("resources", {}).get("node_cpu_cores", 1)),
        ]
        _parameters(arguments, request, {"role"})
        return arguments
    database = _one(request, "mmp_database")
    membership = _one(request, "cluster_membership_matrix")
    arguments += ["--mmp-database", _path(database), "--cluster-membership", _path(membership)]
    clusterings = _inputs(request, "clustering")
    if role == "local-screen":
        registry = _one(request, "cluster_registry", required=False)
        if registry:
            arguments += ["--cluster-registry", _path(registry)]
        for clustering in clusterings:
            _source_provenance(arguments, clustering, "--clustering-node-id")
    else:
        cluster_id = request.get("subject", {}).get("target_cluster_id") or request.get("parameters", {}).get("target_cluster")
        if not cluster_id:
            raise ValueError("MMP local-detail requires a target Cluster")
        arguments += ["--cluster-id", str(cluster_id)]
        if clusterings:
            _source_provenance(arguments, clusterings[0], "--clustering-node-id")
    return arguments


ADAPTERS = {
    "description": _description,
    "structure_clustering": _structure_clustering,
    "categorical_clustering": _categorical_clustering,
    "vector_clustering": _vector_clustering,
    "meta_clustering": _meta_clustering,
    "standard_operator": _standard_operator,
    "projection_operator": _projection_operator,
    "multidescription_operator": _multidescription_operator,
    "mmp_operator": _mmp_operator,
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
    return request


def request_to_cli(path: str | Path, capability: dict[str, Any]) -> list[str]:
    request = load_request(path, capability)
    profile = _profile(capability)
    adapter = ADAPTERS.get(profile)
    if not adapter:
        raise ValueError(f"Unsupported conductor_request adapter: {profile}")
    return adapter(request, capability)


def canonical_request_hash(request: dict[str, Any]) -> str:
    encoded = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
