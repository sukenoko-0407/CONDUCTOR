from __future__ import annotations

import itertools
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from grouping_io import write_csv, write_json
from grouping_models import assign_group_ids, registry_entry, stable_slug

try:
    from rdkit.ML.Cluster import Butina  # type: ignore

    BUTINA_AVAILABLE = True
except Exception:
    Butina = None
    BUTINA_AVAILABLE = False


NON_FEATURE_COLUMNS = {
    "compound_id",
    "canonical_smiles",
    "input_smiles",
    "original_smiles",
    "mol_parse_ok",
    "descriptor_error",
    "mol_error",
    "source_row_index",
    "row_index",
    "exclusion_reason",
}

ID_COLUMN_CANDIDATES = ["compound_id", "Compound_ID", "ID", "id", "mol_id", "molecule_id"]
DEFAULT_METHODS = ["butina", "hierarchical", "dbscan", "louvain", "leiden", "connected_components"]

FILE_SUMMARY_COLUMNS = [
    "descriptor_file",
    "id_column",
    "input_row_count",
    "matched_compound_count",
    "feature_count",
    "used_for_clustering",
    "skip_reason",
]

CLUSTER_SUMMARY_COLUMNS = [
    "descriptor_file",
    "method",
    "parameter_set_id",
    "cluster_id",
    "group_id",
    "cluster_size",
    "center_compound_id",
]

CLUSTER_MEMBERSHIP_COLUMNS = [
    "descriptor_file",
    "method",
    "parameter_set_id",
    "cluster_id",
    "group_id",
    "compound_id",
    "is_center",
    "similarity_to_center",
]


class DisjointSet:
    def __init__(self, values: list[int]) -> None:
        self.parent = {value: value for value in values}

    def find(self, value: int) -> int:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: int, right: int) -> None:
        root_left = self.find(left)
        root_right = self.find(right)
        if root_left != root_right:
            self.parent[max(root_left, root_right)] = min(root_left, root_right)


def _methods(cfg: dict[str, Any]) -> list[str]:
    methods = cfg.get("methods")
    if isinstance(methods, list) and methods:
        return [str(method).lower() for method in methods]
    return DEFAULT_METHODS


def _descriptor_dir(input_path: str | Path, description_cfg: dict[str, Any]) -> Path:
    base_dir = Path(str(description_cfg.get("base_dir", "descriptions")))
    if not base_dir.is_absolute():
        base_dir = SCRIPT_DIR.parents[3] / base_dir
    subdir = description_cfg.get("subdir")
    if subdir:
        return base_dir / str(subdir)
    return base_dir / Path(input_path).stem


def _find_id_column(df: pd.DataFrame) -> str | None:
    normalized = {str(col).strip().lower(): str(col) for col in df.columns}
    for candidate in ID_COLUMN_CANDIDATES:
        hit = normalized.get(candidate.lower())
        if hit is not None:
            return hit
    return None


def _parameter_configs(cfg: dict[str, Any], method: str) -> list[tuple[str, dict[str, Any]]]:
    sweeps = cfg.get("parameter_sweeps", {}) or {}
    method_sweep = sweeps.get(method, {}) or {}

    def thresholds(default: list[float]) -> list[float]:
        values = method_sweep.get("similarity_thresholds", default)
        return [float(value) for value in values]

    if method == "butina":
        return [(f"thr{threshold:g}", {"similarity_threshold": threshold}) for threshold in thresholds([0.6, 0.7, 0.8])]
    if method == "hierarchical":
        values = []
        for threshold, linkage in itertools.product(thresholds([0.6, 0.7, 0.8]), method_sweep.get("linkages", ["average"])):
            values.append((f"thr{threshold:g}_{linkage}", {"similarity_threshold": threshold, "hierarchical_linkage": str(linkage)}))
        return values
    if method == "dbscan":
        values = []
        for threshold, min_samples in itertools.product(thresholds([0.6, 0.7, 0.8]), method_sweep.get("min_samples", [3, 5])):
            values.append((f"thr{threshold:g}_min{int(min_samples)}", {"similarity_threshold": threshold, "dbscan_min_samples": int(min_samples)}))
        return values
    if method in {"louvain", "leiden"}:
        values = []
        for resolution, graph_mode, top_k in itertools.product(
            method_sweep.get("resolutions", [0.5, 1.0, 1.5]),
            method_sweep.get("graph_modes", ["top_k_weighted_graph"]),
            method_sweep.get("top_k_neighbors", [10, 20]),
        ):
            values.append(
                (
                    f"res{float(resolution):g}_{graph_mode}_k{int(top_k)}",
                    {"resolution": float(resolution), "graph_mode": str(graph_mode), "top_k_neighbors": int(top_k)},
                )
            )
        return values
    if method in {"connected_components", "threshold_graph"}:
        return [(f"thr{threshold:g}", {"similarity_threshold": threshold}) for threshold in thresholds([0.6, 0.7, 0.8])]
    return [("default", {})]


