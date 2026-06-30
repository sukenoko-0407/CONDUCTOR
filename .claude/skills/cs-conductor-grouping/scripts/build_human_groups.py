from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from grouping_models import assign_group_ids, group_prefix_for_human_column, registry_entry, stable_slug


SPLIT_PATTERN = re.compile(r"\s*[;|,]\s*")


def split_group_values(value: Any) -> list[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    text = str(value).strip()
    if not text:
        return []
    return [item.strip() for item in SPLIT_PATTERN.split(text) if item.strip()]


def build_human_groups(
    compounds: pd.DataFrame,
    grouping_columns: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    registry: list[dict[str, Any]] = []
    membership: list[dict[str, Any]] = []
    warnings: list[str] = []

    for column in grouping_columns:
        if column not in compounds.columns:
            warnings.append(f"Grouping column not found in standardized compounds: {column}")
            continue

        value_members: dict[str, set[str]] = defaultdict(set)
        for _, row in compounds.iterrows():
            compound_id = str(row["compound_id"])
            for group_value in split_group_values(row.get(column)):
                value_members[group_value].add(compound_id)

        prefix = group_prefix_for_human_column(column)
        pending: list[dict[str, Any]] = []
        for value, compound_ids in value_members.items():
            pending.append(
                {
                    "group_label": str(value),
                    "source_column": column,
                    "compound_ids": sorted(compound_ids),
                    "sort_key": f"{column}:{stable_slug(value)}",
                }
            )

        for item in assign_group_ids(pending, prefix):
            group_id = item["group_id"]
            registry.append(
                registry_entry(
                    group_id=group_id,
                    label=item["group_label"],
                    group_type="human_defined",
                    source="human_group_builder",
                    source_column=column,
                    definition={"method": "human_column", "column": column, "value": item["group_label"]},
                    compounds=compounds,
                    compound_ids=item["compound_ids"],
                )
            )
            for compound_id in item["compound_ids"]:
                membership.append(
                    {
                        "group_id": group_id,
                        "compound_id": compound_id,
                        "membership_source": "human_column",
                        "membership_reason": f"{column}={item['group_label']}",
                    }
                )

    return registry, membership, warnings
