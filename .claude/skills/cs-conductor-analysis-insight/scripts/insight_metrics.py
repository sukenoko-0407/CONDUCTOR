from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from insight_groups import registry_fields
from insight_stats import (
    fdr_bh,
    fisher_greater,
    mannwhitney_greater,
    median_abs_deviation,
    median_pairwise_abs_delta,
    rank_values,
    safe_quantile,
)


def activity_thresholds(properties: np.ndarray, config: dict[str, Any]) -> dict[str, float | bool]:
    bins = config.get("activity_bins", {}) or {}
    high_q = float(bins.get("high_quantile", 0.8))
    low_q = float(bins.get("low_quantile", 0.2))
    higher = bool((config.get("property", {}) or {}).get("higher_is_better", True))
    q_low = float(np.quantile(properties, low_q))
    q_high = float(np.quantile(properties, high_q))
    if higher:
        return {
            "higher_is_better": True,
            "high_activity_threshold": q_high,
            "low_activity_threshold": q_low,
        }
    return {
        "higher_is_better": False,
        "high_activity_threshold": q_low,
        "low_activity_threshold": q_high,
    }


def high_low_flags(properties: np.ndarray, thresholds: dict[str, float | bool]) -> tuple[np.ndarray, np.ndarray]:
    higher = bool(thresholds["higher_is_better"])
    high = float(thresholds["high_activity_threshold"])
    low = float(thresholds["low_activity_threshold"])
    if higher:
        return properties >= high, properties <= low
    return properties <= high, properties >= low


