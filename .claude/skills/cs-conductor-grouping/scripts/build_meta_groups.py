from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from grouping_models import membership_sets, registry_entry


def build_meta_groups(
    compounds: pd.DataFrame,
    registry: list[dict[str, Any]],
    membership: list[dict[str, Any]],
    config: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    cfg = config or {}
    max_meta_groups = int(cfg.get("max_meta_groups", 20))
    sets = membership_sets(membership)
    registry_by_id = {row["group_id"]: row for row in registry}
    candidates: list[tuple[float, int, str, str, set[str]]] = []

    group_ids = sorted(sets)
    for idx, source in enumerate(group_ids):
        for target in group_ids[idx + 1 :]:
            a = sets[source]
            b = sets[target]
            if not a or not b:
                continue
            shared = a & b
            union = a | b
            jaccard = len(shared) / len(union)
            if jaccard >= 0.65 and registry_by_id.get(source, {}).get("group_type") != registry_by_id.get(target, {}).get("group_type"):
                candidates.append((jaccard, len(shared), source, target, union))

    candidates.sort(key=lambda item: (-item[0], -item[1], item[2], item[3]))
    meta_registry: list[dict[str, Any]] = []
    meta_membership: list[dict[str, Any]] = []
    meta_relations: list[dict[str, Any]] = []
    used_pairs: set[tuple[str, str]] = set()

    for index, (jaccard, shared_count, source, target, union) in enumerate(candidates[:max_meta_groups], start=1):
        pair = tuple(sorted((source, target)))
        if pair in used_pairs:
            continue
        used_pairs.add(pair)
        group_id = f"GRP_META_{index:03d}"
        label = f"META_{source}_{target}"
        meta_registry.append(
            registry_entry(
                group_id=group_id,
                label=label,
                group_type="meta_group",
                source="meta_group_builder",
                source_column=None,
                definition={
                    "method": "overlap_meta_group",
                    "member_group_ids": [source, target],
                    "jaccard_overlap": round(jaccard, 6),
                    "shared_compound_count": shared_count,
                },
                compounds=compounds,
                compound_ids=sorted(union),
                exploratory=True,
            )
        )
        for compound_id in sorted(union):
            meta_membership.append(
                {
                    "group_id": group_id,
                    "compound_id": compound_id,
                    "membership_source": "meta_group",
                    "membership_reason": f"union_of={source},{target}",
                }
            )
        for target_group in [source, target]:
            meta_relations.append(
                {
                    "relation_id": "",
                    "source_group_id": group_id,
                    "target_group_id": target_group,
                    "relation_type": "meta_group_of",
                    "metrics": {
                        "jaccard_overlap": round(jaccard, 6),
                        "shared_compound_count": shared_count,
                    },
                }
            )

    return meta_registry, meta_membership, meta_relations, []
