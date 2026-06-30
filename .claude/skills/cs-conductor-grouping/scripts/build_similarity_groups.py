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
from grouping_models import assign_group_ids, registry_entry

try:
    from rdkit import Chem, DataStructs  # type: ignore
    from rdkit import RDLogger  # type: ignore
    from rdkit.Chem import AllChem  # type: ignore
    from rdkit.ML.Cluster import Butina  # type: ignore

    RDLogger.DisableLog("rdApp.error")
    RDLogger.DisableLog("rdApp.warning")
    RDKIT_AVAILABLE = True
except Exception:
    Chem = None
    DataStructs = None
    AllChem = None
    Butina = None
    RDKIT_AVAILABLE = False


SIM_MEMBERSHIP_COLUMNS = [
    "method",
    "parameter_set_id",
    "cluster_id",
    "group_id",
    "compound_id",
    "is_center",
    "similarity_to_center",
    "membership_reason",
]

SIM_SUMMARY_COLUMNS = [
    "method",
    "parameter_set_id",
    "cluster_id",
    "group_id",
    "cluster_size",
    "center_compound_id",
    "min_similarity_to_center",
    "median_similarity_to_center",
    "mean_similarity_to_center",
    "max_similarity_to_center",
    "edge_count",
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


def _method_threshold(cfg: dict[str, Any], method: str) -> float:
    thresholds = cfg.get("similarity_thresholds", {}) or {}
    if method in thresholds:
        return float(thresholds[method])
    return float(cfg.get("similarity_threshold", 0.7))


def _methods(cfg: dict[str, Any]) -> list[str]:
    methods = cfg.get("methods")
    if isinstance(methods, list) and methods:
        return [str(method).lower() for method in methods]
    method = str(cfg.get("method", "butina")).lower()
    return [method]


def _parameter_configs(cfg: dict[str, Any], method: str) -> list[tuple[str, dict[str, Any]]]:
    sweeps = cfg.get("parameter_sweeps", {}) or {}
    method_sweep = sweeps.get(method, {}) or {}

    def thresholds(default: list[float]) -> list[float]:
        values = method_sweep.get("similarity_thresholds", default)
        return [float(value) for value in values]

    if method == "butina":
        return [(f"thr{threshold:g}", {"similarity_thresholds": {"butina": threshold}}) for threshold in thresholds([0.6, 0.7, 0.8])]
    if method == "hierarchical":
        values = []
        for threshold, linkage in itertools.product(thresholds([0.6, 0.7, 0.8]), method_sweep.get("linkages", ["average"])):
            values.append((f"thr{threshold:g}_{linkage}", {"similarity_thresholds": {"hierarchical": threshold}, "hierarchical_linkage": str(linkage)}))
        return values
    if method == "dbscan":
        values = []
        for threshold, min_samples in itertools.product(thresholds([0.6, 0.7, 0.8]), method_sweep.get("min_samples", [3, 5])):
            values.append((f"thr{threshold:g}_min{int(min_samples)}", {"similarity_thresholds": {"dbscan": threshold}, "dbscan_min_samples": int(min_samples)}))
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
                    {
                        f"{method}_resolution": float(resolution),
                        "graph_construction": {
                            method: {
                                "graph_mode": str(graph_mode),
                                "top_k_neighbors": int(top_k),
                                "use_similarity_threshold": False,
                            }
                        },
                    },
                )
            )
        return values
    if method in {"connected_components", "threshold_graph"}:
        return [(f"thr{threshold:g}", {"similarity_thresholds": {"connected_components": threshold}}) for threshold in thresholds([0.6, 0.7, 0.8])]
    return [("default", {})]


def _with_parameter_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            nested = dict(merged[key])
            for nested_key, nested_value in value.items():
                if isinstance(nested_value, dict) and isinstance(nested.get(nested_key), dict):
                    inner = dict(nested[nested_key])
                    inner.update(nested_value)
                    nested[nested_key] = inner
                else:
                    nested[nested_key] = nested_value
            merged[key] = nested
        else:
            merged[key] = value
    return merged


