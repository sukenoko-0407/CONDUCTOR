from __future__ import annotations

import numpy as np
import pandas as pd

from insight_stats import rank_values


def compute_overlap(
    membership_df: pd.DataFrame,
    summary_df: pd.DataFrame,
    threshold: float,
    redundancy_penalty: float,
    penalty_enabled: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if summary_df.empty:
        return pd.DataFrame(), summary_df

    group_ids = summary_df["group_id"].astype(str).tolist()
    matrix = membership_df[["compound_id", *group_ids]].copy()
    x = matrix[group_ids].to_numpy(dtype=np.int32)
    sizes = x.sum(axis=0).astype(np.int32)
    intersections = x.T @ x
    unions = sizes[:, None] + sizes[None, :] - intersections
    jaccard = np.divide(intersections, unions, out=np.zeros_like(intersections, dtype=float), where=unions != 0)
    np.fill_diagonal(jaccard, 0.0)

    order = summary_df.sort_values("insight_priority_prelim_score", na_position="last").index.tolist()
    position_by_index = {idx: pos for pos, idx in enumerate(summary_df.index)}
    index_by_group = {group_id: idx for group_id, idx in zip(group_ids, summary_df.index)}
    rows: list[dict[str, object]] = []
    updated = summary_df.copy()

    for idx in summary_df.index:
        group_id = str(summary_df.loc[idx, "group_id"])
        pos = position_by_index[idx]
        sims = jaccard[pos]
        max_any_pos = int(np.argmax(sims)) if sims.size else -1
        max_any = float(sims[max_any_pos]) if max_any_pos >= 0 else 0.0
        max_any_group = group_ids[max_any_pos] if max_any_pos >= 0 and max_any > 0 else ""

        current_order_pos = order.index(idx)
        higher_indices = order[:current_order_pos]
        higher_positions = [position_by_index[hidx] for hidx in higher_indices]
        if higher_positions:
            higher_sims = sims[higher_positions]
            best_local = int(np.argmax(higher_sims))
            max_higher = float(higher_sims[best_local])
            redundant_group = str(summary_df.loc[higher_indices[best_local], "group_id"]) if max_higher > 0 else ""
        else:
            max_higher = 0.0
            redundant_group = ""

        overlap_count = int((sims >= threshold).sum())
        redundant = bool(max_higher >= threshold)
        rows.append(
            {
                "group_id": group_id,
                "max_jaccard_with_any_group": max_any,
                "max_jaccard_group_id": max_any_group,
                "max_jaccard_with_higher_ranked_group": max_higher,
                "redundant_with_group_id": redundant_group if redundant else "",
                "overlap_count_above_threshold": overlap_count,
                "redundancy_flag": int(redundant),
            }
        )

    overlap_df = pd.DataFrame(rows)
    updated = updated.merge(overlap_df, on="group_id", how="left")
    if penalty_enabled:
        updated["insight_priority_score"] = updated["insight_priority_prelim_score"] + (
            updated["redundancy_flag"].fillna(0).astype(float) * redundancy_penalty
        )
    else:
        updated["insight_priority_score"] = updated["insight_priority_prelim_score"]
    updated["insight_priority_rank"] = rank_values(updated["insight_priority_score"], False)
    return overlap_df, updated