def _prepare_matrix(
    descriptor_path: Path,
    compounds: pd.DataFrame,
    cfg: dict[str, Any],
    warnings: list[str],
) -> tuple[list[str], np.ndarray, str, int, str | None]:
    df = pd.read_csv(descriptor_path)
    id_column = _find_id_column(df)
    if id_column is None:
        return [], np.empty((0, 0)), "", 0, "no supported compound ID column"

    if df[id_column].astype(str).duplicated().any():
        duplicate_count = int(df[id_column].astype(str).duplicated().sum())
        warnings.append(f"{descriptor_path.name}: dropped {duplicate_count} duplicate descriptor ID rows, keeping first occurrence.")
        df = df.drop_duplicates(subset=[id_column], keep="first")

    wanted = compounds["compound_id"].astype(str).tolist()
    wanted_set = set(wanted)
    df[id_column] = df[id_column].astype(str)
    extra_count = int((~df[id_column].isin(wanted_set)).sum())
    if extra_count:
        warnings.append(f"{descriptor_path.name}: ignored {extra_count} descriptor rows not present in the input CSV.")
    df = df[df[id_column].isin(wanted_set)].copy()
    order = pd.DataFrame({"compound_id": wanted})
    df = order.merge(df, left_on="compound_id", right_on=id_column, how="inner")

    excluded = {col.lower() for col in NON_FEATURE_COLUMNS}
    feature_cols: list[str] = []
    numeric_parts: list[pd.Series] = []
    for col in df.columns:
        if str(col).lower() in excluded or col in {"compound_id", id_column}:
            continue
        numeric = pd.to_numeric(df[col], errors="coerce")
        if numeric.notna().any():
            feature_cols.append(str(col))
            numeric_parts.append(numeric)

    if not numeric_parts:
        return [], np.empty((0, 0)), id_column, 0, "no numeric feature columns"

    features = pd.concat(numeric_parts, axis=1)
    features.columns = feature_cols
    if bool(cfg.get("drop_constant_features", True)):
        keep = [col for col in features.columns if features[col].nunique(dropna=True) > 1]
        features = features[keep]
    if features.shape[1] == 0:
        return [], np.empty((0, 0)), id_column, 0, "all numeric features were constant"

    if str(cfg.get("missing_value_strategy", "median_impute")) == "median_impute":
        features = features.fillna(features.median(numeric_only=True)).fillna(0.0)
    else:
        features = features.fillna(0.0)

    matrix = features.to_numpy(dtype=float)
    if str(cfg.get("scaling", "standard")) == "standard":
        means = matrix.mean(axis=0)
        stds = matrix.std(axis=0)
        stds[stds == 0] = 1.0
        matrix = (matrix - means) / stds

    ids = df["compound_id"].astype(str).tolist()
    return ids, matrix, id_column, int(features.shape[1]), None


def _similarity_matrix(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1)
    norms[norms == 0] = 1.0
    normalized = matrix / norms[:, None]
    similarity = normalized @ normalized.T
    similarity = np.clip(similarity, -1.0, 1.0)
    similarity = (similarity + 1.0) / 2.0
    np.fill_diagonal(similarity, 1.0)
    return similarity


def _distance_matrix(similarity: np.ndarray) -> np.ndarray:
    distance = 1.0 - similarity
    np.fill_diagonal(distance, 0.0)
    return distance


def _clusters_from_labels(labels: list[int]) -> list[list[int]]:
    clusters: dict[int, list[int]] = defaultdict(list)
    for index, label in enumerate(labels):
        if label < 0:
            continue
        clusters[int(label)].append(index)
    return sorted((sorted(indices) for indices in clusters.values()), key=lambda item: (item[0], len(item)))


def _center_for_cluster(indices: list[int], similarity: np.ndarray) -> int:
    if len(indices) == 1:
        return indices[0]
    return max(indices, key=lambda idx: (sum(float(similarity[idx, other]) for other in indices if other != idx), -idx))