def _compound_fingerprints(compounds: pd.DataFrame, cfg: dict[str, Any]) -> tuple[list[str], list[Any], list[Any]]:
    radius = int(cfg.get("radius", 2))
    n_bits = int(cfg.get("n_bits", 2048))
    ids: list[str] = []
    fps: list[Any] = []
    mols: list[Any] = []
    for _, row in compounds.sort_values("compound_id").iterrows():
        mol = Chem.MolFromSmiles(str(row.get("canonical_smiles", "")))
        if mol is None:
            continue
        ids.append(str(row["compound_id"]))
        mols.append(mol)
        fps.append(AllChem.GetMorganFingerprintAsBitVect(mol, radius, nBits=n_bits))
    return ids, fps, mols


def _similarity_matrix(fps: list[Any]) -> np.ndarray:
    n = len(fps)
    matrix = np.eye(n, dtype=float)
    for i in range(n):
        sims = DataStructs.BulkTanimotoSimilarity(fps[i], fps[i + 1 :])
        for offset, similarity in enumerate(sims, start=i + 1):
            value = float(similarity)
            matrix[i, offset] = value
            matrix[offset, i] = value
    return matrix


def _distance_matrix(similarity: np.ndarray) -> np.ndarray:
    distance = 1.0 - similarity
    np.fill_diagonal(distance, 0.0)
    return distance


def _edge_count(similarity: np.ndarray, threshold: float | None = None) -> int:
    n = similarity.shape[0]
    count = 0
    for i in range(n):
        for j in range(i + 1, n):
            if threshold is None or similarity[i, j] >= threshold:
                count += 1
    return count


def _center_for_cluster(indices: list[int], similarity: np.ndarray) -> int:
    if len(indices) == 1:
        return indices[0]
    best = indices[0]
    best_score = -1.0
    for idx in indices:
        score = float(sum(similarity[idx, other] for other in indices if other != idx))
        if score > best_score or (score == best_score and idx < best):
            best = idx
            best_score = score
    return best


def _clusters_from_labels(labels: list[int]) -> list[list[int]]:
    clusters: dict[int, list[int]] = defaultdict(list)
    for index, label in enumerate(labels):
        if label < 0:
            continue
        clusters[int(label)].append(index)
    return sorted((sorted(indices) for indices in clusters.values()), key=lambda item: (item[0], len(item)))


