from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any, Iterator


SKILL_DIR = Path(__file__).resolve().parents[1]
GROUP_MATRIX_SHARD_SIZE = 100_000
GROUP_REGISTRY_FIELDS = [
    "group_id", "group_label", "grouping_capability_id", "grouping_skill_name",
    "source_node_id", "source_description_id", "source_description_node_id",
    "source_grouping_node_ids", "compound_count", "activity_blind", "status", "membership_artifact",
    "definition_json", "created_at", "discard_reason", "discarded_at",
]


def find_workspace() -> Path:
    for candidate in [Path.cwd(), *Path.cwd().parents, SKILL_DIR, *SKILL_DIR.parents]:
        if (candidate / "catalog" / "catalog.json").exists() and (candidate / ".claude").exists():
            return candidate
    raise RuntimeError("CONDUCTOR workspace could not be located")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_id_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def default_exploration_state() -> dict[str, Any]:
    return {
        "policy_version": "1.0.0",
        "budget": {
            "configured": False,
            "max_iterations": None,
            "max_additional_nodes": None,
            "walltime_minutes": None,
            "seed": None,
            "configured_at": None,
        },
        "iterations": [],
        "ledger": [],
    }


def ensure_exploration_state(state: dict[str, Any]) -> dict[str, Any]:
    state.setdefault("interpretation_exploration", default_exploration_state())
    return state