def _edge_count(indices: list[int], similarity: np.ndarray, threshold: float | None) -> int:
    count = 0
    for left, right in itertools.combinations(indices, 2):
        if threshold is None or similarity[left, right] >= threshold:
            count += 1
    return count


def _butina(similarity: np.ndarray, params: dict[str, Any], warnings: list[str]) -> tuple[list[list[int]], dict[str, Any]] | None:
    if not BUTINA_AVAILABLE:
        warnings.append("Skipped descriptor Butina clustering: RDKit Butina is unavailable.")
        return None
    threshold = float(params.get("similarity_threshold", 0.7))
    distances: list[float] = []
    for i in range(1, similarity.shape[0]):
        distances.extend([1.0 - float(similarity[i, j]) for j in range(i)])
    clusters = Butina.ClusterData(distances, similarity.shape[0], 1.0 - threshold, isDistData=True, reordering=True)
    return [list(cluster) for cluster in clusters], {"method": "butina", "similarity_threshold": threshold, "distance_cutoff": 1.0 - threshold}


def _hierarchical(similarity: np.ndarray, params: dict[str, Any], cfg: dict[str, Any], warnings: list[str]) -> tuple[list[list[int]], dict[str, Any]] | None:
    max_compounds = int(cfg.get("max_hierarchical_compounds", 3000))
    if similarity.shape[0] > max_compounds:
        warnings.append(f"Skipped descriptor hierarchical clustering: compound count exceeds max_hierarchical_compounds={max_compounds}.")
        return None
    try:
        from sklearn.cluster import AgglomerativeClustering  # type: ignore
    except Exception as exc:
        warnings.append(f"Skipped descriptor hierarchical clustering: scikit-learn unavailable ({exc}).")
        return None
    threshold = float(params.get("similarity_threshold", 0.7))
    linkage = str(params.get("hierarchical_linkage", "average"))
    try:
        model = AgglomerativeClustering(n_clusters=None, metric="precomputed", linkage=linkage, distance_threshold=1.0 - threshold)
    except TypeError:
        model = AgglomerativeClustering(n_clusters=None, affinity="precomputed", linkage=linkage, distance_threshold=1.0 - threshold)
    labels = model.fit_predict(_distance_matrix(similarity))
    return _clusters_from_labels([int(label) for label in labels]), {"method": "hierarchical", "similarity_threshold": threshold, "linkage": linkage}


def _dbscan(similarity: np.ndarray, params: dict[str, Any], cfg: dict[str, Any], warnings: list[str]) -> tuple[list[list[int]], dict[str, Any]] | None:
    max_compounds = int(cfg.get("max_dbscan_compounds", 3000))
    if similarity.shape[0] > max_compounds:
        warnings.append(f"Skipped descriptor DBSCAN clustering: compound count exceeds max_dbscan_compounds={max_compounds}.")
        return None
    try:
        from sklearn.cluster import DBSCAN  # type: ignore
    except Exception as exc:
        warnings.append(f"Skipped descriptor DBSCAN clustering: scikit-learn unavailable ({exc}).")
        return None
    threshold = float(params.get("similarity_threshold", 0.7))
    min_samples = int(params.get("dbscan_min_samples", 3))
    labels = DBSCAN(eps=1.0 - threshold, min_samples=min_samples, metric="precomputed").fit_predict(_distance_matrix(similarity))
    return _clusters_from_labels([int(label) for label in labels]), {
        "method": "dbscan",
        "similarity_threshold": threshold,
        "eps": 1.0 - threshold,
        "min_samples": min_samples,
    }


def _graph_edges(similarity: np.ndarray, params: dict[str, Any]) -> list[tuple[int, int, float]]:
    mode = str(params.get("graph_mode", "top_k_weighted_graph"))
    top_k = int(params.get("top_k_neighbors", 20))
    threshold = params.get("similarity_threshold")
    n = similarity.shape[0]
    edges: dict[tuple[int, int], float] = {}

    def add_edge(i: int, j: int) -> None:
        if i == j:
            return
        weight = float(similarity[i, j])
        if threshold is not None and weight < float(threshold):
            return
        if weight <= 0:
            return
        key = (min(i, j), max(i, j))
        edges[key] = max(edges.get(key, 0.0), weight)

    if mode == "full_weighted_graph":
        for i in range(n):
            for j in range(i + 1, n):
                add_edge(i, j)
    elif mode == "mutual_top_k_weighted_graph":
        top_sets = [set(sorted((j for j in range(n) if j != i), key=lambda j: (-similarity[i, j], j))[:top_k]) for i in range(n)]
        for i in range(n):
            for j in top_sets[i]:
                if i in top_sets[j]:
                    add_edge(i, j)
    else:
        for i in range(n):
            for j in sorted((j for j in range(n) if j != i), key=lambda j: (-similarity[i, j], j))[:top_k]:
                add_edge(i, j)
    return [(i, j, weight) for (i, j), weight in sorted(edges.items())]