def compute_group_metrics(
    property_table: pd.DataFrame,
    membership_df: pd.DataFrame,
    group_columns: list[str],
    registry: dict[str, dict[str, Any]],
    config: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, list[str]], list[str]]:
    warnings: list[str] = []
    filters = config.get("filters", {}) or {}
    min_group_size = int(filters.get("min_group_size", 5))
    max_group_fraction = float(filters.get("max_group_fraction", 0.95))

    merged = property_table.merge(membership_df, on="compound_id", how="inner")
    if merged.empty:
        raise ValueError("No compounds matched between property table and membership matrix.")

    properties = merged["property"].to_numpy(dtype=float)
    thresholds = activity_thresholds(properties, config)
    high_flags, low_flags = high_low_flags(properties, thresholds)
    favorable_property = properties if bool(thresholds["higher_is_better"]) else -properties
    global_high_fraction = float(np.mean(high_flags)) if high_flags.size else float("nan")
    global_low_fraction = float(np.mean(low_flags)) if low_flags.size else float("nan")

    global_info = {
        "property_count": int(len(properties)),
        "property_mean": float(np.mean(properties)),
        "property_median": float(np.median(properties)),
        "property_std": float(np.std(properties, ddof=1)) if len(properties) > 1 else 0.0,
        "property_q20": safe_quantile(properties, 0.2),
        "property_q80": safe_quantile(properties, 0.8),
        "global_high_active_fraction": global_high_fraction,
        "global_low_active_fraction": global_low_fraction,
        **thresholds,
    }

    profile_rows: list[dict[str, Any]] = []
    enrichment_rows: list[dict[str, Any]] = []
    member_rows: list[dict[str, Any]] = []
    group_members: dict[str, list[str]] = {}
    skipped_small = 0
    skipped_large = 0

    all_ids = merged["compound_id"].astype(str).tolist()
    n_total = len(merged)
    for group_id in group_columns:
        mask = merged[group_id].to_numpy(dtype=int) == 1
        group_size = int(mask.sum())
        if group_size < min_group_size:
            skipped_small += 1
            continue
        if n_total > 0 and group_size / n_total > max_group_fraction:
            skipped_large += 1
            continue

        group_values = properties[mask]
        bg_values = properties[~mask]
        group_favorable = favorable_property[mask]
        bg_favorable = favorable_property[~mask]
        group_high = high_flags[mask]
        bg_high = high_flags[~mask]
        group_low = low_flags[mask]
        bg_low = low_flags[~mask]
        ids = [compound_id for compound_id, keep in zip(all_ids, mask) if keep]
        group_members[group_id] = ids

        q25 = safe_quantile(group_values, 0.25)
        q75 = safe_quantile(group_values, 0.75)
        registry_row = registry_fields(group_id, registry)
        profile = {
            **registry_row,
            "group_size": group_size,
            "property_count": int(len(group_values)),
            "property_mean": float(np.mean(group_values)),
            "property_median": float(np.median(group_values)),
            "property_std": float(np.std(group_values, ddof=1)) if len(group_values) > 1 else 0.0,
            "property_variance": float(np.var(group_values, ddof=1)) if len(group_values) > 1 else 0.0,
            "property_min": float(np.min(group_values)),
            "property_max": float(np.max(group_values)),
            "property_q25": q25,
            "property_q75": q75,
            "property_iqr": float(q75 - q25),
            "property_mad": median_abs_deviation(group_values),
            "median_pairwise_abs_property_delta": median_pairwise_abs_delta(group_values),
            "median_shift_vs_global": float(np.median(group_values) - global_info["property_median"]),
            "favorable_median_shift_vs_global": float(np.median(group_favorable) - np.median(favorable_property)),
            "mean_shift_vs_global": float(np.mean(group_values) - global_info["property_mean"]),
            "favorable_mean_shift_vs_global": float(np.mean(group_favorable) - np.mean(favorable_property)),
        }
        profile_rows.append(profile)

        group_high_count = int(group_high.sum())
        group_low_count = int(group_low.sum())
        bg_high_count = int(bg_high.sum())
        bg_low_count = int(bg_low.sum())
        high_odds, high_p = fisher_greater(group_high_count, group_size - group_high_count, bg_high_count, len(bg_high) - bg_high_count)
        low_odds, low_p = fisher_greater(group_low_count, group_size - group_low_count, bg_low_count, len(bg_low) - bg_low_count)
        mw_u, mw_p, rank_biserial = mannwhitney_greater(group_favorable, bg_favorable)
        enrichment_rows.append(
            {
                "group_id": group_id,
                "group_size": group_size,
                "high_active_count": group_high_count,
                "high_active_fraction": float(group_high_count / group_size),
                "global_high_active_fraction": global_high_fraction,
                "high_active_fraction_delta": float(group_high_count / group_size - global_high_fraction),
                "high_active_odds_ratio": high_odds,
                "high_active_pvalue": high_p,
                "low_active_count": group_low_count,
                "low_active_fraction": float(group_low_count / group_size),
                "global_low_active_fraction": global_low_fraction,
                "low_active_fraction_delta": float(group_low_count / group_size - global_low_fraction),
                "low_active_odds_ratio": low_odds,
                "low_active_pvalue": low_p,
                "mannwhitney_u": mw_u,
                "mannwhitney_pvalue": mw_p,
                "rank_biserial_effect": rank_biserial,
            }
        )

        for compound_id, prop, is_high, is_low in zip(np.asarray(all_ids)[mask], group_values, group_high, group_low):
            member_rows.append(
                {
                    "group_id": group_id,
                    "compound_id": str(compound_id),
                    "property": float(prop),
                    "is_high_active": int(bool(is_high)),
                    "is_low_active": int(bool(is_low)),
                }
            )

    if skipped_small:
        warnings.append(f"Skipped {skipped_small} groups with size < {min_group_size}.")
    if skipped_large:
        warnings.append(f"Skipped {skipped_large} near-global groups with fraction > {max_group_fraction}.")

    profile_df = pd.DataFrame(profile_rows)
    enrichment_df = pd.DataFrame(enrichment_rows)
    member_df = pd.DataFrame(member_rows)
    if not enrichment_df.empty:
        enrichment_df["high_active_fdr_qvalue"] = fdr_bh(enrichment_df["high_active_pvalue"].tolist())
        enrichment_df["low_active_fdr_qvalue"] = fdr_bh(enrichment_df["low_active_pvalue"].tolist())
        enrichment_df["mannwhitney_fdr_qvalue"] = fdr_bh(enrichment_df["mannwhitney_pvalue"].tolist())
    return profile_df, enrichment_df, member_df, global_info, group_members, warnings


