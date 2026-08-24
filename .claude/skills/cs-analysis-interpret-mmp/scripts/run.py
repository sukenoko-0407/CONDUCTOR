from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from render import clean_json, render_html, render_markdown, report_json


VERSION = "0.1.6"
REQUEST_PATTERN = re.compile(r"^MMPREQ(\d{6,})$")
NODE_PATTERN = re.compile(r"^N\d{6}$")
CLUSTER_PATTERN = re.compile(r"^C\d{6}$")
ROUND_PATTERN = re.compile(r"^RND\d{4}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def write_json(path: Path, value: Any) -> None:
    atomic_text(path, json.dumps(clean_json(value), ensure_ascii=False, indent=2) + "\n")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_inside(root: Path, value: str) -> Path:
    raw = Path(value).expanduser()
    resolved = (raw if raw.is_absolute() else root / raw).resolve()
    if not is_relative_to(resolved, root.resolve()):
        raise PermissionError(f"Path escapes the Run Root: {value}")
    return resolved


def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def validate_frozen_run(value: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    root = Path(value).expanduser().resolve()
    control_path = root / "conductor_control.json"
    snapshot_path = root / "runtime" / "dag_snapshot.json"
    if not control_path.is_file() or not snapshot_path.is_file():
        raise FileNotFoundError("conductor_control.json or runtime/dag_snapshot.json is missing")
    control, snapshot = load_json(control_path), load_json(snapshot_path)
    if control.get("conductor_version") != VERSION or not isinstance(snapshot.get("nodes"), list):
        raise ValueError(f"The supplied directory is not a CONDUCTOR {VERSION} Run Root")
    state = control.get("round_state")
    if state in {"ACTIVE", "FINALIZING"}:
        raise RuntimeError(f"Run is not frozen: round_state={state}")
    if state not in {"AWAITING_HUMAN_REVIEW", "CLOSED", "NO_ACTIVE_ROUND"}:
        raise RuntimeError(f"Unsupported frozen Round state: {state}")
    running = [node.get("node_id") for node in snapshot["nodes"] if node.get("status") == "running"]
    if running:
        raise RuntimeError("Run has running Nodes: " + ", ".join(map(str, running[:20])))
    lease = control.get("lease") or {}
    expiry = parse_datetime(lease.get("expires_at"))
    if lease.get("owner_id") and (expiry is None or expiry > datetime.now(timezone.utc)):
        raise RuntimeError(f"Run has a live Orchestrator lease: {lease.get('owner_id')}")
    return root, control, snapshot


def run_inventory(root: Path) -> list[dict[str, Any]]:
    writable = (root / "mmp_interpretation").resolve()
    rows: list[dict[str, Any]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if is_relative_to(resolved, writable):
            continue
        stat = resolved.stat()
        rows.append({"path": resolved.relative_to(root).as_posix(), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns})
    return sorted(rows, key=lambda row: row["path"])


def allocate_request(root: Path) -> tuple[str, Path]:
    parent = root / "mmp_interpretation"
    parent.mkdir(parents=True, exist_ok=True)
    serials = [int(match.group(1)) for child in parent.iterdir() if child.is_dir() and (match := REQUEST_PATTERN.match(child.name))]
    serial = max(serials, default=0) + 1
    while True:
        request_id = f"MMPREQ{serial:06d}"
        request = parent / request_id
        try:
            request.mkdir()
            return request_id, request.resolve()
        except FileExistsError:
            serial += 1


def node_number(node: dict[str, Any]) -> int:
    match = re.search(r"(\d+)$", str(node.get("node_id", "")))
    return int(match.group(1)) if match else -1


def node_output(root: Path, node: dict[str, Any]) -> Path:
    value = node.get("output_ref")
    if not isinstance(value, str) or not value:
        raise ValueError(f"Node has no output_ref: {node.get('node_id')}")
    output = resolve_inside(root, value)
    if not output.is_dir():
        raise FileNotFoundError(output)
    return output


def select_global_mmp(root: Path, snapshot: dict[str, Any], round_id: str, requested: str | None) -> tuple[dict[str, Any], Path]:
    candidates = [
        node for node in snapshot["nodes"]
        if node.get("kind") == "analysis"
        and node.get("capability_id") == "A014"
        and node.get("status") == "succeeded"
        and (node.get("parameters") or {}).get("role") == "global-build"
    ]
    if requested:
        candidates = [node for node in candidates if node.get("node_id") == requested]
    else:
        candidates = [
            node for node in candidates
            if node.get("assigned_round") == round_id or node.get("created_in_round") == round_id
        ]
    if not candidates:
        if requested:
            raise RuntimeError(f"The requested successful Global A014 Node is unavailable: {requested}")
        raise RuntimeError(
            f"No successful Global A014 Node was produced in {round_id}; "
            "use --mmp-node-id only when the human explicitly requests reuse of an older Global Database"
        )
    node = max(candidates, key=node_number)
    database = node_output(root, node) / "mmp_database.sqlite"
    if not database.is_file():
        raise FileNotFoundError(f"Global A014 database is missing: {database}")
    return node, database


def load_mmp_database(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        details = pd.read_sql_query(
            """
            SELECT p.mmp_id,
                   cf.compound_id AS compound_id_from, ct.compound_id AS compound_id_to,
                   p.favorable_delta,
                   t.transform_id, t.transform_smirks,
                   c.core_id
              FROM mmp_pairs p
              JOIN compounds cf ON cf.compound_key = p.compound_from_key
              JOIN compounds ct ON ct.compound_key = p.compound_to_key
              JOIN transforms t ON t.transform_key = p.transform_key
              JOIN cores c ON c.core_key = p.core_key
             ORDER BY p.pair_key
            """,
            connection,
        )
        metadata = {key: json.loads(value) for key, value in connection.execute("SELECT key, value_json FROM metadata")}
    details["compound_id_from"] = details["compound_id_from"].astype(str)
    details["compound_id_to"] = details["compound_id_to"].astype(str)
    details["favorable_delta"] = pd.to_numeric(details["favorable_delta"], errors="coerce")
    return details, metadata


def load_membership(path: Path) -> tuple[pd.DataFrame, str, list[str]]:
    frame = pd.read_csv(path, dtype="string")
    cluster_columns = [column for column in frame.columns if CLUSTER_PATTERN.match(str(column))]
    if not cluster_columns:
        raise ValueError("runtime/cluster_membership.csv has no canonical Cluster columns")
    id_column = "compound_id" if "compound_id" in frame.columns else str(frame.columns[0])
    frame[id_column] = frame[id_column].astype(str)
    for column in cluster_columns:
        frame[column] = frame[column].fillna("false").str.lower().isin({"1", "true", "t", "yes", "y"})
    return frame, id_column, cluster_columns


def select_clusters(
    root: Path,
    snapshot: dict[str, Any],
    requested_nodes: list[str],
    requested_clusters: list[str],
) -> tuple[pd.DataFrame, str, list[dict[str, Any]]]:
    matrix, id_column, columns = load_membership(root / "runtime" / "cluster_membership.csv")
    lookup = {node.get("node_id"): node for node in snapshot["nodes"]}
    latest = {row["cluster_id"]: row for row in read_jsonl(root / "runtime" / "cluster_registry.jsonl") if row.get("cluster_id")}
    rows = [
        row for row in latest.values()
        if row.get("status", "active") == "active"
        and row.get("cluster_id") in columns
        and int(row.get("compound_count", 0)) >= 5
        and (lookup.get(row.get("source_node_id")) or {}).get("status") == "succeeded"
    ]
    if requested_nodes:
        rows = [row for row in rows if row.get("source_node_id") in set(requested_nodes)]
    if requested_clusters:
        requested = set(requested_clusters)
        missing = sorted(requested - {row.get("cluster_id") for row in rows})
        if missing:
            raise ValueError("Requested Clusters are unavailable or inactive: " + ", ".join(missing))
        rows = [row for row in rows if row.get("cluster_id") in requested]
    if not rows:
        raise RuntimeError("No eligible canonical Clusters were selected")
    return matrix, id_column, sorted(rows, key=lambda row: (str(row.get("source_node_id")), str(row.get("cluster_id"))))


STAT_COLUMNS = [
    "mmp_instance_count", "pair_count", "endpoint_pair_count", "independent_compound_count",
    "independent_core_count", "median", "q1", "q3", "iqr", "mad", "direction_consistency",
]

COMPARISON_COLUMNS = [
    "clustering_node_id", "clustering_capability_id", "cluster_id",
    "transform_id", "transform_smirks",
    *[f"local_{column}" for column in STAT_COLUMNS],
    *[f"global_{column}" for column in STAT_COLUMNS],
    *[f"outside_{column}" for column in STAT_COLUMNS],
    "cluster_size", "clustering_overlap_detected", "boundary_pair_count",
    "shared_core_count", "local_minus_global", "local_minus_outside",
    "dispersion_ratio", "dispersion_reduction",
    "direction_reversal_vs_global", "direction_reversal_vs_outside",
    "eligible_local", "eligible_outside", "core_context_flag",
]

METHOD_COLUMNS = [
    "clustering_node_id", "clustering_capability_id", "transform_id", "transform_smirks",
    "eligible_cluster_count", "overlap_detected", "global_endpoint_pair_count",
    "global_iqr", "weighted_local_iqr", "dispersion_reduction",
    "between_cluster_median_iqr", "between_cluster_median_range",
    "pair_coverage", "variance_comparison_eligible",
]


def transform_summary(frame: pd.DataFrame, prefix: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (transform_id, smirks), group in frame.groupby(["transform_id", "transform_smirks"], dropna=False):
        group = group.copy()
        pair_effects = group.groupby(["compound_id_from", "compound_id_to"], dropna=False)["favorable_delta"].median().dropna()
        median = float(pair_effects.median()) if len(pair_effects) else math.nan
        rows.append({
            "transform_id": transform_id,
            "transform_smirks": smirks,
            f"{prefix}_mmp_instance_count": int(len(group)),
            f"{prefix}_pair_count": int(group[["compound_id_from", "compound_id_to"]].drop_duplicates().shape[0]),
            f"{prefix}_endpoint_pair_count": int(len(pair_effects)),
            f"{prefix}_independent_compound_count": int(len(set(group["compound_id_from"]) | set(group["compound_id_to"]))),
            f"{prefix}_independent_core_count": int(group["core_id"].nunique()),
            f"{prefix}_median": median,
            f"{prefix}_q1": float(pair_effects.quantile(.25)) if len(pair_effects) else math.nan,
            f"{prefix}_q3": float(pair_effects.quantile(.75)) if len(pair_effects) else math.nan,
            f"{prefix}_iqr": float(pair_effects.quantile(.75) - pair_effects.quantile(.25)) if len(pair_effects) else math.nan,
            f"{prefix}_mad": float((pair_effects - median).abs().median()) if len(pair_effects) else math.nan,
            f"{prefix}_direction_consistency": float(max((pair_effects > 0).mean(), (pair_effects < 0).mean())) if len(pair_effects) else math.nan,
        })
    columns = ["transform_id", "transform_smirks", *[f"{prefix}_{column}" for column in STAT_COLUMNS]]
    return pd.DataFrame(rows, columns=columns)


def source_overlap(matrix: pd.DataFrame, source_clusters: list[str]) -> bool:
    if len(source_clusters) < 2:
        return False
    return bool((matrix[source_clusters].astype(int).sum(axis=1) > 1).any())


def derive_tables(
    details: pd.DataFrame,
    matrix: pd.DataFrame,
    id_column: str,
    registry: list[dict[str, Any]],
    min_local_pairs: int,
    min_outside_pairs: int,
) -> dict[str, pd.DataFrame]:
    valid = details[details["favorable_delta"].notna()].copy()
    global_summary = transform_summary(valid, "global")
    by_source: dict[str, list[dict[str, Any]]] = {}
    for row in registry:
        by_source.setdefault(str(row.get("source_node_id")), []).append(row)
    overlap = {source: source_overlap(matrix, [str(row["cluster_id"]) for row in rows]) for source, rows in by_source.items()}
    comparisons: list[pd.DataFrame] = []
    screening: list[dict[str, Any]] = []
    for origin in registry:
        cluster_id = str(origin["cluster_id"])
        source_node = str(origin.get("source_node_id"))
        members = set(matrix.loc[matrix[cluster_id], id_column].astype(str))
        left = valid["compound_id_from"].isin(members)
        right = valid["compound_id_to"].isin(members)
        local = valid[left & right].copy()
        outside = valid[~left & ~right].copy()
        boundary = valid[left ^ right].copy()
        local_summary = transform_summary(local, "local")
        outside_summary = transform_summary(outside, "outside")
        combined = local_summary.merge(global_summary, on=["transform_id", "transform_smirks"], how="left")
        combined = combined.merge(outside_summary, on=["transform_id", "transform_smirks"], how="left")
        if len(combined):
            local_cores = {key: set(group["core_id"].astype(str)) for key, group in local.groupby("transform_id")}
            outside_cores = {key: set(group["core_id"].astype(str)) for key, group in outside.groupby("transform_id")}
            combined.insert(0, "cluster_id", cluster_id)
            combined.insert(0, "clustering_node_id", source_node)
            combined.insert(1, "clustering_capability_id", str(origin.get("clustering_capability_id", "")))
            combined["cluster_size"] = len(members)
            combined["clustering_overlap_detected"] = overlap[source_node]
            combined["boundary_pair_count"] = int(boundary[["compound_id_from", "compound_id_to"]].drop_duplicates().shape[0])
            combined["shared_core_count"] = combined["transform_id"].map(lambda key: len(local_cores.get(key, set()) & outside_cores.get(key, set())))
            combined["local_minus_global"] = combined["local_median"] - combined["global_median"]
            combined["local_minus_outside"] = combined["local_median"] - combined["outside_median"]
            combined["dispersion_ratio"] = np.where(combined["global_iqr"] > 0, combined["local_iqr"] / combined["global_iqr"], np.nan)
            combined["dispersion_reduction"] = 1.0 - combined["dispersion_ratio"]
            combined["direction_reversal_vs_global"] = (
                combined["local_median"].notna() & combined["global_median"].notna()
                & (combined["local_median"] != 0) & (combined["global_median"] != 0)
                & (np.sign(combined["local_median"]) != np.sign(combined["global_median"]))
            )
            combined["direction_reversal_vs_outside"] = (
                combined["local_median"].notna() & combined["outside_median"].notna()
                & (combined["local_median"] != 0) & (combined["outside_median"] != 0)
                & (np.sign(combined["local_median"]) != np.sign(combined["outside_median"]))
            )
            combined["eligible_local"] = combined["local_endpoint_pair_count"] >= min_local_pairs
            combined["eligible_outside"] = combined["outside_endpoint_pair_count"] >= min_outside_pairs
            combined["core_context_flag"] = np.where(combined["shared_core_count"] > 0, "shared_exact_core_available", "different_or_unshared_exact_core")
            comparisons.append(combined)
        screening.append({
            "clustering_node_id": source_node,
            "clustering_capability_id": str(origin.get("clustering_capability_id", "")),
            "source_description_capability_ids": "|".join(map(str, origin.get("source_description_capability_ids", []))),
            "cluster_id": cluster_id,
            "cluster_size": len(members),
            "overlap_detected": overlap[source_node],
            "within_mmp_instance_count": len(local),
            "within_pair_count": int(local[["compound_id_from", "compound_id_to"]].drop_duplicates().shape[0]),
            "boundary_pair_count": int(boundary[["compound_id_from", "compound_id_to"]].drop_duplicates().shape[0]),
            "transform_count": int(local["transform_id"].nunique()),
            "exact_core_count": int(local["core_id"].nunique()),
            "eligible_transform_count": int((transform_summary(local, "local")["local_endpoint_pair_count"] >= min_local_pairs).sum()) if len(local) else 0,
        })
    comparison = pd.concat(comparisons, ignore_index=True) if comparisons else pd.DataFrame(columns=COMPARISON_COLUMNS)
    comparison = comparison.reindex(columns=COMPARISON_COLUMNS)
    screen = pd.DataFrame(screening)
    method_rows: list[dict[str, Any]] = []
    if len(comparison):
        eligible = comparison[comparison["eligible_local"]].copy()
        for (source_node, capability, transform_id, smirks), group in eligible.groupby(
            ["clustering_node_id", "clustering_capability_id", "transform_id", "transform_smirks"], dropna=False
        ):
            weights = pd.to_numeric(group["local_endpoint_pair_count"], errors="coerce").fillna(0).to_numpy(dtype=float)
            local_iqr = pd.to_numeric(group["local_iqr"], errors="coerce").to_numpy(dtype=float)
            finite = np.isfinite(local_iqr) & (weights > 0)
            weighted_iqr = float(np.average(local_iqr[finite], weights=weights[finite])) if finite.any() else math.nan
            medians = pd.to_numeric(group["local_median"], errors="coerce").dropna()
            global_iqr = float(group["global_iqr"].dropna().iloc[0]) if group["global_iqr"].notna().any() else math.nan
            is_overlap = bool(group["clustering_overlap_detected"].any())
            total_pairs = float(group["local_endpoint_pair_count"].sum())
            global_pairs = float(group["global_endpoint_pair_count"].dropna().iloc[0]) if group["global_endpoint_pair_count"].notna().any() else math.nan
            coverage = min(1.0, total_pairs / global_pairs) if not is_overlap and global_pairs > 0 else math.nan
            method_rows.append({
                "clustering_node_id": source_node,
                "clustering_capability_id": capability,
                "transform_id": transform_id,
                "transform_smirks": smirks,
                "eligible_cluster_count": int(group["cluster_id"].nunique()),
                "overlap_detected": is_overlap,
                "global_endpoint_pair_count": int(global_pairs) if math.isfinite(global_pairs) else 0,
                "global_iqr": global_iqr,
                "weighted_local_iqr": weighted_iqr,
                "dispersion_reduction": 1.0 - weighted_iqr / global_iqr if global_iqr > 0 and math.isfinite(weighted_iqr) else math.nan,
                "between_cluster_median_iqr": float(medians.quantile(.75) - medians.quantile(.25)) if len(medians) >= 2 else math.nan,
                "between_cluster_median_range": float(medians.max() - medians.min()) if len(medians) >= 2 else math.nan,
                "pair_coverage": coverage,
                "variance_comparison_eligible": bool(not is_overlap and len(medians) >= 2 and global_iqr > 0),
            })
    method = pd.DataFrame(method_rows, columns=METHOD_COLUMNS)
    if len(method):
        variance = method[method["variance_comparison_eligible"] & (method["dispersion_reduction"] > 0)].copy()
        variance = variance.sort_values(["dispersion_reduction", "pair_coverage", "eligible_cluster_count"], ascending=[False, False, False])
    else:
        variance = method.copy()
    if len(comparison):
        specific = comparison[comparison["eligible_local"] & comparison["eligible_outside"]].copy()
        specific["absolute_local_minus_outside"] = specific["local_minus_outside"].abs()
        specific = specific.sort_values(
            ["direction_reversal_vs_outside", "absolute_local_minus_outside", "local_endpoint_pair_count", "local_direction_consistency"],
            ascending=[False, False, False, False],
        )
        reversals = specific[specific["direction_reversal_vs_outside"]].copy()
    else:
        specific = pd.DataFrame(columns=[*COMPARISON_COLUMNS, "absolute_local_minus_outside"])
        reversals = specific.copy()
    overview_rows: list[dict[str, Any]] = []
    for source_node, group in screen.groupby("clustering_node_id", dropna=False):
        method_group = method[method["clustering_node_id"] == source_node] if len(method) else pd.DataFrame()
        overview_rows.append({
            "clustering_node_id": source_node,
            "clustering_capability_id": str(group["clustering_capability_id"].iloc[0]),
            "cluster_count": int(group["cluster_id"].nunique()),
            "overlap_detected": bool(group["overlap_detected"].any()),
            "clusters_with_mmp": int((group["within_pair_count"] > 0).sum()),
            "eligible_transform_comparisons": int(method_group["variance_comparison_eligible"].sum()) if len(method_group) else 0,
        })
    return {
        "global_transform_summary": global_summary,
        "cluster_screening": screen,
        "cluster_transform_summary": comparison,
        "clustering_transform_summary": method,
        "variance_collapse": variance,
        "cluster_specific": specific,
        "direction_reversal": reversals,
        "clustering_overview": pd.DataFrame(overview_rows),
    }


def records(frame: pd.DataFrame, limit: int = 20) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    return clean_json(frame.head(limit).to_dict(orient="records"))


def default_draft(context: dict[str, Any]) -> dict[str, Any]:
    previews = context["previews"]
    summary = context["summary"]
    observations: list[dict[str, Any]] = []
    for row in previews.get("variance_collapse", [])[:3]:
        observations.append({
            "title": f"{row['clustering_node_id']}で{row['transform_id']}のCluster内分散が縮小",
            "category": "variance_collapse",
            "observation": f"Global IQR={row.get('global_iqr')}に対し、eligible Clusterのpair数加重Local IQR={row.get('weighted_local_iqr')}、dispersion reduction={row.get('dispersion_reduction')}でした。",
            "interpretation": "このClusteringが当該Transformの効果修飾Contextを部分的に分離している候補です。Cluster中央値間の差とcoverageを併せて確認する必要があります。",
            "evidence": [f"clustering_transform_summary.csv:{row['clustering_node_id']}:{row['transform_id']}"],
            "limitations": ["記述的な分散比較であり、少標本化だけでもIQRは変動します。", "Exact CoreとEnvironment構成の違いを固定した比較ではありません。"],
        })
    for row in previews.get("cluster_specific", [])[:3]:
        observations.append({
            "title": f"{row['cluster_id']}で{row['transform_id']}の効果がGlobal外部から乖離",
            "category": "cluster_specific",
            "observation": f"Local median={row.get('local_median')}、Outside median={row.get('outside_median')}、Local-minus-Outside={row.get('local_minus_outside')}でした。",
            "interpretation": "このClusterに固有の構造ContextでTransform効果が増幅または減弱する候補です。shared Exact Coreの有無を確認して解釈してください。",
            "evidence": [f"cluster_transform_summary.csv:{row['cluster_id']}:{row['transform_id']}"],
            "limitations": [f"Local support={row.get('local_endpoint_pair_count')}、Outside support={row.get('outside_endpoint_pair_count')}です。", f"shared Exact Core count={row.get('shared_core_count')}です。"],
        })
    for row in previews.get("direction_reversal", [])[:2]:
        observations.append({
            "title": f"{row['cluster_id']}で{row['transform_id']}の良好方向がOutsideと反転",
            "category": "direction_reversal",
            "observation": f"Local median={row.get('local_median')}に対しOutside median={row.get('outside_median')}で、符号が反転しました。",
            "interpretation": "Transformの効果方向がCluster Contextに依存する候補であり、設計判断へ直接一般化せずExact Core単位で再確認する価値があります。",
            "evidence": [f"candidate_direction_reversal.csv:{row['cluster_id']}:{row['transform_id']}"],
            "limitations": ["LocalとOutsideのassay条件が比較可能であることを前提とします。", "同じ化合物またはCoreへの依存を独立再現として数えません。"],
        })
    if not observations:
        observations.append({
            "title": "支持条件を満たすGlobal–Local MMP候補は限定的",
            "category": "negative_result",
            "observation": "指定したClustering／Cluster範囲では、support条件を満たす分散縮小、Cluster固有效果、方向反転候補が得られませんでした。",
            "interpretation": "これはMMP解析失敗ではなく、現在のGlobal DBとCluster membershipから明瞭な局所差を支持できなかったnegative resultです。",
            "evidence": ["cluster_screening.csv"],
            "limitations": ["MMP coverageが低いClusterでは、効果がないこととデータがないことを区別できません。"],
        })
    run_root = context["request"]["run_root"]
    round_id = context["request"]["round_id"]
    guidance = [
        {"title": "特定Clusteringを深掘り", "prompt": f"/cs-analysis-interpret-mmp\nRun Root: {run_root}\n対象Round: {round_id}\nClustering Node: <N######>\n依頼: このClusteringでTransform効果の分散が縮小する傾向を詳しく比較してください。"},
        {"title": "特定Clusterを深掘り", "prompt": f"/cs-analysis-interpret-mmp\nRun Root: {run_root}\n対象Round: {round_id}\nCluster: <C######>\n依頼: Global-minus-Localを含め、Cluster固有Transformを詳しく比較してください。"},
        {"title": "特定Transformを横断", "prompt": f"/cs-analysis-interpret-mmp\nRun Root: {run_root}\n対象Round: {round_id}\nTransform: <TRF-...>\n依頼: このTransformを全ClusteringとClusterで横断比較してください。"},
    ]
    return {
        "title": "MMP Global–Local Clustering解釈",
        "executive_summary": f"Global MMP {summary['global_mmp_count']}件を、{summary['clustering_node_count']}個のClustering Nodeと{summary['cluster_count']}個のClusterでread-only比較しました。分散縮小候補{summary['variance_candidate_count']}件、Cluster固有候補{summary['cluster_specific_candidate_count']}件、方向反転候補{summary['direction_reversal_candidate_count']}件を抽出しました。",
        "observations": observations[:12],
        "human_guidance": guidance,
    }


def validate_draft(path: Path) -> dict[str, Any]:
    draft = load_json(path)
    try:
        import jsonschema
    except ImportError as exc:
        raise RuntimeError("jsonschema is required") from exc
    schema = load_json(Path(__file__).resolve().parents[1] / "schemas" / "draft.schema.json")
    jsonschema.validate(draft, schema)
    return draft


def prepare(args: argparse.Namespace) -> int:
    if not args.explicit_request:
        raise PermissionError("--explicit-request is required")
    if not ROUND_PATTERN.match(args.round_id):
        raise ValueError("--round-id must be RND####")
    if args.mmp_node_id and not NODE_PATTERN.match(args.mmp_node_id):
        raise ValueError("--mmp-node-id must be N######")
    for value in args.clustering_node_id or []:
        if not NODE_PATTERN.match(value):
            raise ValueError(f"Invalid Clustering Node ID: {value}")
    for value in args.cluster_id or []:
        if not CLUSTER_PATTERN.match(value):
            raise ValueError(f"Invalid Cluster ID: {value}")
    root, control, snapshot = validate_frozen_run(args.run_root)
    if args.round_id not in (snapshot.get("rounds") or {}):
        raise ValueError(f"Unknown Round: {args.round_id}")
    mmp_node, database = select_global_mmp(root, snapshot, args.round_id, args.mmp_node_id)
    matrix, id_column, registry = select_clusters(root, snapshot, args.clustering_node_id or [], args.cluster_id or [])
    details, metadata = load_mmp_database(database)
    if args.transform_id:
        requested = set(args.transform_id)
        missing = sorted(requested - set(details["transform_id"].astype(str)))
        if missing:
            raise ValueError("Requested Transforms are unavailable: " + ", ".join(missing))
        details = details[details["transform_id"].astype(str).isin(requested)].copy()
    inventory = run_inventory(root)
    tables = derive_tables(details, matrix, id_column, registry, args.min_local_pairs, args.min_outside_pairs)
    # Allocate only after every read-only derivation has succeeded, so a bad
    # request does not leave an empty request directory behind.
    request_id, request_dir = allocate_request(root)
    filenames = {
        "global_transform_summary": "global_transform_summary.csv",
        "cluster_screening": "cluster_screening.csv",
        "cluster_transform_summary": "cluster_transform_summary.csv",
        "clustering_transform_summary": "clustering_transform_summary.csv",
        "variance_collapse": "candidate_variance_collapse.csv",
        "cluster_specific": "candidate_cluster_specific.csv",
        "direction_reversal": "candidate_direction_reversal.csv",
        "clustering_overview": "clustering_overview.csv",
    }
    for key, filename in filenames.items():
        tables[key].to_csv(request_dir / filename, index=False)
    source_nodes = sorted({str(row.get("source_node_id")) for row in registry})
    summary = {
        "clustering_node_count": len(source_nodes),
        "cluster_count": len(registry),
        "global_mmp_count": int(details["mmp_id"].nunique()),
        "global_transform_count": int(details["transform_id"].nunique()),
        "variance_candidate_count": len(tables["variance_collapse"]),
        "cluster_specific_candidate_count": len(tables["cluster_specific"]),
        "direction_reversal_candidate_count": len(tables["direction_reversal"]),
        "min_local_pairs": args.min_local_pairs,
        "min_outside_pairs": args.min_outside_pairs,
    }
    previews = {key: records(tables[key], 20) for key in ("variance_collapse", "cluster_specific", "direction_reversal", "clustering_overview")}
    run = control.get("run") or {}
    context = {
        "schema_version": "1.0.0",
        "request": {
            "request_id": request_id,
            "run_root": str(root),
            "round_id": args.round_id,
            "mmp_node_id": mmp_node["node_id"],
            "clustering_node_ids": source_nodes,
            "cluster_ids": [str(row["cluster_id"]) for row in registry],
            "transform_ids": args.transform_id or [],
            "created_at": utc_now(),
        },
        "source": {
            "run_id": str(run.get("run_id", "")),
            "round_id": args.round_id,
            "mmp_node_id": mmp_node["node_id"],
            "mmp_database": database.relative_to(root).as_posix(),
            "mmp_database_bytes": database.stat().st_size,
            "endpoint": str(metadata.get("endpoint_column") or run.get("endpoint") or ""),
            "higher_is_better": bool(metadata.get("higher_is_better", run.get("higher_is_better", True))),
        },
        "summary": summary,
        "metric_definitions": {
            "favorable_delta": "Endpoint delta oriented so that positive is favorable according to higher_is_better.",
            "local": "Both compounds of the MMP pair are members of the Cluster.",
            "outside": "Neither compound of the MMP pair is a member of the Cluster; boundary pairs are excluded.",
            "dispersion_reduction": "1 - pair-count-weighted eligible Local IQR / Global IQR; descriptive and valid for ranking only when membership does not overlap.",
            "direction_reversal_vs_outside": "Non-zero Local and Outside median favorable_delta have opposite signs.",
        },
        "previews": previews,
        "artifacts": filenames,
        "agent_contract": {
            "read_only_run": True,
            "editable_file": "mmp_interpretation_draft.json",
            "state_or_dag_mutation": False,
            "scientific_values_must_come_from_context_or_csv": True,
        },
    }
    draft = default_draft(context)
    request_record = {
        "schema_version": "1.0.0",
        "request_id": request_id,
        "run_root": str(root),
        "request_dir": str(request_dir),
        "round_id": args.round_id,
        "mmp_node_id": mmp_node["node_id"],
        "configuration": {
            "clustering_node_ids": args.clustering_node_id or [],
            "cluster_ids": args.cluster_id or [],
            "transform_ids": args.transform_id or [],
            "min_local_pairs": args.min_local_pairs,
            "min_outside_pairs": args.min_outside_pairs,
        },
        "created_at": utc_now(),
    }
    write_json(request_dir / "request.json", request_record)
    write_json(request_dir / "source_inventory.json", {"entries": inventory})
    write_json(request_dir / "mmp_interpretation_context.json", context)
    write_json(request_dir / "mmp_interpretation_draft.json", draft)
    print(json.dumps({"request_id": request_id, "request_dir": str(request_dir), "context": str(request_dir / "mmp_interpretation_context.json"), "draft": str(request_dir / "mmp_interpretation_draft.json")}, ensure_ascii=False))
    return 0


def resolve_request(value: str) -> tuple[Path, Path, dict[str, Any]]:
    request_dir = Path(value).expanduser().resolve()
    if not request_dir.is_dir() or not REQUEST_PATTERN.match(request_dir.name):
        raise ValueError(f"Invalid MMP request directory: {request_dir}")
    request = load_json(request_dir / "request.json")
    root = Path(str(request.get("run_root", ""))).resolve()
    if request_dir.parent != (root / "mmp_interpretation").resolve():
        raise PermissionError("Request directory is outside run_root/mmp_interpretation")
    return root, request_dir, request


def finalize(args: argparse.Namespace) -> int:
    root, request_dir, _request = resolve_request(args.request_dir)
    validate_frozen_run(str(root))
    draft = validate_draft(request_dir / "mmp_interpretation_draft.json")
    context = load_json(request_dir / "mmp_interpretation_context.json")
    outputs = [request_dir / "mmp_interpretation.json", request_dir / "mmp_interpretation.md", request_dir / "mmp_interpretation.html"]
    if not args.overwrite and any(path.exists() for path in outputs):
        raise FileExistsError("Finalized output already exists; use --overwrite only after intentionally revising the request-local draft")
    report = {
        "schema_version": "1.0.0",
        "document_type": "read_only_mmp_interpretation",
        "source": context["source"],
        "summary": context["summary"],
        "metric_definitions": context["metric_definitions"],
        "draft": draft,
        "previews": context["previews"],
        "artifacts": context["artifacts"],
        "state_effect": "none",
        "created_at": utc_now(),
    }
    atomic_text(outputs[0], report_json(report))
    atomic_text(outputs[1], render_markdown(report))
    atomic_text(outputs[2], render_html(report))
    print(json.dumps({"json": str(outputs[0]), "markdown": str(outputs[1]), "html": str(outputs[2])}, ensure_ascii=False))
    return 0


def verify(args: argparse.Namespace) -> int:
    root, request_dir, _request = resolve_request(args.request_dir)
    expected = load_json(request_dir / "source_inventory.json")["entries"]
    current = run_inventory(root)
    errors: list[str] = []
    if expected != current:
        before = {row["path"]: row for row in expected}
        after = {row["path"]: row for row in current}
        changed = sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))
        errors.append("Canonical Run inventory changed: " + ", ".join(changed[:30]))
    required = [
        "request.json", "source_inventory.json", "mmp_interpretation_context.json", "mmp_interpretation_draft.json",
        "mmp_interpretation.json", "mmp_interpretation.md", "mmp_interpretation.html",
        "global_transform_summary.csv", "cluster_screening.csv", "cluster_transform_summary.csv",
        "clustering_transform_summary.csv", "candidate_variance_collapse.csv",
        "candidate_cluster_specific.csv", "candidate_direction_reversal.csv", "clustering_overview.csv",
    ]
    missing = [name for name in required if not (request_dir / name).is_file()]
    if missing:
        errors.append("Missing request artifacts: " + ", ".join(missing))
    value = {"schema_version": "1.0.0", "request_dir": str(request_dir), "status": "fail" if errors else "pass", "errors": errors, "verified_at": utc_now()}
    write_json(request_dir / "verification.json", value)
    print(json.dumps(value, ensure_ascii=False))
    return 1 if errors else 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Read-only MMP Global–Local interpretation for a frozen CONDUCTOR Run")
    commands = root.add_subparsers(dest="command", required=True)
    item = commands.add_parser("prepare")
    item.add_argument("--run-root", required=True)
    item.add_argument("--round-id", required=True)
    item.add_argument("--mmp-node-id")
    item.add_argument("--clustering-node-id", action="append")
    item.add_argument("--cluster-id", action="append")
    item.add_argument("--transform-id", action="append")
    item.add_argument("--min-local-pairs", type=int, default=5)
    item.add_argument("--min-outside-pairs", type=int, default=5)
    item.add_argument("--explicit-request", action="store_true")
    item.set_defaults(func=prepare)
    item = commands.add_parser("finalize")
    item.add_argument("--request-dir", required=True)
    item.add_argument("--overwrite", action="store_true")
    item.set_defaults(func=finalize)
    item = commands.add_parser("verify")
    item.add_argument("--request-dir", required=True)
    item.set_defaults(func=verify)
    return root


def main() -> int:
    args = parser().parse_args()
    if hasattr(args, "min_local_pairs") and args.min_local_pairs < 2:
        raise ValueError("--min-local-pairs must be >= 2")
    if hasattr(args, "min_outside_pairs") and args.min_outside_pairs < 2:
        raise ValueError("--min-outside-pairs must be >= 2")
    return int(args.func(args))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