def _louvain(similarity: np.ndarray, params: dict[str, Any], cfg: dict[str, Any], warnings: list[str]) -> tuple[list[list[int]], dict[str, Any]] | None:
    max_compounds = int(cfg.get("max_louvain_compounds", 10000))
    if similarity.shape[0] > max_compounds:
        warnings.append(f"Skipped descriptor Louvain clustering: compound count exceeds max_louvain_compounds={max_compounds}.")
        return None
    try:
        import networkx as nx  # type: ignore
        from networkx.algorithms.community import louvain_communities  # type: ignore
    except Exception as exc:
        warnings.append(f"Skipped descriptor Louvain clustering: NetworkX Louvain unavailable ({exc}).")
        return None
    graph = nx.Graph()
    graph.add_nodes_from(range(similarity.shape[0]))
    edges = _graph_edges(similarity, params)
    graph.add_weighted_edges_from(edges)
    communities = louvain_communities(graph, weight="weight", resolution=float(params.get("resolution", 1.0)), seed=int(cfg.get("random_seed", 42)))
    return [sorted(list(community)) for community in communities], {
        "method": "louvain",
        "resolution": float(params.get("resolution", 1.0)),
        "graph_mode": str(params.get("graph_mode", "top_k_weighted_graph")),
        "top_k_neighbors": int(params.get("top_k_neighbors", 20)),
        "edge_count": len(edges),
    }


def _leiden(similarity: np.ndarray, params: dict[str, Any], cfg: dict[str, Any], warnings: list[str]) -> tuple[list[list[int]], dict[str, Any]] | None:
    max_compounds = int(cfg.get("max_leiden_compounds", 10000))
    if similarity.shape[0] > max_compounds:
        warnings.append(f"Skipped descriptor Leiden clustering: compound count exceeds max_leiden_compounds={max_compounds}.")
        return None
    try:
        import igraph as ig  # type: ignore
        import leidenalg  # type: ignore
    except Exception as exc:
        warnings.append(f"Skipped descriptor Leiden clustering: igraph/leidenalg unavailable ({exc}).")
        return None
    edges = _graph_edges(similarity, params)
    graph = ig.Graph(n=similarity.shape[0], edges=[(i, j) for i, j, _ in edges], directed=False)
    weights = [weight for _, _, weight in edges]
    if weights:
        graph.es["weight"] = weights
    partition_name = str(cfg.get("leiden_partition_type", "RBConfigurationVertexPartition"))
    partition_type = getattr(leidenalg, partition_name, leidenalg.RBConfigurationVertexPartition)
    kwargs: dict[str, Any] = {"seed": int(cfg.get("random_seed", 42))}
    if weights:
        kwargs["weights"] = "weight"
    if partition_name in {"RBConfigurationVertexPartition", "CPMVertexPartition"}:
        kwargs["resolution_parameter"] = float(params.get("resolution", 1.0))
    partition = leidenalg.find_partition(graph, partition_type, **kwargs)
    return [sorted(list(cluster)) for cluster in partition], {
        "method": "leiden",
        "resolution": float(params.get("resolution", 1.0)),
        "graph_mode": str(params.get("graph_mode", "top_k_weighted_graph")),
        "top_k_neighbors": int(params.get("top_k_neighbors", 20)),
        "edge_count": len(edges),
    }


def _connected_components(similarity: np.ndarray, params: dict[str, Any]) -> tuple[list[list[int]], dict[str, Any]]:
    threshold = float(params.get("similarity_threshold", 0.7))
    ds = DisjointSet(list(range(similarity.shape[0])))
    edges = 0
    for i in range(similarity.shape[0]):
        for j in range(i + 1, similarity.shape[0]):
            if similarity[i, j] >= threshold:
                ds.union(i, j)
                edges += 1
    components: dict[int, list[int]] = defaultdict(list)
    for index in range(similarity.shape[0]):
        components[ds.find(index)].append(index)
    return sorted((sorted(value) for value in components.values()), key=lambda item: (item[0], len(item))), {
        "method": "connected_components",
        "similarity_threshold": threshold,
        "edge_count": edges,
    }


