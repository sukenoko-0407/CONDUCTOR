from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import Any, Iterable

import pandas as pd


GROUP_PREFIXES = {
    "human": "HUM",
    "human_series": "HSER",
    "human_scaffold": "HSCF",
    "murcko": "MURCKO",
    "mcs": "MCS",
    "similarity": "SIM",
    "meta": "META",
    "auto_rgroup": "ARG",
}


def stable_slug(value: Any, max_len: int = 48) -> str:
    text = str(value).strip()
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
    text = text.strip("_.-")
    return text[:max_len] or "NA"


def stable_hash(value: Any, length: int = 12) -> str:
    return hashlib.sha1(str(value).encode("utf-8")).hexdigest()[:length]


def group_prefix_for_human_column(column: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", column.lower()).strip("_")
    if normalized == "human_series" or normalized.endswith("_series") or normalized == "series":
        return GROUP_PREFIXES["human_series"]
    if normalized == "human_scaffold" or normalized.endswith("_scaffold") or normalized in {"scaffold", "core", "core_id"}:
        return GROUP_PREFIXES["human_scaffold"]
    return GROUP_PREFIXES["human"]


def assign_group_ids(groups: list[dict[str, Any]], prefix: str) -> list[dict[str, Any]]:
    ordered = sorted(groups, key=lambda item: (str(item.get("sort_key", "")), str(item.get("group_label", ""))))
    for index, group in enumerate(ordered, start=1):
        group["group_id"] = f"GRP_{prefix}_{index:03d}"
    return ordered


def counts_for_members(compounds: pd.DataFrame, compound_ids: Iterable[str]) -> tuple[int, int, int]:
    wanted = {str(compound_id) for compound_id in compound_ids}
    subset = compounds[compounds["compound_id"].astype(str).isin(wanted)]
    total = int(len(subset))
    if "is_virtual" not in subset.columns:
        return total, total, 0
    virtual_count = int(subset["is_virtual"].fillna(False).astype(bool).sum())
    wet_count = total - virtual_count
    return total, wet_count, virtual_count


def registry_entry(
    group_id: str,
    label: str,
    group_type: str,
    source: str,
    source_column: str | None,
    definition: dict[str, Any],
    compounds: pd.DataFrame,
    compound_ids: Iterable[str],
    exploratory: bool = False,
    status: str = "passed",
) -> dict[str, Any]:
    compound_id_list = list(compound_ids)
    total, wet_count, virtual_count = counts_for_members(compounds, compound_id_list)
    return {
        "group_id": group_id,
        "group_label": str(label),
        "group_type": group_type,
        "group_source": source,
        "source_column": source_column,
        "activity_blind": True,
        "definition": definition,
        "compound_count": total,
        "wet_count": wet_count,
        "virtual_count": virtual_count,
        "activity_summary": {"available": False, "count": 0},
        "quality": {"status": status, "exploratory": exploratory},
    }


def membership_sets(membership: list[dict[str, Any]]) -> dict[str, set[str]]:
    sets: dict[str, set[str]] = defaultdict(set)
    for row in membership:
        sets[str(row["group_id"])].add(str(row["compound_id"]))
    return dict(sets)


def relation_rows_from_overlap(
    membership: list[dict[str, Any]],
    min_jaccard: float = 0.5,
    max_relations: int | None = 50000,
) -> list[dict[str, Any]]:
    sets = membership_sets(membership)
    relations: list[dict[str, Any]] = []
    relation_index = 1
    group_ids = sorted(sets)
    for idx, source in enumerate(group_ids):
        for target in group_ids[idx + 1 :]:
            a = sets[source]
            b = sets[target]
            if not a or not b:
                continue
            shared = a & b
            if not shared:
                continue
            union = a | b
            jaccard = len(shared) / len(union)
            subset = a <= b or b <= a
            if jaccard >= min_jaccard or subset:
                relation_type = "subset_of" if subset else "overlaps_with"
                relations.append(
                    {
                        "relation_id": f"REL_{relation_index:04d}",
                        "source_group_id": source,
                        "target_group_id": target,
                        "relation_type": relation_type,
                        "metrics": {
                            "jaccard_overlap": round(jaccard, 6),
                            "shared_compound_count": len(shared),
                            "source_compound_count": len(a),
                            "target_compound_count": len(b),
                        },
                    }
                )
                relation_index += 1
                if max_relations is not None and max_relations > 0 and len(relations) >= max_relations:
                    return relations
    return relations