@contextmanager
def state_lock(state_path: Path) -> Iterator[None]:
    lock_path = state_path.with_suffix(state_path.suffix + ".lock")
    descriptor: int | None = None
    try:
        descriptor = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(descriptor, f"pid={os.getpid()} created={utc_now()}".encode("utf-8"))
        yield
    except FileExistsError as exc:
        raise RuntimeError(f"State is locked by another writer: {lock_path}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
            lock_path.unlink(missing_ok=True)


def write_state(path: Path, value: dict[str, Any]) -> None:
    ensure_exploration_state(value)
    value["updated_at"] = utc_now()
    validate_state(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def validate_state(value: dict[str, Any]) -> None:
    try:
        import jsonschema
    except ImportError as exc:
        raise RuntimeError("jsonschema is required") from exc
    schema = read_json(SKILL_DIR / "schemas" / "state.schema.json")
    jsonschema.validate(value, schema)


def validate_event(value: dict[str, Any]) -> None:
    try:
        import jsonschema
    except ImportError as exc:
        raise RuntimeError("jsonschema is required") from exc
    schema = read_json(SKILL_DIR / "schemas" / "execution_event.schema.json")
    jsonschema.validate(value, schema)


def catalog_by_id(workspace: Path) -> dict[str, dict[str, Any]]:
    catalog = read_json(workspace / "catalog" / "catalog.json")
    return {entry["capability_id"]: entry for entry in catalog["capabilities"]}


def state_nodes(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {node["node_id"]: node for node in state["execution_graph"]["nodes"]}


def infer_run_id_column(header: list[str]) -> str:
    normalized = {"".join(character for character in name.lower() if character.isalnum()): name for name in header}
    for candidate in ["compound_id", "compoundid", "molecule_id", "moleculeid", "id", "chembl_id"]:
        key = "".join(character for character in candidate.lower() if character.isalnum())
        if key in normalized:
            return normalized[key]
    raise ValueError("CONDUCTOR input requires an explicit compound ID column")


def run_compound_ids(state: dict[str, Any]) -> list[str]:
    path = Path(state["run"]["input"])
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        id_column = state["run"].get("id_column") or infer_run_id_column(reader.fieldnames or [])
        identifiers = [str(row.get(id_column, "")).strip() for row in reader]
    if any(not identifier for identifier in identifiers):
        raise ValueError("Blank compound IDs are not allowed")
    if len(identifiers) != len(set(identifiers)):
        duplicates = sorted({identifier for identifier in identifiers if identifiers.count(identifier) > 1})[:10]
        raise ValueError(f"Duplicate compound IDs: {duplicates}")
    return identifiers


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv_rows(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def write_json_file(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def binding_node_ids(bindings: dict[str, Any], stage: str) -> list[str]:
    value = bindings.get(stage)
    if value is None:
        return []
    return [str(item) for item in value] if isinstance(value, list) else [str(value)]


def dependency_bindings(dependency_nodes: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[str]] = {}
    for dependency_node in dependency_nodes:
        grouped.setdefault(dependency_node["stage"], []).append(dependency_node["node_id"])
    return {stage: values[0] if len(values) == 1 else values for stage, values in grouped.items()}


def validate_dependency_contract(capability: dict[str, Any], dependency_nodes: list[dict[str, Any]]) -> None:
    required = capability.get("dependencies") or []
    required_stages = ["analysis" if item == "evidence" else item for item in required]
    allowed_stages = set(required_stages)
    if capability.get("stage") == "analysis" and any(
        mode != "global" for mode in capability.get("scope_support") or []
    ):
        allowed_stages.add("grouping")
    actual_stages = [node["stage"] for node in dependency_nodes]
    missing = sorted(stage for stage in set(required_stages) if stage not in actual_stages)
    unexpected = sorted(stage for stage in set(actual_stages) if stage not in allowed_stages)
    if missing:
        raise ValueError(f"{capability['capability_id']} requires dependency stage(s): {missing}")
    if unexpected:
        raise ValueError(f"{capability['capability_id']} does not accept dependency stage(s): {unexpected}")
    for stage in set(actual_stages):
        count = actual_stages.count(stage)
        multiple_allowed = (
            capability["stage"] == "interpretation" and stage == "analysis"
        ) or (
            capability.get("grouping_kind") == "meta" and stage == "grouping"
        )
        if count > 1 and not multiple_allowed:
            raise ValueError(f"{capability['capability_id']} accepts only one {stage} dependency")


def validate_analysis_scope_contract(
    capability: dict[str, Any],
    dependency_nodes: list[dict[str, Any]],
    parameters: dict[str, Any],
) -> None:
    if capability.get("stage") != "analysis":
        return
    scope_mode = str(parameters.get("scope_mode") or "global")
    if scope_mode not in set(capability.get("scope_support") or ["global"]):
        raise ValueError(f"{capability['capability_id']} does not support scope mode {scope_mode}")
    has_grouping_dependency = any(node["stage"] == "grouping" for node in dependency_nodes)
    generated_scope = bool(parameters.get("scope_compound_set_hash"))
    grouping_is_required = "grouping" in (capability.get("dependencies") or [])
    if scope_mode != "global" and not has_grouping_dependency and not generated_scope:
        raise ValueError("A local Operator node requires a Grouping dependency or an Orchestrator-generated explicit scope")
    if scope_mode == "global" and has_grouping_dependency and not grouping_is_required:
        raise ValueError("A global Operator node must not carry an unused optional Grouping dependency")


def group_index_paths(state_path: Path) -> tuple[Path, Path]:
    root = (state_path.parent / "grouping" / "group_index").resolve()
    return root, root / "group_registry.csv"


def update_group_index(
    state_path: Path,
    state: dict[str, Any],
    node: dict[str, Any],
    membership_path: Path,
    registry_path: Path,
) -> None:
    registry_json = read_json(registry_path)
    if not isinstance(registry_json, list):
        raise ValueError("group_registry.json must contain an array")
    incoming_ids = [str(item.get("group_id") or "") for item in registry_json]
    if any(not group_id for group_id in incoming_ids) or len(incoming_ids) != len(set(incoming_ids)):
        raise ValueError("Grouping artifact contains blank or duplicate Group IDs")
    membership_rows = read_csv_rows(membership_path)
    if membership_rows and not {"cluster_id", "compound_id", "membership_value"}.issubset(membership_rows[0]):
        raise ValueError("Grouping membership must contain cluster_id, compound_id, and membership_value")
    compound_ids = run_compound_ids(state)
    available_compounds = set(compound_ids)
    memberships: dict[str, set[str]] = {group_id: set() for group_id in incoming_ids}
    for row in membership_rows:
        group_id = str(row.get("cluster_id") or "").strip()
        compound_id = str(row.get("compound_id") or "").strip()
        if compound_id not in available_compounds:
            raise ValueError(f"Grouping membership contains an unknown compound ID: {compound_id}")
        try:
            active = float(row.get("membership_value") or 0) > 0
        except ValueError as exc:
            raise ValueError(f"Invalid membership_value for {compound_id}: {row.get('membership_value')}") from exc
        if active:
            if group_id not in memberships:
                raise ValueError(f"Membership references a Group ID absent from registry: {group_id}")
            memberships[group_id].add(compound_id)

    index_root, consolidated_registry_path = group_index_paths(state_path)
    registry_rows = read_csv_rows(consolidated_registry_path)
    registry_by_id = {row["group_id"]: row for row in registry_rows}
    for row in registry_rows:
        if row.get("source_node_id") == node["node_id"] and row.get("status") != "discarded":
            row["status"] = "stale"
    description_nodes = binding_node_ids(node.get("input_bindings") or {}, "description")
    grouping_nodes = binding_node_ids(node.get("input_bindings") or {}, "grouping")
    for item in registry_json:
        group_id = str(item["group_id"])
        existing = registry_by_id.get(group_id)
        if existing and existing.get("source_node_id") != node["node_id"]:
            raise ValueError(f"Group ID collision across nodes: {group_id}")
        row = existing or {field: "" for field in GROUP_REGISTRY_FIELDS}
        preserve_discard = bool(existing and existing.get("status") == "discarded")
        row.update({
            "group_id": group_id,
            "group_label": str(item.get("group_label") or ""),
            "grouping_capability_id": str(item.get("grouping_capability_id") or node["capability_id"]),
            "grouping_skill_name": node["skill_name"],
            "source_node_id": node["node_id"],
            "source_description_id": str(item.get("source_description_id") or ""),
            "source_description_node_id": description_nodes[0] if description_nodes else "",
            "source_grouping_node_ids": ";".join(grouping_nodes),
            "compound_count": str(len(memberships[group_id])),
            "activity_blind": str(bool(item.get("activity_blind", True))),
            "status": "discarded" if preserve_discard else "active",
            "membership_artifact": str(membership_path.resolve()),
            "definition_json": json.dumps(item.get("definition") or {}, ensure_ascii=False, sort_keys=True),
            "created_at": row.get("created_at") or utc_now(),
            "discard_reason": row.get("discard_reason", "") if preserve_discard else "",
            "discarded_at": row.get("discarded_at", "") if preserve_discard else "",
        })
        if existing is None:
            registry_rows.append(row)
            registry_by_id[group_id] = row
    write_csv_rows(consolidated_registry_path, GROUP_REGISTRY_FIELDS, registry_rows)

    ordered_group_ids = [row["group_id"] for row in registry_rows]
    affected_shards = {ordered_group_ids.index(group_id) // GROUP_MATRIX_SHARD_SIZE for group_id in incoming_ids}
    shard_records = []
    for shard_number, start in enumerate(range(0, len(ordered_group_ids), GROUP_MATRIX_SHARD_SIZE)):
        end = start + GROUP_MATRIX_SHARD_SIZE - 1
        shard_group_ids = ordered_group_ids[start : start + GROUP_MATRIX_SHARD_SIZE]
        shard_path = index_root / f"Cpd_Group_matrix_G{start:06d}_{end:06d}.csv"
        shard_records.append({"path": str(shard_path), "start_index": start, "end_index": end, "group_count": len(shard_group_ids)})
        if shard_number not in affected_shards:
            continue
        existing_rows = {row["compound_id"]: row for row in read_csv_rows(shard_path)}
        output_rows = []
        for compound_id in compound_ids:
            row = {"compound_id": compound_id}
            previous = existing_rows.get(compound_id, {})
            for group_id in shard_group_ids:
                if group_id in memberships:
                    row[group_id] = str(compound_id in memberships[group_id])
                else:
                    row[group_id] = previous.get(group_id, "False")
            output_rows.append(row)
        write_csv_rows(shard_path, ["compound_id", *shard_group_ids], output_rows)

    graph_nodes = state["domain_graph"].setdefault("nodes", [])
    graph_by_id = {item.get("group_id"): item for item in graph_nodes}
    graph_edges = state["domain_graph"].setdefault("edges", [])
    for graph_node in graph_nodes:
        if graph_node.get("source_node_id") == node["node_id"] and graph_node.get("status") != "discarded":
            graph_node["status"] = "stale"
    for item in registry_json:
        group_id = str(item["group_id"])
        group_status = registry_by_id[group_id]["status"]
        graph_node = {
            "group_id": group_id,
            "group_label": item.get("group_label"),
            "grouping_capability_id": item.get("grouping_capability_id"),
            "source_node_id": node["node_id"],
            "source_description_node_id": description_nodes[0] if description_nodes else None,
            "status": group_status,
        }
        if group_id in graph_by_id:
            graph_by_id[group_id].update(graph_node)
        else:
            graph_nodes.append(graph_node)
        edge = {"source": node["node_id"], "target": group_id, "relation": "produces_group"}
        if edge not in graph_edges:
            graph_edges.append(edge)
    active_count = sum(row.get("status") == "active" for row in registry_rows)
    discarded_count = sum(row.get("status") == "discarded" for row in registry_rows)
    state["group_index"] = {
        "registry_path": str(consolidated_registry_path),
        "matrix_shards": shard_records,
        "group_count": len(registry_rows),
        "active_group_count": active_count,
        "discarded_group_count": discarded_count,
        "updated_at": utc_now(),
    }


def append_history(state: dict[str, Any], action: str, **details: Any) -> None:
    state["history"].append({"timestamp": utc_now(), "action": action, **details})


TRANSIENT_PARAMETER_KEYS = {
    "output_dir", "project", "run_id", "node_id", "conductor", "overwrite",
    "input", "description", "membership", "state", "evidence", "catalog",
}


def analysis_signature(capability_id: str, dependencies: list[str], parameters: dict[str, Any]) -> str:
    scientific_parameters = {key: value for key, value in parameters.items() if key not in TRANSIENT_PARAMETER_KEYS}
    if scientific_parameters.get("scope_compound_set_hash"):
        for display_or_path_key in ("membership", "target_group", "comparison_group"):
            scientific_parameters.pop(display_or_path_key, None)
    payload = {
        "capability_id": capability_id,
        "dependencies": sorted(dependencies),
        "parameters": scientific_parameters,
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def safe_node_segment(node_id: str) -> str:
    return node_id.replace(":", "-")


def bind_system_parameter(parameters: dict[str, Any], key: str, value: Any) -> None:
    if key in parameters and parameters[key] != value:
        raise ValueError(f"CONDUCTOR-bound parameter {key} conflicts with the run or dependency artifact")
    parameters[key] = value


def primary_artifact_path(node: dict[str, Any], capability: dict[str, Any]) -> Path:
    output = capability["output"]
    if capability["stage"] == "description":
        extension = "parquet" if node.get("parameters", {}).get("format") == "parquet" else "csv"
        filename = f"{output['basename']}.{extension}"
    elif capability["stage"] == "grouping":
        filename = output["membership"]
    elif capability["stage"] == "analysis":
        filename = output["filename"]
    elif capability["stage"] == "interpretation":
        filename = output.get("json", "interpretation.json")
    else:
        raise ValueError(f"Capability does not produce a DAG artifact: {capability['capability_id']}")
    return Path(node["output_dir"]) / filename


def configure_node_io(
    state: dict[str, Any],
    node: dict[str, Any],
    capability: dict[str, Any],
    capabilities: dict[str, dict[str, Any]],
    output_root: Path,
    input_bindings: dict[str, Any] | None = None,
) -> None:
    bindings = dict(input_bindings or {})
    parameters = node["parameters"]
    configured_output = parameters.get("output_dir")
    output_dir = Path(configured_output) if configured_output else output_root / capability["stage"] / capability["skill_name"] / safe_node_segment(node["node_id"])
    output_dir = output_dir.resolve()
    node["output_dir"] = str(output_dir)
    node["input_bindings"] = bindings
    parameters["output_dir"] = str(output_dir)

    stage = capability["stage"]
    if stage == "description":
        bind_system_parameter(parameters, "input", state["run"]["input"])
        parameters.setdefault("format", "csv")
    elif stage == "grouping":
        description_node_ids = binding_node_ids(bindings, "description")
        grouping_node_ids = binding_node_ids(bindings, "grouping")
        source_node_ids = description_node_ids or grouping_node_ids
        if source_node_ids:
            artifact_paths = []
            for source_node_id in source_node_ids:
                source_node = state_nodes(state)[source_node_id]
                source_capability = capabilities[source_node["capability_id"]]
                artifact_paths.append(str(primary_artifact_path(source_node, source_capability)))
            bind_system_parameter(parameters, "input", artifact_paths[0] if len(artifact_paths) == 1 else artifact_paths)
            if description_node_ids:
                source_node = state_nodes(state)[description_node_ids[0]]
                bind_system_parameter(parameters, "input_representation", source_node["capability_id"])
        else:
            bind_system_parameter(parameters, "input", state["run"]["input"])
    elif stage == "analysis":
        bind_system_parameter(parameters, "input", state["run"]["input"])
        bind_system_parameter(parameters, "property_column", state["run"]["endpoint"])
        bind_system_parameter(parameters, "higher_is_better", state["run"]["higher_is_better"])
        description_node_ids = binding_node_ids(bindings, "description")
        grouping_node_ids = binding_node_ids(bindings, "grouping")
        if description_node_ids:
            source_node = state_nodes(state)[description_node_ids[0]]
            source_capability = capabilities[source_node["capability_id"]]
            bind_system_parameter(parameters, "description", str(primary_artifact_path(source_node, source_capability)))
            bind_system_parameter(parameters, "evaluation_representation", source_node["capability_id"])
        if grouping_node_ids:
            source_node = state_nodes(state)[grouping_node_ids[0]]
            source_capability = capabilities[source_node["capability_id"]]
            bind_system_parameter(parameters, "membership", str(primary_artifact_path(source_node, source_capability)))
            bind_system_parameter(parameters, "grouping_representation", source_node["capability_id"])
        if capability["capability_id"] in {"A003", "A007", "A010"}:
            bind_system_parameter(parameters, "evaluation_representation", "internal_morgan_r2_2048")
    elif stage == "interpretation":
        evidence_paths = []
        for dependency_node_id in node.get("dependencies") or []:
            source_node = state_nodes(state)[dependency_node_id]
            if source_node["stage"] == "analysis":
                evidence_paths.append(str(Path(source_node["output_dir"]) / "evidence.json"))
        if evidence_paths:
            bind_system_parameter(parameters, "evidence", evidence_paths)
        bind_system_parameter(parameters, "state", str((output_root / "state.json").resolve()))


def nodes_for_wide_source(
    state: dict[str, Any],
    dependency_stage: str,
    source_ids: list[str],
) -> list[dict[str, Any]]:
    candidates = [
        node for node in state["execution_graph"]["nodes"]
        if node["stage"] == dependency_stage and node.get("phase") == "wide_shallow"
    ]
    if "*" in source_ids:
        return candidates
    order = {capability_id: index for index, capability_id in enumerate(source_ids)}
    return sorted(
        (node for node in candidates if node["capability_id"] in order),
        key=lambda node: (order[node["capability_id"]], node["node_id"]),
    )


def wide_shallow_summary(state: dict[str, Any]) -> dict[str, Any]:
    wide_nodes = [node for node in state["execution_graph"]["nodes"] if node.get("phase") == "wide_shallow"]
    stages: dict[str, Any] = {}
    for stage in ["description", "grouping", "analysis"]:
        stage_nodes = [node for node in wide_nodes if node["stage"] == stage]
        axes: dict[str, dict[str, int]] = {}
        for node in stage_nodes:
            axis = node.get("coverage_axis") or node["capability_id"]
            counts = axes.setdefault(axis, {})
            counts[node["status"]] = counts.get(node["status"], 0) + 1
        stages[stage] = {"node_count": len(stage_nodes), "axes": axes}
    terminal = {"succeeded", "failed", "skipped"}
    return {
        "profile": "representative-family-wide-v1",
        "node_count": len(wide_nodes),
        "terminal": bool(wide_nodes) and all(node["status"] in terminal for node in wide_nodes),
        "all_succeeded": bool(wide_nodes) and all(node["status"] == "succeeded" for node in wide_nodes),
        "stages": stages,
    }


def cmd_init(args: argparse.Namespace) -> int:
    workspace = find_workspace()
    input_path = Path(args.input).resolve()
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    with input_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames or []
        id_column = infer_run_id_column(header)
        row_count = 0
        identifiers: list[str] = []
        numeric_endpoint_count = 0
        assay_levels_seen: set[str] = set()
        for row in reader:
            row_count += 1
            identifier = str(row.get(id_column, "")).strip()
            if not identifier:
                raise ValueError(f"Blank compound ID at input row {row_count + 1}")
            identifiers.append(identifier)
            endpoint_value = str(row.get(args.endpoint, "")).strip()
            if endpoint_value:
                try:
                    float(endpoint_value)
                    numeric_endpoint_count += 1
                except ValueError as exc:
                    raise ValueError(f"Non-numeric endpoint value at input row {row_count + 1}: {endpoint_value}") from exc
            if args.assay_column:
                value = str(row.get(args.assay_column, "")).strip()
                if value:
                    assay_levels_seen.add(value)
    if args.endpoint not in header:
        raise ValueError(f"Endpoint column not found: {args.endpoint}")
    if args.assay_column and args.assay_column not in header:
        raise ValueError(f"Assay column not found: {args.assay_column}")
    duplicates = sorted({identifier for identifier in identifiers if identifiers.count(identifier) > 1})
    if duplicates:
        raise ValueError(f"Duplicate compound IDs: {duplicates[:10]}")
    if numeric_endpoint_count < 2:
        raise ValueError("At least two numeric endpoint values are required")
    assay_levels = sorted(assay_levels_seen)
    run_id = args.run_id or run_id_now()
    outdir = Path(args.output_dir) if args.output_dir else workspace / "results" / "CONDUCTOR" / args.project / run_id
    state_path = outdir / "state.json"
    if state_path.exists() and not args.overwrite:
        raise FileExistsError(f"State exists; use --overwrite or resume it: {state_path}")
    state = {
        "schema_version": "1.0.0",
        "conductor_version": "4.0.0",
        "run": {"run_id": run_id, "project": args.project, "input": str(input_path), "input_hash": file_hash(input_path), "endpoint": args.endpoint, "higher_is_better": args.higher_is_better, "parallel_limit": args.parallel_limit, "row_count": row_count, "id_column": id_column, "assay_column": args.assay_column, "assay_level_count": len(assay_levels), "created_at": utc_now()},
        "execution_graph": {"nodes": [], "edges": []},
        "domain_graph": {"nodes": [], "edges": []},
        "evidence_graph": {"nodes": [], "edges": []},
        "group_index": {"registry_path": str((outdir / "grouping" / "group_index" / "group_registry.csv").resolve()), "matrix_shards": [], "group_count": 0, "active_group_count": 0, "discarded_group_count": 0, "updated_at": utc_now()},
        "interpretations": [],
        "interpretation_exploration": default_exploration_state(),
        "history": [],
        "updated_at": utc_now(),
    }
    append_history(state, "initialized")
    write_state(state_path, state)
    print(state_path)
    return 0


def add_node(
    state: dict[str, Any],
    capability: dict[str, Any],
    dependencies: list[str] | None = None,
    reason: str = "",
    parameters: dict[str, Any] | None = None,
    phase: str = "deep_dive",
    coverage_axis: str | None = None,
) -> dict[str, Any]:
    existing = [node for node in state["execution_graph"]["nodes"] if node["capability_id"] == capability["capability_id"]]
    node_id = f"{capability['capability_id']}:{len(existing) + 1:03d}"
    approval = "required" if capability["cost"].get("human_approval_required") else "not_required"
    selected_parameters = dict(capability.get("default_parameters") or {})
    selected_parameters.update(parameters or {})
    signature = analysis_signature(capability["capability_id"], dependencies or [], selected_parameters)
    node = {"node_id": node_id, "capability_id": capability["capability_id"], "skill_name": capability["skill_name"], "stage": capability["stage"], "phase": phase, "coverage_axis": coverage_axis, "status": "pending", "dependencies": dependencies or [], "human_approval": approval, "selection_reason": reason, "parameters": selected_parameters, "analysis_signature": signature, "cost": capability["cost"], "artifacts": [], "warnings": []}
    state["execution_graph"]["nodes"].append(node)
    for dependency in dependencies or []:
        state["execution_graph"]["edges"].append({"source": dependency, "target": node_id, "relation": "depends_on"})
    append_history(state, "node_added", node_id=node_id, capability_id=capability["capability_id"])
    return node


def cmd_plan_wide(args: argparse.Namespace) -> int:
    state_path = Path(args.state)
    workspace = find_workspace()
    capabilities = catalog_by_id(workspace)
    with state_lock(state_path):
        state = read_json(state_path)
        planned = []
        stage_order = {"description": 0, "grouping": 1, "analysis": 2, "interpretation": 3, "orchestration": 4}
        ordered_capabilities = sorted(
            capabilities.values(),
            key=lambda capability: (stage_order.get(capability["stage"], 99), capability["capability_id"]),
        )
        for capability in ordered_capabilities:
            assay_grouping = (
                capability.get("implementation", {}).get("algorithm") == "categorical"
                and state["run"].get("assay_level_count", 0) > 1
            )
            if not capability.get("default_wide_shallow") and not assay_grouping:
                continue
            required = capability.get("dependencies") or []
            if "evidence" in required:
                continue
            source_config = capability.get("wide_shallow_sources") or {}
            source_sets: list[tuple[str, list[dict[str, Any]]]] = []
            for dependency_stage in required:
                source_ids = source_config.get(dependency_stage)
                if not source_ids:
                    raise ValueError(f"{capability['capability_id']}: wide-shallow source mapping is missing for {dependency_stage}")
                source_nodes = nodes_for_wide_source(state, dependency_stage, source_ids)
                if not source_nodes:
                    raise ValueError(f"{capability['capability_id']}: no planned wide-shallow source node for {dependency_stage}={source_ids}")
                source_sets.append((dependency_stage, source_nodes))
            binding_sets = [dict()] if not source_sets else [
                {source_sets[index][0]: source_node["node_id"] for index, source_node in enumerate(combination)}
                for combination in product(*(nodes for _, nodes in source_sets))
            ]
            for bindings in binding_sets:
                already_planned = next((
                    node for node in state["execution_graph"]["nodes"]
                    if node["capability_id"] == capability["capability_id"]
                    and node.get("phase") == "wide_shallow"
                    and (node.get("input_bindings") or {}) == bindings
                ), None)
                if already_planned:
                    continue
                parameters = {"columns": state["run"]["assay_column"]} if assay_grouping else {}
                parameter_overrides = capability.get("wide_shallow_parameter_overrides") or {}
                for dependency_stage, source_node_id in bindings.items():
                    source_capability_id = state_nodes(state)[source_node_id]["capability_id"]
                    parameters.update((parameter_overrides.get(dependency_stage) or {}).get(source_capability_id) or {})
                reason = "Multiple assay conditions detected; plan assay-specific Grouping" if assay_grouping else f"Initial broad coverage axis={capability.get('wide_shallow_axis')}; sources={bindings or 'run_input'}"
                node = add_node(
                    state, capability, list(bindings.values()), reason, parameters,
                    phase="wide_shallow", coverage_axis=capability.get("wide_shallow_axis") or "assay_context_groups",
                )
                configure_node_io(state, node, capability, capabilities, state_path.parent, bindings)
                planned.append(node["node_id"])
        all_wide_nodes = [node for node in state["execution_graph"]["nodes"] if node.get("phase") == "wide_shallow"]
        state["wide_shallow_plan"] = {
            "profile": "representative-family-wide-v1",
            "node_ids": [node["node_id"] for node in all_wide_nodes],
            "required_axes": {
                stage: sorted({node.get("coverage_axis") or node["capability_id"] for node in all_wide_nodes if node["stage"] == stage})
                for stage in ["description", "grouping", "analysis"]
            },
        }
        append_history(state, "wide_plan_created", node_ids=planned, profile="representative-family-wide-v1")
        write_state(state_path, state)
    print(json.dumps({"planned_nodes": planned, "coverage": wide_shallow_summary(state)}, ensure_ascii=False, indent=2))
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    state_path = Path(args.state)
    capabilities = catalog_by_id(find_workspace())
    capability = capabilities.get(args.capability_id)
    if capability is None:
        raise ValueError(f"Capability is not in the human-curated Catalog: {args.capability_id}")
    if capability["stage"] == "orchestration":
        raise ValueError("The Orchestrator capability coordinates the run and cannot be added as an execution node")
    parameters: dict[str, Any] = {}
    if args.parameters_json:
        parsed = json.loads(args.parameters_json)
        if not isinstance(parsed, dict):
            raise ValueError("--parameters-json must decode to a JSON object")
        parameters = parsed
    with state_lock(state_path):
        state = read_json(state_path)
        dependencies = [value.strip() for value in (args.depends_on or "").split(",") if value.strip()]
        unknown = [value for value in dependencies if value not in state_nodes(state)]
        if unknown:
            raise ValueError(f"Unknown dependency nodes: {unknown}")
        dependency_nodes = [state_nodes(state)[node_id] for node_id in dependencies]
        if any(item["stage"] == "interpretation" for item in dependency_nodes):
            raise ValueError("Interpretation nodes are terminal and cannot be execution dependencies")
        validate_dependency_contract(capability, dependency_nodes)
        selected_parameters = dict(capability.get("default_parameters") or {})
        selected_parameters.update(parameters)
        validate_analysis_scope_contract(capability, dependency_nodes, selected_parameters)
        signature = analysis_signature(capability["capability_id"], dependencies, selected_parameters)
        duplicate = next((item["node_id"] for item in state["execution_graph"]["nodes"] if item.get("analysis_signature") == signature), None)
        if duplicate:
            raise ValueError(f"Repeated analysis signature is not allowed; existing node={duplicate}")
        bindings = dependency_bindings(dependency_nodes)
        node = add_node(state, capability, dependencies, args.reason or "Human or Orchestrator selected deep-dive", parameters)
        configure_node_io(state, node, capability, capabilities, state_path.parent, bindings)
        if args.require_approval and node["human_approval"] == "not_required":
            node["human_approval"] = "required"
            append_history(state, "dynamic_approval_required", node_id=node["node_id"], reason=args.reason or "Dataset-scale or runtime-specific cost")
        write_state(state_path, state)
    print(json.dumps(node, ensure_ascii=False, indent=2))
    return 0


def cmd_configure_exploration(args: argparse.Namespace) -> int:
    state_path = Path(args.state)
    with state_lock(state_path):
        state = ensure_exploration_state(read_json(state_path))
        budget = {
            "configured": True,
            "max_iterations": args.max_iterations,
            "max_additional_nodes": args.max_additional_nodes,
            "walltime_minutes": args.walltime_minutes,
            "seed": args.seed,
            "configured_at": utc_now(),
        }
        state["interpretation_exploration"]["budget"] = budget
        append_history(state, "interpretation_exploration_budget_configured", budget=budget)
        write_state(state_path, state)
    print(json.dumps(budget, ensure_ascii=False, indent=2))
    return 0


def completed_exploration_walltime_minutes(state: dict[str, Any]) -> float:
    total_seconds = 0.0
    for node in state["execution_graph"]["nodes"]:
        if node.get("phase") != "interpretation_exploration" or not node.get("started_at") or not node.get("finished_at"):
            continue
        try:
            started = datetime.fromisoformat(node["started_at"])
            finished = datetime.fromisoformat(node["finished_at"])
            total_seconds += max(0.0, (finished - started).total_seconds())
        except ValueError:
            continue
    return total_seconds / 60.0


def validate_exploration_plan(plan: dict[str, Any]) -> None:
    try:
        import jsonschema
    except ImportError as exc:
        raise RuntimeError("jsonschema is required") from exc
    schema = read_json(SKILL_DIR / "schemas" / "interpretation_exploration_plan.schema.json")
    jsonschema.validate(plan, schema)


def infer_input_id_column(path: Path, requested: str | None = None) -> tuple[str, set[str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames or []
        normalized = {"".join(character for character in name.lower() if character.isalnum()): name for name in header}
        candidates = [requested] if requested else ["compound_id", "compoundid", "molecule_id", "moleculeid", "id", "chembl_id"]
        id_column = next((normalized.get("".join(character for character in candidate.lower() if character.isalnum())) for candidate in candidates if candidate), None)
        if id_column is None:
            raise ValueError("Exploration scope input ID column could not be inferred; set scope.id_column")
        identifiers = {str(row.get(id_column, "")).strip() for row in reader}
    identifiers.discard("")
    return id_column, identifiers


def prepare_exploration_scope(
    state_path: Path,
    state: dict[str, Any],
    capability: dict[str, Any],
    request: dict[str, Any],
    selected_parameters: dict[str, Any],
) -> tuple[dict[str, Any] | None, tuple[Path, list[dict[str, str]]] | None]:
    scope = request.get("scope")
    if not scope:
        return None, None
    if capability["stage"] != "analysis":
        raise ValueError(f"Explicit compound scope is valid only for Operator requests: {request['request_id']}")
    supported_modes = set(capability.get("scope_support") or ["global"])
    if scope["mode"] not in supported_modes:
        raise ValueError(f"{capability['capability_id']} does not support scope mode {scope['mode']}")

    input_path = Path(state["run"]["input"])
    id_column, available_ids = infer_input_id_column(input_path, scope.get("id_column") or selected_parameters.get("id_column"))
    target_ids = {str(value).strip() for value in scope["target_compound_ids"]}
    comparison_ids = {str(value).strip() for value in scope.get("comparison_compound_ids") or []}
    requested_ids = target_ids | comparison_ids
    unknown_ids = sorted(requested_ids - available_ids)
    if unknown_ids:
        preview = unknown_ids[:10]
        raise ValueError(f"Exploration scope contains compound IDs absent from run input: {preview}")
    if len(requested_ids) < 2:
        raise ValueError("Exploration scope must contain at least two distinct compounds")

    if scope["mode"] == "between-groups" and not comparison_ids:
        raise ValueError("between-groups exploration scope requires comparison_compound_ids")
    canonical_scope = {
        "mode": scope["mode"],
        "partitions": (
            sorted([sorted(target_ids), sorted(comparison_ids)])
            if scope["mode"] == "between-groups"
            else [sorted(target_ids)]
        ),
    }
    compound_set_hash = hashlib.sha256(json.dumps(canonical_scope, sort_keys=True).encode("utf-8")).hexdigest()
    canonical_group_definition = {
        **canonical_scope,
        "selection_method": scope["selection_method"],
        "source_group_ids": sorted(scope.get("source_group_ids") or []),
    }
    group_definition_hash = hashlib.sha256(json.dumps(canonical_group_definition, sort_keys=True).encode("utf-8")).hexdigest()
    target_group_label = scope.get("target_group_id") or f"scope:{scope['scope_id']}:target"
    comparison_group_label = scope.get("comparison_group_id") if scope["mode"] == "between-groups" else None
    target_group = f"G_SCOPE_{group_definition_hash[:16]}_A"
    comparison_group = f"G_SCOPE_{group_definition_hash[:16]}_B" if scope["mode"] == "between-groups" else None
    if scope["mode"] == "between-groups":
        comparison_group_label = comparison_group_label or f"scope:{scope['scope_id']}:comparison"
    scope_path = (state_path.parent / "interpretation" / "scopes" / f"{group_definition_hash}.csv").resolve()
    rows = [{"cluster_id": target_group, "compound_id": compound_id, "membership_value": "1.0", "membership_reason": target_group_label} for compound_id in sorted(target_ids)]
    rows.extend({"cluster_id": comparison_group, "compound_id": compound_id, "membership_value": "1.0", "membership_reason": comparison_group_label} for compound_id in sorted(comparison_ids))

    selected_parameters.update({
        "membership": str(scope_path),
        "scope_mode": scope["mode"],
        "target_group": target_group,
        "scope_compound_set_hash": compound_set_hash,
        "reference_scope": selected_parameters.get("reference_scope", "global"),
    })
    if comparison_group:
        selected_parameters["comparison_group"] = comparison_group
    scope_record = {
        "scope_id": scope["scope_id"],
        "mode": scope["mode"],
        "selection_method": scope["selection_method"],
        "source_group_ids": scope.get("source_group_ids") or [],
        "input_id_column": id_column,
        "target_group_id": target_group,
        "comparison_group_id": comparison_group,
        "target_group_label": target_group_label,
        "comparison_group_label": comparison_group_label,
        "target_count": len(target_ids),
        "comparison_count": len(comparison_ids),
        "compound_set_hash": compound_set_hash,
        "group_definition_hash": group_definition_hash,
        "membership_path": str(scope_path),
        "selection_notes": scope.get("selection_notes", ""),
    }
    return scope_record, (scope_path, rows)


def write_scope_membership(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["cluster_id", "compound_id", "membership_value", "membership_reason"])
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def cmd_register_exploration(args: argparse.Namespace) -> int:
    state_path = Path(args.state)
    plan_path = Path(args.plan)
    plan = read_json(plan_path)
    validate_exploration_plan(plan)
    capabilities = catalog_by_id(find_workspace())
    with state_lock(state_path):
        state = ensure_exploration_state(read_json(state_path))
        budget = state["interpretation_exploration"]["budget"]
        if not budget.get("configured"):
            raise ValueError("Interpretation exploration budget is not configured")
        if plan["run_id"] != state["run"]["run_id"]:
            raise ValueError("Exploration plan run_id does not match State")
        if plan["seed"] != budget["seed"]:
            raise ValueError("Exploration plan seed does not match the human-configured State seed")
        known_interpretation_ids = {item.get("interpretation_id") for item in state.get("interpretations") or []}
        if plan["source_interpretation_id"] not in known_interpretation_ids:
            raise ValueError(f"Unknown source_interpretation_id: {plan['source_interpretation_id']}")
        if any(item.get("iteration") == plan["iteration"] for item in state["interpretation_exploration"]["iterations"]):
            raise ValueError(f"Exploration iteration is already registered: {plan['iteration']}")
        if plan["iteration"] > budget["max_iterations"]:
            raise ValueError("Exploration plan exceeds the maximum iteration budget")
        existing_count = len(state["interpretation_exploration"]["ledger"])
        if existing_count + len(plan["requests"]) > budget["max_additional_nodes"]:
            raise ValueError("Exploration plan exceeds the additional-node budget")
        consumed_minutes = completed_exploration_walltime_minutes(state)
        if consumed_minutes >= budget["walltime_minutes"]:
            raise ValueError("Interpretation exploration walltime budget is exhausted")

        discovery_id_list = [item["discovery_id"] for item in plan["discoveries"]]
        if len(discovery_id_list) != len(set(discovery_id_list)):
            raise ValueError("Exploration discovery IDs must be unique")
        plan_request_ids = [item["request_id"] for item in plan["requests"]]
        if len(plan_request_ids) != len(set(plan_request_ids)):
            raise ValueError("Exploration request IDs must be unique")
        discovery_ids = set(discovery_id_list)
        known_evidence_ids = {item.get("evidence_id") for item in state.get("evidence_graph", {}).get("nodes", [])}
        unknown_evidence = sorted({evidence_id for discovery in plan["discoveries"] for evidence_id in discovery.get("evidence_ids") or []} - known_evidence_ids)
        if unknown_evidence:
            raise ValueError(f"Exploration discoveries reference unknown evidence: {unknown_evidence}")
        referenced_discoveries = {
            discovery_id
            for request in plan["requests"]
            for discovery_id in request.get("parent_discovery_ids") or []
        }
        unknown_discoveries = sorted(referenced_discoveries - discovery_ids)
        if unknown_discoveries:
            raise ValueError(f"Exploration requests reference unknown discoveries: {unknown_discoveries}")
        falsified_ids = {
            discovery_id
            for request in plan["requests"]
            if request["purpose"] == "falsify"
            for discovery_id in request.get("parent_discovery_ids") or []
        }
        missing_falsification = sorted(discovery_ids - falsified_ids)
        if missing_falsification:
            raise ValueError(f"Every discovery requires a falsification request: {missing_falsification}")

        bounds = plan.get("bounds") or {}
        scientific_bound_keys = ("group_ids", "description_ids", "grouping_ids", "operator_ids")
        if plan["mode"] == "orchestrator-bounded" and not any(bounds.get(key) for key in scientific_bound_keys):
            raise ValueError("orchestrator-bounded exploration requires at least one explicit scientific bound")

        known_nodes = state_nodes(state)
        known_signatures = {node.get("analysis_signature") for node in known_nodes.values() if node.get("analysis_signature")}
        known_signatures.update(item.get("analysis_signature") for item in state["interpretation_exploration"]["ledger"])
        request_ids = {item.get("request_id") for item in state["interpretation_exploration"]["ledger"]}
        planned_nodes = []
        new_ledger = []
        pending_scope_files: dict[Path, list[dict[str, str]]] = {}
        request_node_ids: dict[str, str] = {}
        for request in plan["requests"]:
            if request["request_id"] in request_ids:
                raise ValueError(f"Exploration request is already registered: {request['request_id']}")
            capability = capabilities.get(request["capability_id"])
            if capability is None:
                raise ValueError(f"Capability is not in the human-curated Catalog: {request['capability_id']}")
            if capability["stage"] in {"interpretation", "orchestration"}:
                raise ValueError("Exploration requests may contain only Description, Grouping, or Operator capabilities")
            bound_key = {"description": "description_ids", "grouping": "grouping_ids", "analysis": "operator_ids"}[capability["stage"]]
            if bounds.get(bound_key) and capability["capability_id"] not in bounds[bound_key]:
                raise ValueError(f"Exploration request is outside {bound_key}: {request['request_id']}")
            scope_definition = request.get("scope") or {}
            bounded_groups = set(bounds.get("group_ids") or [])
            referenced_groups = set(scope_definition.get("source_group_ids") or [])
            if not scope_definition:
                referenced_groups.update(
                    value for value in (
                        (request.get("parameters") or {}).get("target_group"),
                        (request.get("parameters") or {}).get("comparison_group"),
                    ) if value
                )
            if bounded_groups and not referenced_groups.issubset(bounded_groups):
                raise ValueError(f"Exploration request references groups outside bounds: {request['request_id']}")
            known_groups = {item.get("group_id"): item for item in state.get("domain_graph", {}).get("nodes", [])}
            unknown_groups = sorted(referenced_groups - set(known_groups))
            if unknown_groups:
                raise ValueError(f"Exploration request references unknown Group IDs: {unknown_groups}")
            discarded_groups = sorted(group_id for group_id in referenced_groups if known_groups[group_id].get("status") == "discarded")
            if discarded_groups:
                raise ValueError(f"Exploration request references discarded Group IDs: {discarded_groups}")
            dependencies = [request_node_ids.get(value, value) for value in (request.get("depends_on") or [])]
            unknown = [node_id for node_id in dependencies if node_id not in known_nodes]
            if unknown:
                raise ValueError(f"Unknown exploration dependency nodes or forward request references: {unknown}")
            if any(known_nodes[node_id]["stage"] == "interpretation" for node_id in dependencies):
                raise ValueError("Interpretation nodes are terminal and cannot be execution dependencies")
            dependency_nodes = [known_nodes[node_id] for node_id in dependencies]
            validate_dependency_contract(capability, dependency_nodes)
            for dependency_node in dependency_nodes:
                dependency_bound_key = {"description": "description_ids", "grouping": "grouping_ids", "analysis": "operator_ids"}.get(dependency_node["stage"])
                if dependency_bound_key and bounds.get(dependency_bound_key) and dependency_node["capability_id"] not in bounds[dependency_bound_key]:
                    raise ValueError(f"Exploration dependency is outside {dependency_bound_key}: {dependency_node['node_id']}")
            selected_parameters = dict(capability.get("default_parameters") or {})
            selected_parameters.update(request.get("parameters") or {})
            scope_record, pending_scope = prepare_exploration_scope(state_path, state, capability, request, selected_parameters)
            validate_analysis_scope_contract(capability, dependency_nodes, selected_parameters)
            if pending_scope:
                scope_path, scope_rows = pending_scope
                pending_scope_files[scope_path] = scope_rows
            signature = analysis_signature(capability["capability_id"], dependencies, selected_parameters)
            if signature in known_signatures:
                raise ValueError(f"Repeated analysis signature is not allowed: {request['request_id']} ({signature})")
            bindings = dependency_bindings(dependency_nodes)
            node = add_node(
                state,
                capability,
                dependencies,
                request["selection_reason"],
                selected_parameters,
                phase="interpretation_exploration",
                coverage_axis=f"interpretation_{request['purpose']}",
            )
            configure_node_io(state, node, capability, capabilities, state_path.parent, bindings)
            node["exploration"] = {
                "request_id": request["request_id"],
                "iteration": plan["iteration"],
                "purpose": request["purpose"],
                "parent_discovery_ids": request.get("parent_discovery_ids") or [],
                "source_interpretation_id": plan["source_interpretation_id"],
                "expected_information_gain": request["expected_information_gain"],
                "scope": scope_record,
            }
            node["analysis_signature"] = signature
            known_signatures.add(signature)
            known_nodes[node["node_id"]] = node
            request_node_ids[request["request_id"]] = node["node_id"]
            request_ids.add(request["request_id"])
            planned_nodes.append(node["node_id"])
            new_ledger.append({
                "request_id": request["request_id"],
                "iteration": plan["iteration"],
                "node_id": node["node_id"],
                "analysis_signature": signature,
                "purpose": request["purpose"],
                "parent_discovery_ids": request.get("parent_discovery_ids") or [],
                "status": "planned",
                "scope": scope_record,
            })
        for scope_path, scope_rows in pending_scope_files.items():
            write_scope_membership(scope_path, scope_rows)
        for node_id in planned_nodes:
            node = known_nodes[node_id]
            scope_record = (node.get("exploration") or {}).get("scope")
            if not scope_record:
                continue
            scope_path = Path(scope_record["membership_path"])
            scope_groups = [{
                "group_id": scope_record["target_group_id"],
                "group_label": scope_record.get("target_group_label"),
                "grouping_capability_id": "SCOPE",
                "source_description_id": None,
                "definition": {"selection_method": scope_record["selection_method"], "source_group_ids": scope_record["source_group_ids"], "selection_notes": scope_record["selection_notes"]},
                "compound_count": scope_record["target_count"],
                "activity_blind": True,
            }]
            if scope_record.get("comparison_group_id"):
                scope_groups.append({
                    "group_id": scope_record["comparison_group_id"],
                    "group_label": scope_record.get("comparison_group_label"),
                    "grouping_capability_id": "SCOPE",
                    "source_description_id": None,
                    "definition": {"selection_method": scope_record["selection_method"], "source_group_ids": scope_record["source_group_ids"], "selection_notes": scope_record["selection_notes"]},
                    "compound_count": scope_record["comparison_count"],
                    "activity_blind": True,
                })
            scope_registry_path = scope_path.with_suffix(".groups.json")
            write_json_file(scope_registry_path, scope_groups)
            scope_source = {
                "node_id": f"SCOPE:{scope_record['group_definition_hash'][:16]}",
                "capability_id": "SCOPE",
                "skill_name": "cs-conductor-orchestrator",
                "input_bindings": {},
            }
            update_group_index(state_path, state, scope_source, scope_path, scope_registry_path)
        state["interpretation_exploration"]["ledger"].extend(new_ledger)
        state["interpretation_exploration"]["iterations"].append({
            "iteration": plan["iteration"],
            "seed": plan["seed"],
            "mode": plan["mode"],
            "source_interpretation_id": plan["source_interpretation_id"],
            "plan_path": str(plan_path.resolve()),
            "plan_hash": file_hash(plan_path),
            "request_ids": [item["request_id"] for item in plan["requests"]],
            "unselected_candidates": plan["unselected_candidates"],
            "registered_at": utc_now(),
        })
        append_history(state, "interpretation_exploration_registered", iteration=plan["iteration"], node_ids=planned_nodes)
        write_state(state_path, state)
    print(json.dumps({"planned_nodes": planned_nodes, "remaining_node_budget": budget["max_additional_nodes"] - existing_count - len(planned_nodes)}, ensure_ascii=False, indent=2))
    return 0


def skip_blocked_descendants(state: dict[str, Any], source_node_id: str, reason: str) -> list[str]:
    """Mark nodes that can no longer satisfy a dependency as terminal skips."""
    skipped: list[str] = []
    nodes = state_nodes(state)
    frontier = [source_node_id]
    while frontier:
        source = frontier.pop()
        for edge in state["execution_graph"]["edges"]:
            if edge["source"] != source:
                continue
            target_id = edge["target"]
            target = nodes[target_id]
            if target["status"] in {"pending", "stale"}:
                target["status"] = "skipped"
                target["skip_reason"] = reason
                target["finished_at"] = utc_now()
                update_exploration_ledger(state, target_id, "skipped", target["finished_at"])
                skipped.append(target_id)
                frontier.append(target_id)
    return skipped


def update_exploration_ledger(state: dict[str, Any], node_id: str, status: str, finished_at: str | None = None) -> None:
    for item in ensure_exploration_state(state)["interpretation_exploration"]["ledger"]:
        if item.get("node_id") == node_id:
            item["status"] = status
            if finished_at:
                item["finished_at"] = finished_at


def cmd_approve(args: argparse.Namespace) -> int:
    state_path = Path(args.state)
    with state_lock(state_path):
        state = read_json(state_path)
        node = state_nodes(state).get(args.node_id)
        if node is None:
            raise ValueError(f"Unknown node: {args.node_id}")
        if node["human_approval"] != "required":
            raise ValueError(f"Node is not awaiting approval: {args.node_id}")
        node["human_approval"] = "approved" if args.approve else "rejected"
        if not args.approve:
            node["status"] = "skipped"
            node["skip_reason"] = f"Human rejected required computation: {args.rationale}"
            node["finished_at"] = utc_now()
            update_exploration_ledger(state, args.node_id, "skipped", node["finished_at"])
            skipped = skip_blocked_descendants(state, args.node_id, f"Required upstream node {args.node_id} was rejected")
        else:
            skipped = []
        append_history(state, "approval_recorded", node_id=args.node_id, decision=node["human_approval"], rationale=args.rationale, downstream_skipped=skipped)
        write_state(state_path, state)
    return 0


def node_readiness_error(state: dict[str, Any], node: dict[str, Any]) -> str | None:
    if node["human_approval"] in {"required", "rejected"}:
        return f"Node is not approved for execution: {node['node_id']}"
    if node["stage"] == "interpretation":
        unfinished_wide = [
            item["node_id"] for item in state["execution_graph"]["nodes"]
            if item.get("phase") == "wide_shallow" and item["status"] not in {"succeeded", "failed", "skipped"}
        ]
        if unfinished_wide:
            return f"Wide-shallow coverage audit is not terminal: {unfinished_wide}"
    nodes = state_nodes(state)
    incomplete = [dependency for dependency in node["dependencies"] if nodes[dependency]["status"] != "succeeded"]
    if incomplete:
        return f"Dependencies are not complete: {incomplete}"
    return None


def cmd_start(args: argparse.Namespace) -> int:
    state_path = Path(args.state)
    with state_lock(state_path):
        state = read_json(state_path)
        node = state_nodes(state).get(args.node_id)
        if node is None:
            raise ValueError(f"Unknown node: {args.node_id}")
        if node["status"] not in {"pending", "stale"}:
            raise ValueError(f"Node cannot start from status {node['status']}: {args.node_id}")
        readiness_error = node_readiness_error(state, node)
        if readiness_error:
            raise ValueError(readiness_error)
        running_count = sum(item["status"] == "running" for item in state["execution_graph"]["nodes"])
        if running_count >= int(state["run"]["parallel_limit"]):
            raise ValueError("Parallel limit has been reached")
        node["status"] = "running"
        node["started_at"] = utc_now()
        append_history(state, "node_started", node_id=args.node_id)
        write_state(state_path, state)
    return 0


def cmd_fail(args: argparse.Namespace) -> int:
    state_path = Path(args.state)
    with state_lock(state_path):
        state = read_json(state_path)
        node = state_nodes(state).get(args.node_id)
        if node is None:
            raise ValueError(f"Unknown node: {args.node_id}")
        if node["status"] != "running":
            raise ValueError(f"Only a running node can be marked failed: {args.node_id}")
        node["status"] = "failed"
        node["finished_at"] = utc_now()
        node["error"] = args.reason
        update_exploration_ledger(state, args.node_id, "failed", node["finished_at"])
        skipped = skip_blocked_descendants(state, args.node_id, f"Required upstream node {args.node_id} failed")
        append_history(state, "node_failed", node_id=args.node_id, reason=args.reason, downstream_skipped=skipped)
        write_state(state_path, state)
    return 0


def downstream(state: dict[str, Any], source: str) -> set[str]:
    edges = state["execution_graph"]["edges"]
    found: set[str] = set()
    frontier = [source]
    while frontier:
        current = frontier.pop()
        for edge in edges:
            if edge["source"] == current and edge["target"] not in found:
                found.add(edge["target"]); frontier.append(edge["target"])
    return found


def set_derived_graph_status(state: dict[str, Any], source_node_ids: set[str], status: str) -> None:
    for graph_name in ["domain_graph", "evidence_graph"]:
        for item in state[graph_name].setdefault("nodes", []):
            if item.get("source_node_id") in source_node_ids and item.get("status") != "discarded":
                item["status"] = status
    registry_path_text = (state.get("group_index") or {}).get("registry_path")
    if registry_path_text:
        registry_path = Path(registry_path_text)
        rows = read_csv_rows(registry_path)
        changed = False
        for row in rows:
            if row.get("source_node_id") in source_node_ids and row.get("status") != "discarded":
                row["status"] = status
                changed = True
        if changed:
            write_csv_rows(registry_path, GROUP_REGISTRY_FIELDS, rows)
            group_index = state["group_index"]
            group_index["active_group_count"] = sum(row.get("status") == "active" for row in rows)
            group_index["discarded_group_count"] = sum(row.get("status") == "discarded" for row in rows)
            group_index["updated_at"] = utc_now()


def cmd_record(args: argparse.Namespace) -> int:
    state_path = Path(args.state)
    event_path = Path(args.event).resolve()
    event = read_json(event_path)
    validate_event(event)
    with state_lock(state_path):
        state = read_json(state_path)
        if event["project"] != state["run"]["project"]:
            raise ValueError("Event project does not match State")
        if event["run_id"] != state["run"]["run_id"]:
            raise ValueError("Event run_id does not match State")
        node = state_nodes(state).get(event["node_id"])
        if node is None:
            raise ValueError(f"Event node is not planned: {event['node_id']}")
        if node["capability_id"] != event["capability_id"]:
            raise ValueError("Event capability does not match planned node")
        if node["skill_name"] != event["skill_name"]:
            raise ValueError("Event Skill does not match planned node")
        if node["status"] != "running":
            raise ValueError(f"Only a running node can record an execution event: {node['node_id']}")
        expected_parameters = node.get("parameters") or {}
        configuration = event["configuration"]
        parameter_mismatches = {
            key: {"expected": expected, "actual": configuration.get(key, "<missing>")}
            for key, expected in expected_parameters.items()
            if key not in configuration or configuration[key] != expected
        }
        if parameter_mismatches:
            raise ValueError(f"Event configuration does not match planned node parameters: {parameter_mismatches}")
        readiness_error = node_readiness_error(state, node)
        if readiness_error:
            raise ValueError(readiness_error)
        previous_input = node.get("input_hash")
        previous_config = node.get("config_hash")
        changed = (previous_input and previous_input != event["input_hash"]) or (previous_config and previous_config != event["config_hash"])
        artifacts = []
        resolved_artifacts: list[tuple[dict[str, Any], Path]] = []
        group_membership_path: Path | None = None
        group_registry_path: Path | None = None
        interpretation_path: Path | None = None
        for artifact in event.get("artifacts") or []:
            artifact = dict(artifact)
            artifact_path = (event_path.parent / str(artifact.get("path", ""))).resolve()
            if not artifact_path.is_file():
                raise FileNotFoundError(f"Event artifact was not found: {artifact_path}")
            declared_hash = artifact.get("sha256")
            if declared_hash and file_hash(artifact_path) != declared_hash:
                raise ValueError(f"Event artifact hash mismatch: {artifact_path}")
            resolved_artifacts.append((artifact, artifact_path))
        if not (node["stage"] == "grouping" and event["status"] == "succeeded"):
            set_derived_graph_status(state, {node["node_id"]}, "stale")
        for artifact, artifact_path in resolved_artifacts:
            artifact["resolved_path"] = str(artifact_path)
            artifacts.append(artifact)
            if artifact.get("type") == "group_membership":
                group_membership_path = artifact_path
            if artifact.get("type") == "group_registry":
                group_registry_path = artifact_path
            if artifact.get("type") == "evidence" and artifact_path.exists():
                evidence = read_json(artifact_path)
                evidence_nodes = state["evidence_graph"].setdefault("nodes", [])
                graph_node = {"evidence_id": evidence.get("evidence_id"), "operator_id": evidence.get("operator_id"), "target_group_id": evidence.get("target_group_id"), "grouping_representation": evidence.get("grouping_representation"), "evaluation_representation": evidence.get("evaluation_representation"), "source_node_id": node["node_id"], "artifact_path": str(artifact_path), "status": "active"}
                existing_evidence = next((item for item in evidence_nodes if item.get("evidence_id") == evidence.get("evidence_id")), None)
                if existing_evidence:
                    existing_evidence.update(graph_node)
                else:
                    evidence_nodes.append(graph_node)
                    state["evidence_graph"].setdefault("edges", []).append({"source": node["node_id"], "target": evidence.get("evidence_id"), "relation": "produces_evidence"})
            if artifact.get("type") == "interpretation" and artifact_path.name == "interpretation.json":
                interpretation_path = artifact_path
        if node["stage"] == "grouping" and event["status"] == "succeeded":
            if group_membership_path is None or group_registry_path is None:
                raise ValueError("Successful Grouping event requires group_membership and group_registry artifacts")
            update_group_index(state_path, state, node, group_membership_path, group_registry_path)
        if node["stage"] == "interpretation" and event["status"] == "succeeded":
            if interpretation_path is None:
                raise ValueError("Successful Interpretation event requires interpretation.json")
            interpretation = read_json(interpretation_path)
            if interpretation.get("run_id") != state["run"]["run_id"] or not interpretation.get("interpretation_id"):
                raise ValueError("Interpretation artifact identity does not match State")
            interpretations = state.setdefault("interpretations", [])
            record = {"interpretation_id": interpretation["interpretation_id"], "source_node_id": node["node_id"], "artifact_path": str(interpretation_path), "status": "active", "created_at": interpretation.get("created_at")}
            existing = next((item for item in interpretations if item.get("interpretation_id") == interpretation["interpretation_id"]), None)
            if existing:
                existing.update(record)
            else:
                interpretations.append(record)
        node.update({"status": event["status"], "input_hash": event["input_hash"], "config_hash": event["config_hash"], "configuration": configuration, "artifacts": artifacts, "warnings": event.get("warnings") or [], "started_at": event.get("started_at"), "finished_at": event.get("finished_at")})
        if node.get("phase") == "interpretation_exploration":
            for ledger_item in ensure_exploration_state(state)["interpretation_exploration"]["ledger"]:
                if ledger_item.get("node_id") == node["node_id"]:
                    ledger_item["status"] = event["status"]
                    ledger_item["finished_at"] = event.get("finished_at")
        downstream_skipped: list[str] = []
        if event["status"] in {"failed", "skipped"}:
            reason = "; ".join(str(item) for item in event.get("warnings") or []) or f"Execution event reported {event['status']}"
            node["error" if event["status"] == "failed" else "skip_reason"] = reason
            downstream_skipped = skip_blocked_descendants(
                state,
                node["node_id"],
                f"Required upstream node {node['node_id']} reported {event['status']}: {reason}",
            )
        if changed:
            downstream_ids = downstream(state, node["node_id"])
            for node_id in downstream_ids:
                target = state_nodes(state)[node_id]
                if target["status"] == "succeeded":
                    target["status"] = "stale"
            set_derived_graph_status(state, downstream_ids, "stale")
        append_history(state, "event_recorded", node_id=node["node_id"], status=node["status"], downstream_invalidated=bool(changed), downstream_skipped=downstream_skipped)
        write_state(state_path, state)
    return 0


def runnable_nodes(state: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = state_nodes(state)
    result = []
    for node in nodes.values():
        if node["status"] not in {"pending", "stale"}:
            continue
        if node_readiness_error(state, node) is None:
            result.append(node)
    stage_order = {"description": 0, "grouping": 1, "analysis": 2, "interpretation": 3}
    result.sort(key=lambda node: (node.get("phase") != "wide_shallow", stage_order.get(node["stage"], 99), node["node_id"]))
    limit = int(state["run"]["parallel_limit"])
    running_count = sum(node["status"] == "running" for node in nodes.values())
    return result[:max(0, limit - running_count)]


def cmd_runnable(args: argparse.Namespace) -> int:
    state = read_json(Path(args.state))
    print(json.dumps(runnable_nodes(state), ensure_ascii=False, indent=2))
    return 0


def coarse_run_phase(state: dict[str, Any]) -> str:
    nodes = state["execution_graph"]["nodes"]
    if any(node["status"] == "running" for node in nodes):
        return "executing"
    if not wide_shallow_summary(state)["terminal"]:
        return "initial_breadth"
    if any(node.get("phase") == "interpretation_exploration" and node["status"] in {"pending", "stale"} for node in nodes):
        return "iterative_exploration"
    if any(node["stage"] == "interpretation" and node["status"] == "succeeded" for node in nodes):
        return "interpreted"
    return "ready_for_interpretation"


def cmd_groups(args: argparse.Namespace) -> int:
    state = read_json(Path(args.state))
    registry_path_text = (state.get("group_index") or {}).get("registry_path")
    rows = read_csv_rows(Path(registry_path_text)) if registry_path_text else []
    if args.group_id:
        requested = {value.strip() for value in args.group_id.split(",") if value.strip()}
        rows = [row for row in rows if row.get("group_id") in requested]
    if args.status:
        rows = [row for row in rows if row.get("status") == args.status]
    print(json.dumps({"group_index": state.get("group_index") or {}, "groups": rows}, ensure_ascii=False, indent=2))
    return 0


def cmd_discard_group(args: argparse.Namespace) -> int:
    state_path = Path(args.state)
    requested = {value.strip() for value in args.group_id.split(",") if value.strip()}
    if not requested:
        raise ValueError("At least one Group ID is required")
    with state_lock(state_path):
        state = read_json(state_path)
        registry_path_text = (state.get("group_index") or {}).get("registry_path")
        if not registry_path_text:
            raise ValueError("State has no Group registry")
        registry_path = Path(registry_path_text)
        rows = read_csv_rows(registry_path)
        known = {row.get("group_id") for row in rows}
        unknown = sorted(requested - known)
        if unknown:
            raise ValueError(f"Unknown Group IDs: {unknown}")
        discarded_at = utc_now()
        for row in rows:
            if row.get("group_id") in requested:
                row["status"] = "discarded"
                row["discard_reason"] = args.reason
                row["discarded_at"] = discarded_at
        write_csv_rows(registry_path, GROUP_REGISTRY_FIELDS, rows)
        for item in state.get("domain_graph", {}).get("nodes", []):
            if item.get("group_id") in requested:
                item["status"] = "discarded"
                item["discard_reason"] = args.reason
                item["discarded_at"] = discarded_at
        group_index = state["group_index"]
        group_index["active_group_count"] = sum(row.get("status") == "active" for row in rows)
        group_index["discarded_group_count"] = sum(row.get("status") == "discarded" for row in rows)
        group_index["updated_at"] = discarded_at
        append_history(state, "groups_discarded", group_ids=sorted(requested), reason=args.reason)
        write_state(state_path, state)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    state = ensure_exploration_state(read_json(Path(args.state)))
    counts: dict[str, int] = {}
    for node in state["execution_graph"]["nodes"]:
        counts[node["status"]] = counts.get(node["status"], 0) + 1
    exploration = state["interpretation_exploration"]
    terminal_count = sum(counts.get(status, 0) for status in ("succeeded", "failed", "skipped"))
    print(json.dumps({"run": state["run"], "overview": {"phase": coarse_run_phase(state), "node_count": len(state["execution_graph"]["nodes"]), "terminal_node_count": terminal_count, "remaining_node_count": len(state["execution_graph"]["nodes"]) - terminal_count, "group_count": (state.get("group_index") or {}).get("group_count", 0), "active_group_count": (state.get("group_index") or {}).get("active_group_count", 0), "discarded_group_count": (state.get("group_index") or {}).get("discarded_group_count", 0)}, "status_counts": counts, "runnable": [node["node_id"] for node in runnable_nodes(state)], "wide_shallow_coverage": wide_shallow_summary(state), "group_index": state.get("group_index") or {}, "interpretation_exploration": {"budget": exploration["budget"], "iteration_count": len(exploration["iterations"]), "planned_node_count": len(exploration["ledger"]), "consumed_walltime_minutes": completed_exploration_walltime_minutes(state)}, "updated_at": state["updated_at"]}, ensure_ascii=False, indent=2))
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    state_path = Path(args.state)
    with state_lock(state_path):
        state = read_json(state_path)
        input_path = Path(state["run"]["input"])
        current_hash = file_hash(input_path)
        changed = current_hash != state["run"].get("input_hash")
        if changed:
            state["run"]["input_hash"] = current_hash
            for node in state["execution_graph"]["nodes"]:
                if node["status"] == "succeeded":
                    node["status"] = "stale"
            set_derived_graph_status(state, {node["node_id"] for node in state["execution_graph"]["nodes"]}, "stale")
            append_history(state, "input_changed_on_resume", input_hash=current_hash)
        else:
            append_history(state, "resumed", input_hash=current_hash)
        write_state(state_path, state)
        runnable = runnable_nodes(state)
    print(json.dumps({"input_changed": changed, "runnable": runnable}, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage a CONDUCTOR v4 run State DAG.")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--input", required=True); init.add_argument("--endpoint", required=True); init.add_argument("--higher-is-better", action=argparse.BooleanOptionalAction, required=True)
    init.add_argument("--project", required=True); init.add_argument("--parallel-limit", type=int, required=True); init.add_argument("--assay-column"); init.add_argument("--run-id"); init.add_argument("--output-dir"); init.add_argument("--overwrite", action="store_true"); init.set_defaults(func=cmd_init)
    plan = sub.add_parser("plan-wide"); plan.add_argument("--state", required=True); plan.set_defaults(func=cmd_plan_wide)
    add = sub.add_parser("add"); add.add_argument("--state", required=True); add.add_argument("--capability-id", required=True); add.add_argument("--depends-on"); add.add_argument("--reason"); add.add_argument("--parameters-json", help="JSON object of Skill CLI parameter destinations, for example {\"include_chirality\":true}."); add.add_argument("--require-approval", action="store_true", help="Require human approval because run-specific scale makes this execution expensive."); add.set_defaults(func=cmd_add)
    configure_exploration = sub.add_parser("configure-exploration"); configure_exploration.add_argument("--state", required=True); configure_exploration.add_argument("--max-iterations", type=int, required=True); configure_exploration.add_argument("--max-additional-nodes", type=int, required=True); configure_exploration.add_argument("--walltime-minutes", type=int, required=True); configure_exploration.add_argument("--seed", type=int, required=True); configure_exploration.set_defaults(func=cmd_configure_exploration)
    register_exploration = sub.add_parser("register-exploration"); register_exploration.add_argument("--state", required=True); register_exploration.add_argument("--plan", required=True); register_exploration.set_defaults(func=cmd_register_exploration)
    approve = sub.add_parser("approve"); approve.add_argument("--state", required=True); approve.add_argument("--node-id", required=True); decision = approve.add_mutually_exclusive_group(required=True); decision.add_argument("--approve", action="store_true"); decision.add_argument("--reject", dest="approve", action="store_false"); approve.add_argument("--rationale", required=True); approve.set_defaults(func=cmd_approve)
    start = sub.add_parser("start"); start.add_argument("--state", required=True); start.add_argument("--node-id", required=True); start.set_defaults(func=cmd_start)
    fail = sub.add_parser("fail"); fail.add_argument("--state", required=True); fail.add_argument("--node-id", required=True); fail.add_argument("--reason", required=True); fail.set_defaults(func=cmd_fail)
    record = sub.add_parser("record"); record.add_argument("--state", required=True); record.add_argument("--event", required=True); record.set_defaults(func=cmd_record)
    runnable = sub.add_parser("runnable"); runnable.add_argument("--state", required=True); runnable.set_defaults(func=cmd_runnable)
    status = sub.add_parser("status"); status.add_argument("--state", required=True); status.set_defaults(func=cmd_status)
    groups = sub.add_parser("groups"); groups.add_argument("--state", required=True); groups.add_argument("--group-id", help="Comma-separated Group IDs."); groups.add_argument("--status", choices=["active", "stale", "discarded"]); groups.set_defaults(func=cmd_groups)
    discard_group = sub.add_parser("discard-group"); discard_group.add_argument("--state", required=True); discard_group.add_argument("--group-id", required=True, help="Comma-separated Group IDs."); discard_group.add_argument("--reason", required=True); discard_group.set_defaults(func=cmd_discard_group)
    resume = sub.add_parser("resume"); resume.add_argument("--state", required=True); resume.set_defaults(func=cmd_resume)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if getattr(args, "parallel_limit", 1) < 1:
        raise ValueError("--parallel-limit must be >= 1")
    for name in ("max_iterations", "max_additional_nodes", "walltime_minutes"):
        if hasattr(args, name) and getattr(args, name) < 1:
            raise ValueError(f"--{name.replace('_', '-')} must be >= 1")
    if hasattr(args, "seed") and args.seed < 0:
        raise ValueError("--seed must be >= 0")
    return args.func(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
