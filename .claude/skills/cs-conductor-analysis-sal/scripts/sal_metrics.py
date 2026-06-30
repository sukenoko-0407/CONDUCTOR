from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


def _safe_quantile(values: np.ndarray, q: float) -> float:
    if values.size == 0:
        return float("nan")
    return float(np.quantile(values, q))


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 2 or len(y) < 2:
        return float("nan")
    xr = pd.Series(x).rank(method="average").to_numpy(dtype=float)
    yr = pd.Series(y).rank(method="average").to_numpy(dtype=float)
    return _pearson(xr, yr)


def _pearson(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 2 or len(y) < 2:
        return float("nan")
    if float(np.std(x)) == 0.0 or float(np.std(y)) == 0.0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def _distribution(values: np.ndarray, prefix: str = "") -> dict[str, float | int]:
    return {
        f"{prefix}count": int(values.size),
        f"{prefix}mean": float(np.mean(values)) if values.size else float("nan"),
        f"{prefix}median": float(np.median(values)) if values.size else float("nan"),
        f"{prefix}p75": _safe_quantile(values, 0.75),
        f"{prefix}p90": _safe_quantile(values, 0.90),
        f"{prefix}p95": _safe_quantile(values, 0.95),
        f"{prefix}p99": _safe_quantile(values, 0.99),
        f"{prefix}max": float(np.max(values)) if values.size else float("nan"),
    }


def pairwise_distance(matrix: np.ndarray, metric: str) -> np.ndarray:
    metric = metric.lower()
    n = matrix.shape[0]
    if n == 0:
        return np.empty((0, 0), dtype=float)

    if metric in {"tanimoto", "jaccard"}:
        binary = matrix > 0
        intersection = binary.astype(float) @ binary.astype(float).T
        counts = binary.sum(axis=1).astype(float)
        union = counts[:, None] + counts[None, :] - intersection
        similarity = np.divide(intersection, union, out=np.ones_like(intersection), where=union != 0)
        distance = 1.0 - similarity
    elif metric == "cosine":
        norms = np.linalg.norm(matrix, axis=1)
        norms[norms == 0] = 1.0
        normalized = matrix / norms[:, None]
        similarity = np.clip(normalized @ normalized.T, -1.0, 1.0)
        distance = 1.0 - similarity
    elif metric in {"euclidean", "standardized_euclidean"}:
        diff = matrix[:, None, :] - matrix[None, :, :]
        distance = np.sqrt(np.sum(diff * diff, axis=2))
    elif metric == "manhattan":
        diff = np.abs(matrix[:, None, :] - matrix[None, :, :])
        distance = np.sum(diff, axis=2)
    elif metric == "correlation":
        centered = matrix - matrix.mean(axis=1, keepdims=True)
        norms = np.linalg.norm(centered, axis=1)
        norms[norms == 0] = 1.0
        normalized = centered / norms[:, None]
        corr = np.clip(normalized @ normalized.T, -1.0, 1.0)
        distance = 1.0 - corr
    else:
        raise ValueError(f"Unsupported metric: {metric}")

    distance = np.asarray(distance, dtype=float)
    distance[~np.isfinite(distance)] = 0.0
    np.fill_diagonal(distance, 0.0)
    return distance


def knn_indices(distance: np.ndarray, k: int) -> np.ndarray:
    n = distance.shape[0]
    if n <= 1:
        return np.empty((n, 0), dtype=int)
    effective_k = min(k, n - 1)
    order = np.argsort(distance, axis=1)
    return order[:, 1 : effective_k + 1]


def compute_sal_metrics(
    representation_id: str,
    descriptor_file: str,
    ids: list[str],
    properties: np.ndarray,
    distance: np.ndarray,
    neighbors: np.ndarray,
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    epsilon = float((config.get("sali", {}) or {}).get("epsilon", 1e-6))
    include_self = bool((config.get("knn", {}) or {}).get("include_self_in_local_variance", True))
    edge_rows: list[dict[str, Any]] = []
    local_rows: list[dict[str, Any]] = []

    for i, neighbor_row in enumerate(neighbors):
        deltas: list[float] = []
        neighbor_values: list[float] = []
        for rank, j in enumerate(neighbor_row, start=1):
            dist = float(distance[i, j])
            delta = abs(float(properties[i]) - float(properties[j]))
            sali = delta / max(dist, epsilon)
            deltas.append(delta)
            neighbor_values.append(float(properties[j]))
            edge_rows.append(
                {
                    "representation_id": representation_id,
                    "descriptor_file": descriptor_file,
                    "compound_id": ids[i],
                    "neighbor_compound_id": ids[j],
                    "neighbor_rank": rank,
                    "distance": dist,
                    "property": float(properties[i]),
                    "neighbor_property": float(properties[j]),
                    "abs_delta_property": delta,
                    "sali": sali,
                }
            )
        local_values = ([float(properties[i])] if include_self else []) + neighbor_values
        local_array = np.asarray(local_values, dtype=float)
        delta_array = np.asarray(deltas, dtype=float)
        local_rows.append(
            {
                "representation_id": representation_id,
                "descriptor_file": descriptor_file,
                "compound_id": ids[i],
                "property": float(properties[i]),
                "local_mean_property": float(np.mean(local_array)) if local_array.size else float("nan"),
                "local_median_property": float(np.median(local_array)) if local_array.size else float("nan"),
                "local_property_variance": float(np.var(local_array, ddof=1)) if local_array.size > 1 else 0.0,
                "median_abs_delta_property_among_knn": float(np.median(delta_array)) if delta_array.size else float("nan"),
                "mean_abs_delta_property_among_knn": float(np.mean(delta_array)) if delta_array.size else float("nan"),
                "max_abs_delta_property_among_knn": float(np.max(delta_array)) if delta_array.size else float("nan"),
            }
        )

    edge_df = pd.DataFrame(edge_rows)
    local_df = pd.DataFrame(local_rows)
    if not edge_df.empty:
        distance_percentile = edge_df["distance"].rank(method="average", pct=True).astype(float)
        edge_df["distance_percentile_within_representation"] = distance_percentile
        edge_df["normalized_sali"] = edge_df["abs_delta_property"] / np.maximum(distance_percentile, epsilon)
        edge_rows = edge_df.to_dict(orient="records")

    sali_values = edge_df["sali"].to_numpy(dtype=float) if not edge_df.empty else np.asarray([], dtype=float)
    normalized_sali_values = (
        edge_df["normalized_sali"].to_numpy(dtype=float) if not edge_df.empty else np.asarray([], dtype=float)
    )
    distances = edge_df["distance"].to_numpy(dtype=float) if not edge_df.empty else np.asarray([], dtype=float)
    deltas = edge_df["abs_delta_property"].to_numpy(dtype=float) if not edge_df.empty else np.asarray([], dtype=float)
    prop_i = edge_df["property"].to_numpy(dtype=float) if not edge_df.empty else np.asarray([], dtype=float)
    prop_j = edge_df["neighbor_property"].to_numpy(dtype=float) if not edge_df.empty else np.asarray([], dtype=float)
    local_var = local_df["local_property_variance"].to_numpy(dtype=float) if not local_df.empty else np.asarray([], dtype=float)
    local_delta = local_df["median_abs_delta_property_among_knn"].to_numpy(dtype=float) if not local_df.empty else np.asarray([], dtype=float)

    sali_distribution = {
        "representation_id": representation_id,
        "descriptor_file": descriptor_file,
    }
    sali_distribution.update(_distribution(sali_values))
    sali_distribution.update(_distribution(normalized_sali_values, "normalized_"))

    summary = {
        "representation_id": representation_id,
        "descriptor_file": descriptor_file,
        "compound_count": len(ids),
        "effective_k": int(neighbors.shape[1]) if neighbors.ndim == 2 else 0,
        "median_sali": sali_distribution["median"],
        "p90_sali": sali_distribution["p90"],
        "p95_sali": sali_distribution["p95"],
        "median_normalized_sali": sali_distribution["normalized_median"],
        "p90_normalized_sali": sali_distribution["normalized_p90"],
        "p95_normalized_sali": sali_distribution["normalized_p95"],
        "median_local_property_variance": float(np.median(local_var)) if local_var.size else float("nan"),
        "p90_local_property_variance": _safe_quantile(local_var, 0.90),
        "median_abs_delta_property_among_knn": float(np.median(local_delta)) if local_delta.size else float("nan"),
        "distance_property_spearman_correlation": _spearman(distances, deltas),
        "neighbor_property_autocorrelation": _pearson(prop_i, prop_j),
        "neighbor_property_spearman_autocorrelation": _spearman(prop_i, prop_j),
    }
    return edge_rows, local_rows, summary, sali_distribution


def build_metric_ranking(summary_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    metric_defs = [
        ("primary_comparison_rank_score", "lower_is_better"),
        ("median_abs_delta_property_among_knn", "lower_is_better"),
        ("median_local_property_variance", "lower_is_better"),
        ("neighbor_property_autocorrelation", "higher_is_better"),
        ("median_sali", "lower_is_better"),
        ("p90_sali", "lower_is_better"),
        ("p95_sali", "lower_is_better"),
        ("median_normalized_sali", "lower_is_better"),
        ("p90_normalized_sali", "lower_is_better"),
        ("p95_normalized_sali", "lower_is_better"),
        ("distance_property_spearman_correlation", "higher_is_better"),
    ]
    rows: list[dict[str, Any]] = []
    for metric_name, direction in metric_defs:
        values = []
        for row in summary_rows:
            value = row.get(metric_name)
            if value is None or (isinstance(value, float) and math.isnan(value)):
                continue
            values.append((str(row["representation_id"]), str(row["descriptor_file"]), float(value)))
        reverse = direction == "higher_is_better"
        ordered = sorted(values, key=lambda item: item[2], reverse=reverse)
        for rank, (representation_id, descriptor_file, value) in enumerate(ordered, start=1):
            rows.append(
                {
                    "metric_name": metric_name,
                    "direction": direction,
                    "representation_id": representation_id,
                    "descriptor_file": descriptor_file,
                    "metric_value": value,
                    "rank": rank,
                }
            )
    return rows
