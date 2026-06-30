from __future__ import annotations

from typing import Any


def select_groups(registry: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for group in sorted(registry, key=lambda row: (row.get("group_type", ""), row.get("group_id", ""))):
        reasons: list[str] = []
        priority = "low"
        enabled = False
        wet_count = int(group.get("wet_count", 0))
        compound_count = int(group.get("compound_count", 0))
        group_type = str(group.get("group_type", ""))
        score = 0.0

        if wet_count >= 5:
            reasons.append("sufficient_wet_count")
            enabled = True
            score += 3.0
        elif compound_count >= 2 and group_type == "human_defined":
            reasons.append("human_defined_group")
            enabled = True
            score += 2.0
        elif compound_count >= 2 and group_type in {
            "murcko_scaffold",
            "structural_similarity",
            "brics_fragment",
            "recap_fragment",
            "descriptor_butina_cluster",
            "descriptor_hierarchical_cluster",
            "descriptor_dbscan_cluster",
            "descriptor_louvain_cluster",
            "descriptor_leiden_cluster",
            "descriptor_connected_component",
        }:
            reasons.append("reference_group_with_multiple_compounds")
            enabled = True
            score += 1.0

        if group_type == "frequent_mcs_core":
            reasons.append("interpretable_structural_core")
            score += 2.0
        elif group_type == "human_defined":
            reasons.append("human_interpretability")
            score += 2.0
        elif group_type == "meta_group":
            reasons.append("exploratory_meta_group")
            score += 0.5
        elif group_type == "murcko_scaffold":
            score += 0.75
        elif group_type == "structural_similarity":
            score += 1.0
        elif group_type in {"brics_fragment", "recap_fragment"}:
            reasons.append("interpretable_fragment")
            score += 1.0
        elif group_type.startswith("descriptor_"):
            reasons.append("descriptor_vector_cluster")
            score += 0.75

        if group_type == "murcko_scaffold" and score < 3.0:
            priority = "reference"
        elif score >= 5.0:
            priority = "high"
        elif score >= 2.5:
            priority = "medium"
        else:
            priority = "low"

        if reasons:
            selected.append(
                {
                    "selected_group_id": group["group_id"],
                    "selection_reason": sorted(set(reasons)),
                    "priority": priority,
                    "selection_score": round(score, 3),
                    "enabled_for_downstream": enabled,
                }
            )
    return sorted(selected, key=lambda row: (-float(row.get("selection_score", 0.0)), row["selected_group_id"]))
