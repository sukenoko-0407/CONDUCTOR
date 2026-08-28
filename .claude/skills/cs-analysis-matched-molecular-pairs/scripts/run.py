from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from jsonschema import Draft202012Validator

from mmp_engine import (
    build_native_database,
    extract_pairs,
    load_input,
    sha256_file,
    summary_tables,
    utc_now,
    write_stable_database,
)
from mmp_outputs import (
    comparison_cards,
    database_hash,
    detail_cluster,
    make_reference_cards,
    render_report,
    screen_clusters,
    write_cards,
)


SKILL_DIR = Path(__file__).resolve().parents[1]
CAPABILITY = json.loads((SKILL_DIR / "capability.json").read_text(encoding="utf-8"))


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError("Expected true or false")


def fragment_job_count(available_cpu_cores: int, requested_jobs: int | None) -> int:
    maximum = min(8, int(available_cpu_cores))
    jobs = int(requested_jobs) if requested_jobs is not None else maximum
    if jobs < 1 or jobs > maximum:
        raise ValueError("--fragment-jobs must be between 1 and min(8, --available-cpu-cores)")
    return jobs


def value_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(item) for item in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        return clean_json(value.item())
    return value


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(clean_json(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def validate_json(value: dict[str, Any], schema_name: str) -> None:
    schema = json.loads((SKILL_DIR / "schemas" / schema_name).read_text(encoding="utf-8"))
    schema.pop("$schema", None)
    Draft202012Validator(schema).validate(clean_json(value))


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output-dir")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--conductor", action="store_true")
    parser.add_argument("--project")
    parser.add_argument("--run-id")
    parser.add_argument("--round-id")
    parser.add_argument("--node-id")
    parser.add_argument("--attempt-id")
    parser.add_argument("--source-node-id", action="append", default=[])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Exhaustive exact-core matched molecular pair analysis")
    subparsers = parser.add_subparsers(dest="role", required=True)
    global_parser = subparsers.add_parser("global-build", help="Build the reusable Global MMP database")
    add_common(global_parser)
    global_parser.add_argument("--input", required=True)
    global_parser.add_argument("--id-column", required=True)
    global_parser.add_argument("--smiles-column", required=True)
    global_parser.add_argument("--endpoint-column", required=True)
    global_parser.add_argument("--higher-is-better", required=True, type=parse_bool)
    global_parser.add_argument("--max-compounds", type=int, default=2000)
    global_parser.add_argument("--available-cpu-cores", type=int, default=8)
    global_parser.add_argument("--fragment-jobs", type=int)
    global_parser.add_argument("--num-cuts", type=int, choices=[1, 2, 3], default=2)
    global_parser.add_argument("--extended-search", action="store_true", help="Explicitly allow 3 cuts or radius 3-5.")
    global_parser.add_argument("--cut-smarts", default="default")
    global_parser.add_argument("--min-core-heavy-atoms", type=int, default=8)
    global_parser.add_argument("--min-core-fraction", type=float, default=.50)
    global_parser.add_argument("--max-variable-heavy-atoms", type=int, default=10)
    global_parser.add_argument("--min-radius", type=int, default=0)
    global_parser.add_argument("--max-radius", type=int, default=2)

    screen = subparsers.add_parser("local-screen", help="Screen all Clusters using an existing Global database")
    add_common(screen)
    screen.add_argument("--mmp-database", required=True)
    screen.add_argument("--cluster-registry")
    screen.add_argument("--cluster-membership", required=True)
    screen.add_argument("--clustering-node-id", action="append", default=[])

    detail = subparsers.add_parser("local-detail", help="Compare one Cluster with Global MMP evidence")
    add_common(detail)
    detail.add_argument("--mmp-database", required=True)
    detail.add_argument("--cluster-membership", required=True)
    detail.add_argument("--cluster-id", required=True)
    detail.add_argument("--clustering-node-id")
    return parser.parse_args()


def validate_context(args: argparse.Namespace) -> None:
    if not args.conductor:
        return
    missing = [name for name in ("project", "run_id", "round_id", "node_id", "attempt_id") if not getattr(args, name)]
    if missing:
        raise ValueError(f"CONDUCTOR mode requires context arguments: {missing}")


def output_directory(args: argparse.Namespace) -> Path:
    if args.output_dir:
        return Path(args.output_dir).resolve()
    timestamp = utc_now().replace(":", "").replace("+00:00", "Z")
    return (Path.cwd() / "results" / "analysis" / CAPABILITY["skill_name"] / timestamp).resolve()


def prepare_output(path: Path, overwrite: bool) -> None:
    path.mkdir(parents=True, exist_ok=True)
    visible = [item for item in path.iterdir() if item.name != "_work"]
    if visible and not overwrite:
        raise FileExistsError(f"Output directory is not empty; use --overwrite: {path}")
    if overwrite:
        allowlist = {
            "mmp_database.sqlite", "mmp_pair_detail.csv", "mmp_storage_profile.json",
            "pair_summary.csv", "transform_summary.csv", "core_summary.csv", "transform_core_summary.csv",
            "context_summary.csv", "coverage_summary.csv", "compound_coverage.csv", "mmp_reference_cards.jsonl",
            "mmp_reference_cards.csv", "mmp_local_screening.csv", "mmp_local_detail_pairs.csv",
            "mmp_global_vs_local.csv", "operator_report.html", "operator_summary.json", "analysis_manifest.json",
            "execution_event.json", "warnings.json", "mmp_result.json", "mmp_query_result.json",
        }
        unexpected = [item.name for item in visible if item.name not in allowlist]
        if unexpected:
            raise FileExistsError(f"Refusing overwrite because output contains unrecognized files: {unexpected[:10]}")
        for item in visible:
            if item.is_file():
                item.unlink()


def export_frame(frame: pd.DataFrame, path: Path, parquet: Path | None = None) -> None:
    frame.to_csv(path, index=False)
    if parquet is not None:
        frame.to_parquet(parquet, index=False)


def payload_mapping(names: list[str]) -> dict[str, str]:
    preferred = {
        "mmp_pair_detail.csv": "mmp_pair_detail",
        "mmp_reference_cards.jsonl": "mmp_reference_cards",
        "mmp_reference_cards.csv": "mmp_reference_cards_csv",
    }
    payloads: dict[str, str] = {}
    for name in names:
        logical_name = preferred.get(name, Path(name).stem)
        if logical_name in payloads:
            raise ValueError(f"MMP artifact logical-name collision: {logical_name}")
        payloads[logical_name] = name
    return payloads


def global_build(args: argparse.Namespace, outdir: Path) -> dict[str, Any]:
    input_path = Path(args.input).resolve()
    valid, coverage, warnings = load_input(input_path, args.id_column, args.smiles_column, args.endpoint_column, args.max_compounds)
    if not (0 < args.min_core_fraction <= 1):
        raise ValueError("--min-core-fraction must satisfy 0 < value <= 1")
    if args.min_core_heavy_atoms < 1 or args.max_variable_heavy_atoms < 1:
        raise ValueError("Core and variable heavy-atom limits must be positive")
    if not (0 <= args.min_radius <= args.max_radius <= 5):
        raise ValueError("Environment radius must satisfy 0 <= min <= max <= 5")
    if not args.extended_search and (args.num_cuts > 2 or args.max_radius > 2):
        raise ValueError("3 cuts or radius 3-5 require explicit --extended-search")
    jobs = fragment_job_count(args.available_cpu_cores, args.fragment_jobs)
    _, native_work = build_native_database(
        valid, outdir / "_work", jobs=jobs, num_cuts=args.num_cuts,
        min_core_heavy_atoms=args.min_core_heavy_atoms,
        extended_core_fraction=args.min_core_fraction,
        min_radius=args.min_radius, max_radius=args.max_radius, cut_smarts=args.cut_smarts,
        max_variable_heavy_atoms=args.max_variable_heavy_atoms,
    )
    endpoint_map = dict(zip(valid["compound_id"], valid["endpoint"]))
    details, contexts, filter_stats = extract_pairs(
        native_work, endpoint_map, higher_is_better=args.higher_is_better,
        min_core_heavy_atoms=args.min_core_heavy_atoms,
        min_core_fraction=args.min_core_fraction,
    )
    parameter_record = {
        "num_cuts": args.num_cuts, "cut_smarts": args.cut_smarts,
        "min_core_heavy_atoms": args.min_core_heavy_atoms,
        "min_core_fraction": args.min_core_fraction,
        "max_variable_heavy_atoms": args.max_variable_heavy_atoms,
        "min_radius": args.min_radius, "max_radius": args.max_radius,
        "extended_search": args.extended_search,
    }
    if len(details):
        details["_compound_pair_key"] = details["compound_id_from"].astype(str) + "\x1f" + details["compound_id_to"].astype(str)
        details["transform_pair_support"] = details.groupby("transform_id")["_compound_pair_key"].transform("nunique")
        details["transform_independent_core_support"] = details.groupby("transform_id")["core_id"].transform("nunique")
        details["core_pair_support"] = details.groupby("core_id")["_compound_pair_key"].transform("nunique")
        details["compound_pair_transform_count"] = details.groupby(["compound_id_from", "compound_id_to"])["transform_id"].transform("nunique")
        compound_support = pd.concat([
            details[["compound_id_from", "mmp_id"]].rename(columns={"compound_id_from": "compound_id"}),
            details[["compound_id_to", "mmp_id"]].rename(columns={"compound_id_to": "compound_id"}),
        ]).groupby("compound_id")["mmp_id"].nunique()
        details["compound_from_mmp_support"] = details["compound_id_from"].map(compound_support)
        details["compound_to_mmp_support"] = details["compound_id_to"].map(compound_support)
        low_support = details["transform_pair_support"] < 3
        details.loc[low_support & details["quality_flags"].eq(""), "quality_flags"] = "low_transform_support"
        details.loc[low_support & details["quality_flags"].ne(""), "quality_flags"] += "|low_transform_support"
        details = details.drop(columns=["_compound_pair_key"])
    details["source_node_id"] = args.node_id or ""
    details["input_sha256"] = sha256_file(input_path)
    details["parameter_hash"] = value_hash(parameter_record)
    details["engine_version"] = "mmpdb-3.1.4"
    summaries = summary_tables(details, contexts, coverage)
    metadata = {
        "schema_version": "1.0.0", "engine": "mmpdb", "engine_version": "3.1.4",
        "input_path": str(input_path), "input_sha256": sha256_file(input_path),
        "id_column": args.id_column, "smiles_column": args.smiles_column,
        "endpoint_column": args.endpoint_column, "higher_is_better": args.higher_is_better,
        "core_policy": {"min_heavy_atoms": args.min_core_heavy_atoms, "min_fraction_both_compounds": args.min_core_fraction, "max_variable_heavy_atoms": args.max_variable_heavy_atoms},
        "fragment_policy": {"num_cuts": args.num_cuts, "cut_smarts": args.cut_smarts, "salt_remover": "<none>", "smallest_transformation_only": False, "symmetric": False, "extended_search": args.extended_search},
        "parameter_hash": value_hash(parameter_record),
        "environment_radius": [args.min_radius, args.max_radius],
        "input_count": int(len(coverage)), "endpoint_available_count": int(coverage["endpoint_available"].sum()),
        "mmp_count": int(len(details)), "filter_stats": filter_stats,
        "created_at": utc_now(),
    }
    export_frame(details, outdir / "mmp_pair_detail.csv")
    coverage.to_csv(outdir / "compound_coverage.csv", index=False)
    for name, frame in summaries.items():
        frame.to_csv(outdir / f"{name}.csv", index=False)
    stable_database = outdir / "mmp_database.sqlite"
    write_stable_database(stable_database, details, contexts, coverage, metadata)
    cards = make_reference_cards(
        details, summaries["transform_summary"], summaries["transform_core_summary"], scope="global",
        core_summary=summaries["core_summary"], context_summary=summaries["context_summary"],
    )
    for card in cards:
        validate_json(card, "mmp_reference_card.schema.json")
    write_cards(cards, outdir)
    counts = {
        "input compounds": len(coverage), "MMP rows": len(details),
        "transforms": int(details["transform_id"].nunique()) if len(details) else 0,
        "exact cores": int(details["core_id"].nunique()) if len(details) else 0,
    }
    artifacts = [
        "mmp_database.sqlite", "mmp_pair_detail.csv",
        "pair_summary.csv", "transform_summary.csv", "core_summary.csv", "transform_core_summary.csv",
        "context_summary.csv", "coverage_summary.csv", "compound_coverage.csv",
        "mmp_reference_cards.jsonl", "mmp_reference_cards.csv",
    ]
    storage_profile = {
        "schema_version": "1.0.0",
        "database_bytes": stable_database.stat().st_size,
        "detail_csv_bytes": (outdir / "mmp_pair_detail.csv").stat().st_size,
        "native_work_database_bytes": native_work.stat().st_size,
        "native_work_database_retained": False,
        "table_rows": {"compounds": int(len(coverage)), "mmp_pairs": int(len(details)), "mmp_contexts": int(len(contexts)), "transforms": int(details["transform_id"].nunique()) if len(details) else 0, "cores": int(details["core_id"].nunique()) if len(details) else 0},
        "filter_stats": filter_stats,
        "created_at": utc_now(),
    }
    write_json(outdir / "mmp_storage_profile.json", storage_profile)
    artifacts.append("mmp_storage_profile.json")
    report = render_report(
        role=args.role, scope_label="Global", endpoint=args.endpoint_column,
        higher_is_better=args.higher_is_better, core_policy=metadata["core_policy"], counts=counts, cards=cards,
        tables=[("Transform summary", summaries["transform_summary"]), ("Core summary", summaries["core_summary"]), ("Transform × Core", summaries["transform_core_summary"])],
        artifact_names=artifacts, limitations=warnings + ["分子標準化・塩除去は実施していません。", "Environment radiusの行は独立したPair supportではありません。"],
    )
    (outdir / "operator_report.html").write_text(report, encoding="utf-8")
    negative_result = not bool(details["favorable_delta"].notna().any()) if len(details) else True
    return {
        "input": str(input_path), "input_hash": sha256_file(input_path), "endpoint": args.endpoint_column,
        "higher_is_better": args.higher_is_better, "scope": "global", "cluster_id": None,
        "primary": "mmp_pair_detail.csv", "counts": counts, "negative_result": negative_result,
        "warnings": warnings, "cards": cards, "artifacts": artifacts,
        "core_policy": metadata["core_policy"], "source_nodes": args.source_node_id, "clustering_node_ids": [],
        "sample_count": int(coverage["endpoint_available"].sum()),
    }


def local_screen(args: argparse.Namespace, outdir: Path) -> dict[str, Any]:
    database = Path(args.mmp_database).resolve()
    membership = Path(args.cluster_membership).resolve()
    registry = Path(args.cluster_registry).resolve() if args.cluster_registry else None
    result, metadata = screen_clusters(database, membership, registry)
    result.to_csv(outdir / "mmp_local_screening.csv", index=False)
    empty_details = pd.DataFrame()
    cards = [{
        "schema_version": "1.0.0", "card_id": f"MRC-{value_hash(['screen', database_hash(database), sha256_file(membership)])[:12].upper()}",
        "category": "coverage", "scope": "cluster-survey", "headline": "全登録ClusterのMMP coverage screening",
        "support": {"cluster_count": len(result), "clusters_with_endpoint_pairs": int((result["endpoint_pair_count"] > 0).sum()) if len(result) else 0},
        "effect": {}, "source_rows": result.head(20)["cluster_id"].tolist() if len(result) else [],
        "quality_flags": ["negative_result"] if result.empty or not bool((result["endpoint_pair_count"] > 0).any()) else [],
    }]
    for card in cards:
        validate_json(card, "mmp_reference_card.schema.json")
    write_cards(cards, outdir)
    counts = {"clusters": len(result), "clusters with MMP": int((result["within_pair_count"] > 0).sum()) if len(result) else 0}
    artifacts = ["mmp_local_screening.csv", "mmp_reference_cards.jsonl", "mmp_reference_cards.csv"]
    (outdir / "operator_report.html").write_text(render_report(
        role=args.role, scope_label="全Cluster screening", endpoint=str(metadata.get("endpoint_column", "unknown")),
        higher_is_better=bool(metadata.get("higher_is_better", True)), core_policy=metadata.get("core_policy", {}), counts=counts, cards=cards,
        tables=[("Cluster screening", result)], artifact_names=artifacts,
        limitations=["Cluster間の重複は独立再現として扱いません。", "Screeningは候補選定用であり、詳細なGlobal対Local比較ではありません。"],
    ), encoding="utf-8")
    negative_result = result.empty or not bool((result["endpoint_pair_count"] > 0).any())
    query = {"schema_version": "1.0.0", "role": args.role, "query_spec_hash": value_hash([database_hash(database), sha256_file(membership), "all-clusters"]), "database_sha256": database_hash(database), "negative_result": negative_result, "rows": len(result), "created_at": utc_now()}
    validate_json(query, "mmp_query_result.schema.json")
    write_json(outdir / "mmp_query_result.json", query)
    return {
        "input": str(database), "input_hash": database_hash(database), "endpoint": str(metadata.get("endpoint_column", "unknown")),
        "higher_is_better": bool(metadata.get("higher_is_better", True)), "scope": "cluster-survey", "cluster_id": None,
        "primary": "mmp_local_screening.csv", "counts": counts, "negative_result": negative_result,
        "warnings": [], "cards": cards, "artifacts": artifacts + ["mmp_query_result.json"],
        "core_policy": metadata.get("core_policy", {}), "source_nodes": args.source_node_id + args.clustering_node_id,
        "clustering_node_ids": args.clustering_node_id,
        "sample_count": int(metadata.get("endpoint_available_count", 0)),
    }


def local_detail(args: argparse.Namespace, outdir: Path) -> dict[str, Any]:
    database = Path(args.mmp_database).resolve()
    membership = Path(args.cluster_membership).resolve()
    details, comparison, metadata = detail_cluster(database, membership, args.cluster_id)
    details.to_csv(outdir / "mmp_local_detail_pairs.csv", index=False)
    comparison.to_csv(outdir / "mmp_global_vs_local.csv", index=False)
    eligible_details = details.copy()
    local_summaries = summary_tables(eligible_details, pd.DataFrame(), pd.DataFrame({"valid_smiles": [], "endpoint_available": []})) if len(eligible_details) else {}
    transforms = local_summaries.get("transform_summary", pd.DataFrame())
    transform_core = local_summaries.get("transform_core_summary", pd.DataFrame())
    cards = make_reference_cards(eligible_details, transforms, transform_core, scope=f"cluster:{args.cluster_id}")
    cards = (comparison_cards(comparison, details, f"cluster:{args.cluster_id}") + cards)[:100]
    for card in cards:
        validate_json(card, "mmp_reference_card.schema.json")
    write_cards(cards, outdir)
    counts = {"cluster size": metadata.get("cluster_size", 0), "within-cluster MMP": len(details), "transforms": int(details["transform_id"].nunique()) if len(details) else 0}
    artifacts = ["mmp_local_detail_pairs.csv", "mmp_global_vs_local.csv", "mmp_reference_cards.jsonl", "mmp_reference_cards.csv"]
    (outdir / "operator_report.html").write_text(render_report(
        role=args.role, scope_label=f"Cluster {args.cluster_id}", endpoint=str(metadata.get("endpoint_column", "unknown")),
        higher_is_better=bool(metadata.get("higher_is_better", True)), core_policy=metadata.get("core_policy", {}), counts=counts, cards=cards,
        tables=[("Local MMP pairs", details), ("Global vs Local", comparison)], artifact_names=artifacts,
        limitations=["LocalはCluster membershipによるGlobal DBのread-only絞り込みです。", "該当Pairがない場合も有効なNegative Resultです。"],
    ), encoding="utf-8")
    negative_result = not bool(eligible_details["favorable_delta"].notna().any()) if len(eligible_details) else True
    query = {"schema_version": "1.0.0", "role": args.role, "query_spec_hash": value_hash([database_hash(database), sha256_file(membership), args.cluster_id]), "database_sha256": database_hash(database), "negative_result": negative_result, "rows": len(details), "created_at": utc_now()}
    validate_json(query, "mmp_query_result.schema.json")
    write_json(outdir / "mmp_query_result.json", query)
    sources = args.source_node_id + ([args.clustering_node_id] if args.clustering_node_id else [])
    return {
        "input": str(database), "input_hash": database_hash(database), "endpoint": str(metadata.get("endpoint_column", "unknown")),
        "higher_is_better": bool(metadata.get("higher_is_better", True)), "scope": "within-cluster", "cluster_id": args.cluster_id,
        "primary": "mmp_local_detail_pairs.csv", "counts": counts, "negative_result": negative_result,
        "warnings": [], "cards": cards, "artifacts": artifacts + ["mmp_query_result.json"],
        "core_policy": metadata.get("core_policy", {}), "source_nodes": sources,
        "clustering_node_ids": [args.clustering_node_id] if args.clustering_node_id else [],
        "sample_count": int(len(set(details.loc[details["endpoint_from"].notna(), "compound_id_from"]) | set(details.loc[details["endpoint_to"].notna(), "compound_id_to"]))) if len(details) else 0,
    }


def conductor_contract(args: argparse.Namespace, outdir: Path, result: dict[str, Any], started_at: str) -> None:
    primary = outdir / result["primary"]
    result_ref = f"{args.node_id}@{args.attempt_id}"
    if result["cluster_id"]:
        result_ref += f"/{result['cluster_id']}"
    scope = {"mode": result["scope"], "target_cluster_id": result["cluster_id"]}
    operator_summary = {
        "schema_version": "1.0.0", "result_ref": result_ref, "node_id": args.node_id,
        "attempt_id": args.attempt_id, "operator_id": "A014", "operator_name": CAPABILITY["display_name"],
        "run_id": args.run_id, "round_id": args.round_id, "scope": scope,
        "scope_context": {"description_node_ids": [], "clustering_node_ids": result.get("clustering_node_ids", []), "cluster_ids": [result["cluster_id"]] if result["cluster_id"] else []},
        "sample_count": int(result.get("sample_count", 0)),
        "endpoint": {"column": result["endpoint"], "higher_is_better": result["higher_is_better"]},
        "metric": "favorable_endpoint_delta", "headline": ("該当するMMP evidenceは得られませんでした。" if result["negative_result"] else f"{args.role}でMMP evidenceを抽出しました。"),
        "key_metrics": {**result["counts"], "negative_result": result["negative_result"], "mmp_reference_candidates": result["cards"][:20]},
        "top_records": result["cards"][:20],
        "limitations": result["warnings"] + ["Environment radius is nested context, not independent pair support.", "Reference cards are candidates rather than final scientific conclusions."],
        "warnings": result["warnings"],
        "source_nodes": list(dict.fromkeys(node for node in result["source_nodes"] if node)),
        "primary_artifact": {"path": primary.name, "sha256": sha256_file(primary)}, "created_at": utc_now(),
    }
    validate_json(operator_summary, "operator_summary.schema.json")
    write_json(outdir / "operator_summary.json", operator_summary)
    all_artifacts = list(dict.fromkeys(result["artifacts"] + ["operator_report.html", "operator_summary.json", "mmp_result.json"]))
    manifest = {
        "schema_version": "2.0.0", "conductor_version": "0.1.8", "artifact_stage": "analysis",
        "run_id": args.run_id, "node_id": args.node_id, "attempt_id": args.attempt_id,
        "capability_id": "A014", "operator_id": "A014", "skill_name": CAPABILITY["skill_name"],
        "skill_version": CAPABILITY["version"], "input": result["input"], "input_hash": result["input_hash"],
        "value_semantics": f"matched_molecular_pairs:{args.role}", "natural_metric": "favorable_endpoint_delta",
        "role": args.role, "scope": scope, "output": primary.name, "payloads": payload_mapping(result["artifacts"]),
        "warnings": result["warnings"], "created_at": utc_now(), "configuration": clean_json(vars(args)),
    }
    validate_json(manifest, "artifact_manifest.schema.json")
    write_json(outdir / "analysis_manifest.json", manifest)
    all_artifacts.append("analysis_manifest.json")
    event_artifacts = []
    type_map = {primary.name: "operator_result", "operator_report.html": "operator_report", "operator_summary.json": "operator_summary", "analysis_manifest.json": "manifest"}
    for name in all_artifacts:
        path = outdir / name
        event_artifacts.append({"type": type_map.get(name, f"mmp_payload:{name}"), "path": name, "sha256": sha256_file(path)})
    event = {
        "schema_version": "2.0.0", "project": args.project, "run_id": args.run_id,
        "round_id": args.round_id, "node_id": args.node_id, "attempt_id": args.attempt_id,
        "capability_id": "A014", "skill_name": CAPABILITY["skill_name"], "status": "succeeded",
        "input_hash": result["input_hash"], "config_hash": value_hash(clean_json(vars(args))),
        "configuration": clean_json(vars(args)), "artifacts": event_artifacts,
        "warnings": result["warnings"], "started_at": started_at, "finished_at": utc_now(),
    }
    validate_json(event, "execution_event.schema.json")
    write_json(outdir / "execution_event.json", event)


def run() -> int:
    started_at = utc_now()
    args = parse_args()
    validate_context(args)
    outdir = output_directory(args)
    prepare_output(outdir, args.overwrite)
    if args.role == "global-build":
        result = global_build(args, outdir)
    elif args.role == "local-screen":
        result = local_screen(args, outdir)
    else:
        result = local_detail(args, outdir)
    mmp_result = {
        "schema_version": "1.0.0", "role": args.role, "scope": result["scope"],
        "cluster_id": result["cluster_id"], "negative_result": result["negative_result"],
        "endpoint": result["endpoint"], "higher_is_better": result["higher_is_better"],
        "counts": result["counts"], "core_policy": result["core_policy"],
        "artifacts": {name: name for name in result["artifacts"]}, "created_at": utc_now(),
    }
    validate_json(mmp_result, "mmp_result.schema.json")
    write_json(outdir / "mmp_result.json", mmp_result)
    if args.conductor:
        result["artifacts"] = list(dict.fromkeys(result["artifacts"] + ["mmp_result.json"]))
        conductor_contract(args, outdir, result, started_at)
    if args.role == "global-build":
        # Keep expensive native intermediates until every canonical artifact,
        # report, and CONDUCTOR contract has been written successfully.
        shutil.rmtree(outdir / "_work", ignore_errors=True)
    print(outdir / result["primary"])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
