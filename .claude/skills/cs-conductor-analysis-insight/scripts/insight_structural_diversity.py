from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from insight_config import detect_id_column
from insight_io import read_csv
from insight_stats import safe_quantile


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


def load_ecfp4_bits(path: Path) -> tuple[dict[str, int], np.ndarray, list[str]]:
    df = read_csv(path)
    id_column = detect_id_column(list(df.columns), None)
    df[id_column] = df[id_column].astype(str).str.strip()
    df = df.drop_duplicates(subset=[id_column], keep="first")

    excluded = {column.lower() for column in NON_FEATURE_COLUMNS}
    feature_cols: list[str] = []
    for column in df.columns:
        if str(column).lower() in excluded or column == id_column:
            continue
        numeric = pd.to_numeric(df[column], errors="coerce")
        if numeric.notna().any():
            feature_cols.append(str(column))
    if not feature_cols:
        raise ValueError(f"No numeric ECFP4 bit columns found in {path}")

    matrix = df[feature_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0).to_numpy(dtype=float) > 0
    ids = df[id_column].astype(str).tolist()
    return {compound_id: idx for idx, compound_id in enumerate(ids)}, matrix, feature_cols


def pairwise_tanimoto_from_matrix(bits: np.ndarray, indices: list[int]) -> np.ndarray:
    if len(indices) < 2:
        return np.asarray([], dtype=float)
    subset = bits[indices].astype(np.uint8)
    intersection = subset @ subset.T
    counts = subset.sum(axis=1).astype(float)
    union = counts[:, None] + counts[None, :] - intersection
    similarity = np.divide(intersection, union, out=np.ones_like(intersection, dtype=float), where=union != 0)
    return similarity[np.triu_indices(len(indices), k=1)].astype(float)


def sampled_pairwise_tanimoto(bits: np.ndarray, indices: list[int], sample_count: int, seed: int) -> np.ndarray:
    if len(indices) < 2:
        return np.asarray([], dtype=float)
    rng = np.random.default_rng(seed)
    pairs: set[tuple[int, int]] = set()
    max_pairs = len(indices) * (len(indices) - 1) // 2
    target = min(sample_count, max_pairs)
    while len(pairs) < target:
        a = int(rng.integers(0, len(indices)))
        b = int(rng.integers(0, len(indices)))
        if a == b:
            continue
        if a > b:
            a, b = b, a
        pairs.add((a, b))
    values: list[float] = []
    for a, b in pairs:
        va = bits[indices[a]]
        vb = bits[indices[b]]
        intersection = float(np.logical_and(va, vb).sum())
        union = float(np.logical_or(va, vb).sum())
        values.append(1.0 if union == 0.0 else intersection / union)
    return np.asarray(values, dtype=float)


def structural_diversity_rows(
    group_members: dict[str, list[str]],
    descriptor_path: Path,
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    div_cfg = config.get("structural_diversity", {}) or {}
    if not bool(div_cfg.get("enabled", True)):
        return [], ["Structural diversity disabled by config."]
    if not descriptor_path.exists():
        return [], [f"ECFP4 descriptor file not found; structural diversity skipped: {descriptor_path}"]

    id_to_index, bits, feature_cols = load_ecfp4_bits(descriptor_path)
    max_exact = int(div_cfg.get("max_exact_pair_count", 200000))
    sample_count = int(div_cfg.get("sample_pair_count", 200000))
    seed = int(div_cfg.get("random_seed", 42))
    rows: list[dict[str, Any]] = []

    for group_id, members in group_members.items():
        indices = [id_to_index[compound_id] for compound_id in members if compound_id in id_to_index]
        pair_count = len(indices) * (len(indices) - 1) // 2
        if len(indices) < 2:
            rows.append(
                {
                    "group_id": group_id,
                    "ecfp4_matched_compound_count": len(indices),
                    "ecfp4_pair_count": pair_count,
                    "structural_diversity_available": False,
                    "structural_diversity_exact": False,
                    "mean_ecfp4_tanimoto": float("nan"),
                    "median_ecfp4_tanimoto": float("nan"),
                    "p25_ecfp4_tanimoto": float("nan"),
                    "p75_ecfp4_tanimoto": float("nan"),
                    "min_ecfp4_tanimoto": float("nan"),
                    "max_ecfp4_tanimoto": float("nan"),
                    "structural_diversity_score": float("nan"),
                    "ecfp4_feature_count": len(feature_cols),
                }
            )
            continue

        if pair_count <= max_exact:
            values = pairwise_tanimoto_from_matrix(bits, indices)
            exact = True
        else:
            values = sampled_pairwise_tanimoto(bits, indices, sample_count, seed)
            exact = False
            warnings.append(f"{group_id}: sampled {len(values)} of {pair_count} ECFP4 pairs.")

        mean_value = float(np.mean(values)) if values.size else float("nan")
        rows.append(
            {
                "group_id": group_id,
                "ecfp4_matched_compound_count": len(indices),
                "ecfp4_pair_count": pair_count,
                "structural_diversity_available": bool(values.size),
                "structural_diversity_exact": exact,
                "mean_ecfp4_tanimoto": mean_value,
                "median_ecfp4_tanimoto": float(np.median(values)) if values.size else float("nan"),
                "p25_ecfp4_tanimoto": safe_quantile(values, 0.25),
                "p75_ecfp4_tanimoto": safe_quantile(values, 0.75),
                "min_ecfp4_tanimoto": float(np.min(values)) if values.size else float("nan"),
                "max_ecfp4_tanimoto": float(np.max(values)) if values.size else float("nan"),
                "structural_diversity_score": float(1.0 - mean_value) if values.size else float("nan"),
                "ecfp4_feature_count": len(feature_cols),
            }
        )
    return rows, warnings
