from __future__ import annotations

from typing import Any

import pandas as pd


def _fmt(value: Any, digits: int = 3) -> str:
    try:
        if pd.isna(value):
            return "NA"
        if isinstance(value, float):
            return f"{value:.{digits}g}"
        return str(value)
    except Exception:
        return str(value)


def build_top_groups_report(summary_df: pd.DataFrame, global_info: dict[str, Any], top_n: int) -> str:
    lines: list[str] = []
    lines.append("# CONDUCTOR_v2 Phase2 Top Groups Report")
    lines.append("")
    lines.append("This report summarizes top-ranked Group Insight candidates.")
    lines.append("")
    lines.append("## Global Context")
    lines.append("")
    lines.append(f"- Property count: `{global_info.get('property_count')}`")
    lines.append(f"- Global property median: `{_fmt(global_info.get('property_median'))}`")
    lines.append(f"- Global property mean: `{_fmt(global_info.get('property_mean'))}`")
    lines.append(f"- High activity threshold: `{_fmt(global_info.get('high_activity_threshold'))}`")
    lines.append(f"- Low activity threshold: `{_fmt(global_info.get('low_activity_threshold'))}`")
    lines.append(f"- Higher is better: `{global_info.get('higher_is_better')}`")
    lines.append("")
    lines.append("## Top Groups")
    lines.append("")

    top = summary_df.sort_values("insight_priority_rank").head(top_n)
    for display_rank, (_, row) in enumerate(top.iterrows(), start=1):
        lines.append(f"### {display_rank}. {row['group_id']} - {row.get('group_label', '')}")
        lines.append("")
        lines.append(f"- Insight priority rank: `{_fmt(row.get('insight_priority_rank'), 0)}`")
        lines.append(f"- Type/source: `{row.get('group_type')}` / `{row.get('group_source')}`")
        lines.append(f"- Size: `{row.get('group_size')}`")
        lines.append(f"- Median property: `{_fmt(row.get('property_median'))}`")
        lines.append(f"- High-active fraction delta: `{_fmt(row.get('high_active_fraction_delta'))}`")
        lines.append(f"- Property IQR: `{_fmt(row.get('property_iqr'))}`")
        lines.append(f"- Mean ECFP4 Tanimoto: `{_fmt(row.get('mean_ecfp4_tanimoto'))}`")
        lines.append(f"- Structural diversity score: `{_fmt(row.get('structural_diversity_score'))}`")
        lines.append(f"- Activity enriched rank: `{_fmt(row.get('activity_enriched_group_rank'), 0)}`")
        lines.append(f"- Structurally diverse active rank: `{_fmt(row.get('structurally_diverse_active_group_rank'), 0)}`")
        lines.append(f"- Consistent rank: `{_fmt(row.get('consistent_group_rank'), 0)}`")
        lines.append(f"- Redundancy flag: `{_fmt(row.get('redundancy_flag'), 0)}`")
        lines.append(f"- Interpretability: `{row.get('interpretability_reason')}`")
        if row.get("redundant_with_group_id"):
            lines.append(f"- Caution: overlaps strongly with `{row.get('redundant_with_group_id')}`.")
        if pd.notna(row.get("mean_ecfp4_tanimoto")) and row.get("high_active_fraction_delta", 0) > 0:
            if row.get("mean_ecfp4_tanimoto", 1) < 0.4:
                lines.append("- Note: high activity enrichment despite low mean ECFP4 Tanimoto may indicate a non-obvious active pattern.")
        lines.append("- Caution: treat this as prioritization evidence, not a mechanistic SAR claim.")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