def add_ranks(summary_df: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    df = summary_df.copy()
    if df.empty:
        return df

    df["rank_high_active_fraction_delta"] = rank_values(df["high_active_fraction_delta"], True)
    df["rank_favorable_median_shift"] = rank_values(df["favorable_median_shift_vs_global"], True)
    df["rank_high_active_fdr_qvalue"] = rank_values(df["high_active_fdr_qvalue"], False)
    df["rank_property_variance"] = rank_values(df["property_variance"], False)
    df["rank_property_iqr"] = rank_values(df["property_iqr"], False)
    df["rank_median_pairwise_abs_property_delta"] = rank_values(df["median_pairwise_abs_property_delta"], False)
    df["rank_structural_diversity_score"] = rank_values(df.get("structural_diversity_score", pd.Series(np.nan, index=df.index)), True)
    df["rank_interpretability_tier"] = rank_values(df["interpretability_tier"], False)

    df["activity_enriched_rank_score"] = df[
        ["rank_high_active_fraction_delta", "rank_favorable_median_shift", "rank_high_active_fdr_qvalue"]
    ].mean(axis=1)
    df["activity_enriched_group_rank"] = rank_values(df["activity_enriched_rank_score"], False)

    df["consistent_rank_score"] = df[
        ["rank_property_variance", "rank_property_iqr", "rank_median_pairwise_abs_property_delta"]
    ].mean(axis=1)
    df["consistent_group_rank"] = rank_values(df["consistent_rank_score"], False)

    if "structural_diversity_score" in df.columns and df["structural_diversity_score"].notna().any():
        df["structurally_diverse_active_rank_score"] = df[
            [
                "rank_high_active_fraction_delta",
                "rank_favorable_median_shift",
                "rank_property_iqr",
                "rank_structural_diversity_score",
            ]
        ].mean(axis=1)
        available = df["structural_diversity_available"].astype(bool) if "structural_diversity_available" in df else True
        df.loc[~available, "structurally_diverse_active_rank_score"] = np.nan
        df["structurally_diverse_active_group_rank"] = rank_values(df["structurally_diverse_active_rank_score"], False)
    else:
        df["structurally_diverse_active_rank_score"] = np.nan
        df["structurally_diverse_active_group_rank"] = np.nan

    df["interpretable_rank_score"] = df[
        ["rank_interpretability_tier", "rank_high_active_fraction_delta", "rank_property_iqr"]
    ].mean(axis=1)
    df["interpretable_group_rank"] = rank_values(df["interpretable_rank_score"], False)

    priority_cols = [
        "activity_enriched_group_rank",
        "consistent_group_rank",
        "interpretable_group_rank",
    ]
    if df["structurally_diverse_active_rank_score"].notna().any():
        priority_cols.append("structurally_diverse_active_group_rank")
    df["insight_priority_prelim_score"] = df[priority_cols].mean(axis=1)
    df["insight_priority_prelim_rank"] = rank_values(df["insight_priority_prelim_score"], False)
    return df


def metric_ranking_rows(summary_df: pd.DataFrame) -> list[dict[str, Any]]:
    metric_defs = [
        ("activity_enriched_rank_score", "lower_is_better"),
        ("structurally_diverse_active_rank_score", "lower_is_better"),
        ("consistent_rank_score", "lower_is_better"),
        ("interpretable_rank_score", "lower_is_better"),
        ("insight_priority_score", "lower_is_better"),
        ("high_active_fraction_delta", "higher_is_better"),
        ("favorable_median_shift_vs_global", "higher_is_better"),
        ("property_variance", "lower_is_better"),
        ("property_iqr", "lower_is_better"),
        ("structural_diversity_score", "higher_is_better"),
        ("mean_ecfp4_tanimoto", "lower_is_better"),
    ]
    rows: list[dict[str, Any]] = []
    for metric_name, direction in metric_defs:
        if metric_name not in summary_df.columns:
            continue
        values = pd.to_numeric(summary_df[metric_name], errors="coerce")
        ordered = values.dropna().sort_values(ascending=(direction == "lower_is_better"))
        for rank, (idx, value) in enumerate(ordered.items(), start=1):
            rows.append(
                {
                    "metric_name": metric_name,
                    "direction": direction,
                    "group_id": str(summary_df.loc[idx, "group_id"]),
                    "metric_value": float(value),
                    "rank": rank,
                }
            )
    return rows