def _cluster_method(
    method: str,
    similarity: np.ndarray,
    params: dict[str, Any],
    cfg: dict[str, Any],
    warnings: list[str],
) -> tuple[list[list[int]], dict[str, Any]] | None:
    if method == "butina":
        return _butina(similarity, params, warnings)
    if method == "hierarchical":
        return _hierarchical(similarity, params, cfg, warnings)
    if method == "dbscan":
        return _dbscan(similarity, params, cfg, warnings)
    if method == "louvain":
        return _louvain(similarity, params, cfg, warnings)
    if method == "leiden":
        return _leiden(similarity, params, cfg, warnings)
    if method in {"connected_components", "threshold_graph"}:
        return _connected_components(similarity, params)
    warnings.append(f"Unknown descriptor clustering method skipped: {method}")
    return None


def _cluster_rows(
    descriptor_file: str,
    method: str,
    parameter_set_id: str,
    clusters: list[list[int]],
    ids: list[str],
    similarity: np.ndarray,
    min_cluster_size: int,
    definition: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cluster_index, indices in enumerate(clusters, start=1):
        if len(indices) < min_cluster_size:
            continue
        center = _center_for_cluster(indices, similarity)
        center_id = ids[center]
        sim_to_center = [float(similarity[center, idx]) for idx in indices]
        rows.append(
            {
                "descriptor_file": descriptor_file,
                "method": method,
                "parameter_set_id": parameter_set_id,
                "cluster_local_id": f"{method.upper()}_{stable_slug(parameter_set_id, 32)}_{cluster_index:03d}",
                "compound_ids": [ids[index] for index in indices],
                "center_compound_id": center_id,
                "similarity_to_center": {ids[index]: float(similarity[center, index]) for index in indices},
                "definition": dict(definition),
                "summary": {
                    "cluster_size": len(indices),
                    "center_compound_id": center_id,
                    "min_similarity_to_center": round(min(sim_to_center), 6),
                    "median_similarity_to_center": round(float(statistics.median(sim_to_center)), 6),
                    "mean_similarity_to_center": round(float(statistics.mean(sim_to_center)), 6),
                    "max_similarity_to_center": round(max(sim_to_center), 6),
                    "edge_count": _edge_count(indices, similarity, definition.get("similarity_threshold")),
                },
                "sort_key": f"{descriptor_file}:{method}:{parameter_set_id}:{center_id}:{len(indices):04d}",
            }
        )
    return rows


def build_descriptor_clusters(
    compounds: pd.DataFrame,
    input_path: str | Path,
    description_config: dict[str, Any],
    config: dict[str, Any],
    outdir: str | Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    description_cfg = description_config or {}
    cfg = config or {}
    if not bool(description_cfg.get("enabled", True)) or not bool(cfg.get("enabled", True)):
        return [], [], []

    warnings: list[str] = []
    descriptor_dir = _descriptor_dir(input_path, description_cfg)
    if not descriptor_dir.exists():
        return [], [], [f"Descriptor directory not found; descriptor clustering skipped: {descriptor_dir}"]

    file_glob = str(description_cfg.get("file_glob", "*.csv"))
    skip_names = {str(name).lower() for name in description_cfg.get("skip_files", ["errors.csv", "run_metadata.csv"])}
    paths = sorted(path for path in descriptor_dir.glob(file_glob) if path.is_file() and path.name.lower() not in skip_names)
    if not paths:
        return [], [], [f"No descriptor CSV files found for descriptor clustering: {descriptor_dir}"]

    min_compounds = int(cfg.get("min_compounds", 3))
    min_cluster_size = int(cfg.get("min_cluster_size", 2))
    file_summary: list[dict[str, Any]] = []
    cluster_summary: list[dict[str, Any]] = []
    cluster_membership: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []

    for path in paths:
        try:
            ids, matrix, id_column, feature_count, skip_reason = _prepare_matrix(path, compounds, cfg, warnings)
        except Exception as exc:
            ids, matrix, id_column, feature_count, skip_reason = [], np.empty((0, 0)), "", 0, f"failed to read descriptor CSV: {exc}"

        used = skip_reason is None and len(ids) >= min_compounds
        if skip_reason is None and len(ids) < min_compounds:
            skip_reason = f"matched compound count below min_compounds={min_compounds}"
            used = False
        file_summary.append(
            {
                "descriptor_file": path.name,
                "id_column": id_column,
                "input_row_count": int(pd.read_csv(path, usecols=[id_column]).shape[0]) if id_column else 0,
                "matched_compound_count": len(ids),
                "feature_count": feature_count,
                "used_for_clustering": used,
                "skip_reason": "" if used else skip_reason,
            }
        )
        if not used:
            warnings.append(f"{path.name}: descriptor clustering skipped: {skip_reason}")
            continue

        similarity = _similarity_matrix(matrix)
        for method in _methods(cfg):
            for parameter_set_id, params in _parameter_configs(cfg, method):
                result = _cluster_method(method, similarity, params, cfg, warnings)
                if result is None:
                    continue
                clusters, definition = result
                definition.update(
                    {
                        "source_descriptor_file": path.name,
                        "parameter_set_id": parameter_set_id,
                        "feature_count": feature_count,
                        "matched_compound_count": len(ids),
                        "scaling": str(cfg.get("scaling", "standard")),
                        "similarity_metric": str(cfg.get("similarity_metric", "cosine")),
                    }
                )
                rows = _cluster_rows(path.name, method, parameter_set_id, clusters, ids, similarity, min_cluster_size, definition)
                pending.extend(
                    {
                        "group_label": f"DESC_{stable_slug(Path(path.name).stem, 24)}_{method.upper()}_{stable_slug(parameter_set_id, 24)}_{row['cluster_local_id']}",
                        "cluster_row": row,
                        "compound_ids": row["compound_ids"],
                        "sort_key": row["sort_key"],
                    }
                    for row in rows
                )

    registry: list[dict[str, Any]] = []
    membership: list[dict[str, Any]] = []
    assigned = assign_group_ids(pending, "DESC")
    for item in assigned:
        group_id = item["group_id"]
        row = item["cluster_row"]
        row["group_id"] = group_id
        method = str(row["method"])
        group_type = f"descriptor_{method}_cluster" if method != "connected_components" else "descriptor_connected_component"
        registry.append(
            registry_entry(
                group_id=group_id,
                label=item["group_label"],
                group_type=group_type,
                source="descriptor_clustering_builder",
                source_column=None,
                definition=row["definition"],
                compounds=compounds,
                compound_ids=item["compound_ids"],
            )
        )
        summary = row["summary"]
        cluster_summary.append(
            {
                "descriptor_file": row["descriptor_file"],
                "method": method,
                "parameter_set_id": row["parameter_set_id"],
                "cluster_id": row["cluster_local_id"],
                "group_id": group_id,
                "cluster_size": summary["cluster_size"],
                "center_compound_id": summary["center_compound_id"],
            }
        )
        for compound_id in item["compound_ids"]:
            membership.append(
                {
                    "group_id": group_id,
                    "compound_id": compound_id,
                    "membership_source": f"descriptor:{method}",
                    "membership_reason": f"{row['descriptor_file']}:{method}:{row['parameter_set_id']}:{row['cluster_local_id']}",
                }
            )
            cluster_membership.append(
                {
                    "descriptor_file": row["descriptor_file"],
                    "method": method,
                    "parameter_set_id": row["parameter_set_id"],
                    "cluster_id": row["cluster_local_id"],
                    "group_id": group_id,
                    "compound_id": compound_id,
                    "is_center": compound_id == summary["center_compound_id"],
                    "similarity_to_center": round(float(row["similarity_to_center"].get(compound_id, 0.0)), 6),
                }
            )

    if outdir is not None and bool(cfg.get("write_descriptor_diagnostics", True)):
        output_dir = Path(outdir)
        write_csv(output_dir / "descriptor_file_summary.csv", file_summary, FILE_SUMMARY_COLUMNS)
        write_csv(output_dir / "descriptor_cluster_summary.csv", cluster_summary, CLUSTER_SUMMARY_COLUMNS)
        write_csv(output_dir / "descriptor_cluster_membership.csv", cluster_membership, CLUSTER_MEMBERSHIP_COLUMNS)
        write_json(output_dir / "descriptor_clustering_warnings.json", warnings)

    return registry, membership, warnings