def _cluster_rows(
    method: str,
    parameter_set_id: str,
    clusters: list[list[int]],
    ids: list[str],
    similarity: np.ndarray,
    min_cluster_size: int,
    edge_threshold: float | None,
    method_definition: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cluster_index, indices in enumerate(clusters, start=1):
        if len(indices) < min_cluster_size:
            continue
        center = _center_for_cluster(indices, similarity)
        center_id = ids[center]
        sim_to_center = [float(similarity[center, idx]) for idx in indices]
        edge_count = 0
        for left, right in itertools.combinations(indices, 2):
            if edge_threshold is None or similarity[left, right] >= edge_threshold:
                edge_count += 1
        rows.append(
            {
                "method": method,
                "parameter_set_id": parameter_set_id,
                "cluster_local_id": f"{method.upper()}_{parameter_set_id}_{cluster_index:03d}",
                "compound_ids": [ids[index] for index in indices],
                "center_compound_id": center_id,
                "similarity_to_center": {ids[index]: float(similarity[center, index]) for index in indices},
                "definition": dict(method_definition),
                "summary": {
                    "cluster_size": len(indices),
                    "center_compound_id": center_id,
                    "min_similarity_to_center": round(min(sim_to_center), 6),
                    "median_similarity_to_center": round(float(statistics.median(sim_to_center)), 6),
                    "mean_similarity_to_center": round(float(statistics.mean(sim_to_center)), 6),
                    "max_similarity_to_center": round(max(sim_to_center), 6),
                    "edge_count": edge_count,
                },
                "sort_key": f"{method}:{parameter_set_id}:{center_id}:{len(indices):04d}",
            }
        )
    return rows


def _butina_clusters(fps: list[Any], cfg: dict[str, Any]) -> tuple[list[list[int]], dict[str, Any]]:
    threshold = _method_threshold(cfg, "butina")
    cutoff = 1.0 - threshold
    distances: list[float] = []
    for i in range(1, len(fps)):
        similarities = DataStructs.BulkTanimotoSimilarity(fps[i], fps[:i])
        distances.extend([1.0 - float(similarity) for similarity in similarities])
    clusters = Butina.ClusterData(distances, len(fps), cutoff, isDistData=True, reordering=True)
    return [list(cluster) for cluster in clusters], {
        "method": "butina_clustering",
        "similarity_threshold": threshold,
        "distance_cutoff": cutoff,
    }


def _hierarchical_clusters(similarity: np.ndarray, cfg: dict[str, Any], warnings: list[str]) -> tuple[list[list[int]], dict[str, Any]] | None:
    max_compounds = int(cfg.get("max_hierarchical_compounds", 3000))
    if similarity.shape[0] > max_compounds:
        warnings.append(f"Skipped hierarchical clustering: compound count exceeds max_hierarchical_compounds={max_compounds}.")
        return None
    try:
        from sklearn.cluster import AgglomerativeClustering  # type: ignore
    except Exception as exc:
        warnings.append(f"Skipped hierarchical clustering: scikit-learn unavailable ({exc}).")
        return None
    threshold = _method_threshold(cfg, "hierarchical")
    distance_threshold = 1.0 - threshold
    distance = _distance_matrix(similarity)
    try:
        model = AgglomerativeClustering(
            n_clusters=None,
            metric="precomputed",
            linkage=str(cfg.get("hierarchical_linkage", "average")),
            distance_threshold=distance_threshold,
        )
    except TypeError:
        model = AgglomerativeClustering(
            n_clusters=None,
            affinity="precomputed",
            linkage=str(cfg.get("hierarchical_linkage", "average")),
            distance_threshold=distance_threshold,
        )
    labels = model.fit_predict(distance)
    return _clusters_from_labels([int(label) for label in labels]), {
        "method": "hierarchical_agglomerative",
        "linkage": str(cfg.get("hierarchical_linkage", "average")),
        "similarity_threshold": threshold,
        "distance_threshold": distance_threshold,
    }


def _dbscan_clusters(similarity: np.ndarray, cfg: dict[str, Any], warnings: list[str]) -> tuple[list[list[int]], dict[str, Any]] | None:
    max_compounds = int(cfg.get("max_dbscan_compounds", 3000))
    if similarity.shape[0] > max_compounds:
        warnings.append(f"Skipped DBSCAN clustering: compound count exceeds max_dbscan_compounds={max_compounds}.")
        return None
    try:
        from sklearn.cluster import DBSCAN  # type: ignore
    except Exception as exc:
        warnings.append(f"Skipped DBSCAN clustering: scikit-learn unavailable ({exc}).")
        return None
    threshold = _method_threshold(cfg, "dbscan")
    eps = 1.0 - threshold
    min_samples = int(cfg.get("dbscan_min_samples", 3))
    labels = DBSCAN(eps=eps, min_samples=min_samples, metric="precomputed").fit_predict(_distance_matrix(similarity))
    noise_count = int(sum(1 for label in labels if int(label) < 0))
    return _clusters_from_labels([int(label) for label in labels]), {
        "method": "dbscan",
        "eps": eps,
        "similarity_threshold": threshold,
        "min_samples": min_samples,
        "noise_compound_count": noise_count,
    }


def _threshold_component_clusters(similarity: np.ndarray, cfg: dict[str, Any], method: str) -> tuple[list[list[int]], dict[str, Any]]:
    threshold = _method_threshold(cfg, "connected_components")
    ds = DisjointSet(list(range(similarity.shape[0])))
    edge_count = 0
    for i in range(similarity.shape[0]):
        for j in range(i + 1, similarity.shape[0]):
            if similarity[i, j] >= threshold:
                ds.union(i, j)
                edge_count += 1
    components: dict[int, list[int]] = defaultdict(list)
    for index in range(similarity.shape[0]):
        components[ds.find(index)].append(index)
    return sorted((sorted(value) for value in components.values()), key=lambda item: (item[0], len(item))), {
        "method": "legacy_threshold_connected_components" if method == "connected_components" else method,
        "similarity_threshold": threshold,
        "edge_count": edge_count,
    }


def _graph_edges(similarity: np.ndarray, graph_cfg: dict[str, Any]) -> list[tuple[int, int, float]]:
    mode = str(graph_cfg.get("graph_mode", "top_k_weighted_graph"))
    use_threshold = bool(graph_cfg.get("use_similarity_threshold", False))
    threshold = float(graph_cfg.get("similarity_threshold", 0.0))
    top_k = int(graph_cfg.get("top_k_neighbors", 20))
    n = similarity.shape[0]
    edges: dict[tuple[int, int], float] = {}

    def add_edge(i: int, j: int) -> None:
        if i == j:
            return
        weight = float(similarity[i, j])
        if weight <= 0:
            return
        if use_threshold and weight < threshold:
            return
        key = (min(i, j), max(i, j))
        edges[key] = max(edges.get(key, 0.0), weight)

    if mode == "full_weighted_graph":
        for i in range(n):
            for j in range(i + 1, n):
                add_edge(i, j)
    elif mode == "mutual_top_k_weighted_graph":
        top_sets: list[set[int]] = []
        for i in range(n):
            neighbors = sorted((j for j in range(n) if j != i), key=lambda j: (-similarity[i, j], j))[:top_k]
            top_sets.append(set(neighbors))
        for i in range(n):
            for j in top_sets[i]:
                if i in top_sets[j]:
                    add_edge(i, j)
    else:
        for i in range(n):
            neighbors = sorted((j for j in range(n) if j != i), key=lambda j: (-similarity[i, j], j))[:top_k]
            for j in neighbors:
                add_edge(i, j)
    return [(i, j, weight) for (i, j), weight in sorted(edges.items())]


def _louvain_clusters(similarity: np.ndarray, cfg: dict[str, Any], warnings: list[str]) -> tuple[list[list[int]], dict[str, Any]] | None:
    max_compounds = int(cfg.get("max_louvain_compounds", 10000))
    if similarity.shape[0] > max_compounds:
        warnings.append(f"Skipped Louvain clustering: compound count exceeds max_louvain_compounds={max_compounds}.")
        return None
    try:
        import networkx as nx  # type: ignore
        from networkx.algorithms.community import louvain_communities  # type: ignore
    except Exception as exc:
        warnings.append(f"Skipped Louvain clustering: NetworkX Louvain unavailable ({exc}).")
        return None
    graph_cfg = ((cfg.get("graph_construction", {}) or {}).get("louvain", {}) or {})
    graph = nx.Graph()
    graph.add_nodes_from(range(similarity.shape[0]))
    edges = _graph_edges(similarity, graph_cfg)
    weights = [weight for _, _, weight in edges]
    graph.add_weighted_edges_from(edges)
    communities = louvain_communities(
        graph,
        weight="weight",
        resolution=float(cfg.get("louvain_resolution", 1.0)),
        seed=int(cfg.get("random_seed", 42)),
    )
    return [sorted(list(community)) for community in communities], {
        "method": "louvain_community",
        "graph_mode": str(graph_cfg.get("graph_mode", "top_k_weighted_graph")),
        "top_k_neighbors": int(graph_cfg.get("top_k_neighbors", 20)),
        "uses_similarity_threshold": bool(graph_cfg.get("use_similarity_threshold", False)),
        "resolution": float(cfg.get("louvain_resolution", 1.0)),
        "edge_count": len(edges),
        "min_edge_weight": round(min(weights), 6) if weights else None,
        "median_edge_weight": round(float(statistics.median(weights)), 6) if weights else None,
        "max_edge_weight": round(max(weights), 6) if weights else None,
    }


def _leiden_clusters(similarity: np.ndarray, cfg: dict[str, Any], warnings: list[str]) -> tuple[list[list[int]], dict[str, Any]] | None:
    max_compounds = int(cfg.get("max_leiden_compounds", 10000))
    if similarity.shape[0] > max_compounds:
        warnings.append(f"Skipped Leiden clustering: compound count exceeds max_leiden_compounds={max_compounds}.")
        return None
    try:
        import igraph as ig  # type: ignore
        import leidenalg  # type: ignore
    except Exception as exc:
        warnings.append(f"Skipped Leiden clustering: igraph/leidenalg unavailable ({exc}).")
        return None
    graph_cfg = ((cfg.get("graph_construction", {}) or {}).get("leiden", {}) or {})
    edges_with_weights = _graph_edges(similarity, graph_cfg)
    graph = ig.Graph(n=similarity.shape[0], edges=[(i, j) for i, j, _ in edges_with_weights], directed=False)
    weights = [weight for _, _, weight in edges_with_weights]
    if weights:
        graph.es["weight"] = weights
    partition_name = str(cfg.get("leiden_partition_type", "RBConfigurationVertexPartition"))
    partition_type = getattr(leidenalg, partition_name, leidenalg.RBConfigurationVertexPartition)
    kwargs: dict[str, Any] = {"seed": int(cfg.get("random_seed", 42))}
    if weights:
        kwargs["weights"] = "weight"
    if partition_name in {"RBConfigurationVertexPartition", "CPMVertexPartition"}:
        kwargs["resolution_parameter"] = float(cfg.get("leiden_resolution", 1.0))
    partition = leidenalg.find_partition(graph, partition_type, **kwargs)
    return [sorted(list(cluster)) for cluster in partition], {
        "method": "leiden_community",
        "graph_mode": str(graph_cfg.get("graph_mode", "top_k_weighted_graph")),
        "top_k_neighbors": int(graph_cfg.get("top_k_neighbors", 20)),
        "uses_similarity_threshold": bool(graph_cfg.get("use_similarity_threshold", False)),
        "resolution": float(cfg.get("leiden_resolution", 1.0)),
        "partition_type": partition_name,
        "edge_count": len(edges_with_weights),
        "min_edge_weight": round(min(weights), 6) if weights else None,
        "median_edge_weight": round(float(statistics.median(weights)), 6) if weights else None,
        "max_edge_weight": round(max(weights), 6) if weights else None,
    }


def _write_similarity_diagnostics(
    cluster_rows: list[dict[str, Any]],
    ids: list[str],
    similarity: np.ndarray,
    pair_summary: dict[str, Any],
    graph_summaries: list[dict[str, Any]],
    outdir: Path | None,
    cfg: dict[str, Any],
) -> list[str]:
    if outdir is None or not bool(cfg.get("write_similarity_diagnostics", True)):
        return []

    membership_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    for row in cluster_rows:
        group_id = row.get("group_id", "")
        summary = row["summary"]
        summary_rows.append(
            {
                "method": row["method"],
                "parameter_set_id": row.get("parameter_set_id", "default"),
                "cluster_id": row["cluster_local_id"],
                "group_id": group_id,
                "cluster_size": summary["cluster_size"],
                "center_compound_id": summary["center_compound_id"],
                "min_similarity_to_center": summary["min_similarity_to_center"],
                "median_similarity_to_center": summary["median_similarity_to_center"],
                "mean_similarity_to_center": summary["mean_similarity_to_center"],
                "max_similarity_to_center": summary["max_similarity_to_center"],
                "edge_count": summary["edge_count"],
            }
        )
        for compound_id in row["compound_ids"]:
            membership_rows.append(
                {
                    "method": row["method"],
                    "parameter_set_id": row.get("parameter_set_id", "default"),
                    "cluster_id": row["cluster_local_id"],
                    "group_id": group_id,
                    "compound_id": compound_id,
                    "is_center": compound_id == summary["center_compound_id"],
                    "similarity_to_center": round(float(row["similarity_to_center"].get(compound_id, 0.0)), 6),
                    "membership_reason": f"{row['method']}:{row.get('parameter_set_id', 'default')}_cluster={row['cluster_local_id']}",
                }
            )

    write_csv(outdir / "similarity_cluster_membership.csv", membership_rows, SIM_MEMBERSHIP_COLUMNS)
    write_csv(outdir / "similarity_cluster_summary.csv", summary_rows, SIM_SUMMARY_COLUMNS)
    write_json(outdir / "similarity_pair_summary.json", pair_summary)
    write_json(outdir / "similarity_graph_summary.json", graph_summaries)
    return _write_similarity_figures(summary_rows, outdir, cfg)


def _write_similarity_figures(summary_rows: list[dict[str, Any]], outdir: Path, cfg: dict[str, Any]) -> list[str]:
    if not bool(cfg.get("write_similarity_figures", True)):
        return []
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:
        return [f"matplotlib is not available; skipped similarity figures: {exc}"]

    figure_dir = outdir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(summary_rows)

    plt.figure(figsize=(7, 4))
    if not df.empty:
        for method, part in df.groupby("method"):
            plt.hist(part["cluster_size"], bins=min(20, max(3, int(part["cluster_size"].nunique()))), alpha=0.5, label=str(method))
        plt.legend()
    plt.xlabel("cluster size")
    plt.ylabel("cluster count")
    plt.title("Similarity Cluster Size Distribution")
    plt.tight_layout()
    plt.savefig(figure_dir / "similarity_cluster_size_distribution.png", dpi=160)
    plt.close()

    plt.figure(figsize=(7, 4))
    if not df.empty:
        grouped = df.groupby("method").agg(cluster_count=("cluster_id", "count"), assigned_compound_count=("cluster_size", "sum")).reset_index()
        x = np.arange(len(grouped))
        width = 0.35
        plt.bar(x - width / 2, grouped["cluster_count"], width=width, label="cluster_count")
        plt.bar(x + width / 2, grouped["assigned_compound_count"], width=width, label="assigned_compound_count")
        plt.xticks(x, grouped["method"], rotation=30, ha="right")
        plt.legend()
    plt.ylabel("count")
    plt.title("Similarity Method Comparison")
    plt.tight_layout()
    plt.savefig(figure_dir / "similarity_method_comparison.png", dpi=160)
    plt.close()
    return []


def build_similarity_groups(
    compounds: pd.DataFrame,
    config: dict[str, Any],
    outdir: str | Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    if not RDKIT_AVAILABLE:
        return [], [], ["RDKit is not installed; similarity groups were skipped."]

    cfg = config or {}
    warnings: list[str] = []
    radius = int(cfg.get("radius", 2))
    n_bits = int(cfg.get("n_bits", 2048))
    min_cluster_size = int(cfg.get("min_cluster_size", 2))
    ids, fps, _ = _compound_fingerprints(compounds, cfg)
    if len(ids) < 2:
        return [], [], ["Fewer than two valid compounds; similarity groups were skipped."]

    similarity = _similarity_matrix(fps)
    pair_count = len(ids) * (len(ids) - 1) // 2
    default_threshold = float(cfg.get("similarity_threshold", 0.7))
    pair_summary = {
        "compound_count": len(ids),
        "pair_count": pair_count,
        "default_similarity_threshold": default_threshold,
        "edge_count_at_default_threshold": _edge_count(similarity, default_threshold),
        "fingerprint": str(cfg.get("fingerprint", "morgan")),
        "radius": radius,
        "n_bits": n_bits,
        "methods": _methods(cfg),
    }

    all_cluster_rows: list[dict[str, Any]] = []
    graph_summaries: list[dict[str, Any]] = []
    for method in _methods(cfg):
        for parameter_set_id, parameter_override in _parameter_configs(cfg, method):
            method_cfg = _with_parameter_config(cfg, parameter_override)
            result: tuple[list[list[int]], dict[str, Any]] | None
            edge_threshold: float | None = None
            if method == "butina":
                result = _butina_clusters(fps, method_cfg)
                edge_threshold = _method_threshold(method_cfg, "butina")
            elif method == "hierarchical":
                result = _hierarchical_clusters(similarity, method_cfg, warnings)
                edge_threshold = _method_threshold(method_cfg, "hierarchical")
            elif method == "dbscan":
                result = _dbscan_clusters(similarity, method_cfg, warnings)
                edge_threshold = _method_threshold(method_cfg, "dbscan")
            elif method == "louvain":
                result = _louvain_clusters(similarity, method_cfg, warnings)
                edge_threshold = None
            elif method == "leiden":
                result = _leiden_clusters(similarity, method_cfg, warnings)
                edge_threshold = None
            elif method in {"connected_components", "threshold_graph"}:
                result = _threshold_component_clusters(similarity, method_cfg, "connected_components")
                edge_threshold = _method_threshold(method_cfg, "connected_components")
            else:
                warnings.append(f"Unknown similarity clustering method skipped: {method}")
                continue
            if result is None:
                continue
            clusters, definition = result
            definition["parameter_set_id"] = parameter_set_id
            if method in {"louvain", "leiden"}:
                graph_summaries.append(
                    {
                        "method": method,
                        "parameter_set_id": parameter_set_id,
                        "graph_mode": definition.get("graph_mode"),
                        "uses_similarity_threshold": definition.get("uses_similarity_threshold"),
                        "top_k_neighbors": definition.get("top_k_neighbors"),
                        "node_count": len(ids),
                        "edge_count": definition.get("edge_count", 0),
                        "min_edge_weight": definition.get("min_edge_weight"),
                        "median_edge_weight": definition.get("median_edge_weight"),
                        "max_edge_weight": definition.get("max_edge_weight"),
                        "resolution": definition.get("resolution"),
                    }
                )
            method_rows = _cluster_rows(method, parameter_set_id, clusters, ids, similarity, min_cluster_size, edge_threshold, definition)
            all_cluster_rows.extend(method_rows)

    pending = [
        {
            "group_label": f"SIM_{row['method'].upper()}_{row['cluster_local_id']}",
            "compound_ids": row["compound_ids"],
            "cluster_row": row,
            "sort_key": row["sort_key"],
        }
        for row in all_cluster_rows
    ]

    registry: list[dict[str, Any]] = []
    membership: list[dict[str, Any]] = []
    assigned = assign_group_ids(pending, "SIM")
    for item in assigned:
        group_id = item["group_id"]
        row = item["cluster_row"]
        row["group_id"] = group_id
        definition = dict(row["definition"])
        definition.update(
            {
                "fingerprint": str(cfg.get("fingerprint", "morgan")),
                "radius": radius,
                "n_bits": n_bits,
                "parameter_set_id": row.get("parameter_set_id", "default"),
                "cluster_id": row["cluster_local_id"],
                "cluster_center_compound_id": row["summary"]["center_compound_id"],
                "cluster_member_count": row["summary"]["cluster_size"],
            }
        )
        registry.append(
            registry_entry(
                group_id=group_id,
                label=item["group_label"],
                group_type="structural_similarity",
                source="similarity_group_builder",
                source_column=None,
                definition=definition,
                compounds=compounds,
                compound_ids=item["compound_ids"],
            )
        )
        for compound_id in item["compound_ids"]:
            membership.append(
                {
                    "group_id": group_id,
                    "compound_id": compound_id,
                    "membership_source": f"similarity:{row['method']}",
                    "membership_reason": f"{row['method']}:{row.get('parameter_set_id', 'default')}_cluster={row['cluster_local_id']}",
                }
            )

    warnings.extend(
        _write_similarity_diagnostics(
            all_cluster_rows,
            ids,
            similarity,
            pair_summary,
            graph_summaries,
            Path(outdir) if outdir else None,
            cfg,
        )
    )
    return registry, membership, warnings
