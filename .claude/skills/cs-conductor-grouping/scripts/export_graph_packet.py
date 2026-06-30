from __future__ import annotations

from typing import Any


def export_graph_packet(
    registry: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    membership: list[dict[str, Any]],
) -> dict[str, Any]:
    node_memberships: dict[str, int] = {}
    for row in membership:
        group_id = str(row["group_id"])
        node_memberships[group_id] = node_memberships.get(group_id, 0) + 1

    nodes = [
        {
            "id": row["group_id"],
            "label": row["group_label"],
            "type": row["group_type"],
            "source": row["group_source"],
            "compound_count": row.get("compound_count", node_memberships.get(row["group_id"], 0)),
            "wet_count": row.get("wet_count", 0),
            "virtual_count": row.get("virtual_count", 0),
        }
        for row in registry
    ]
    edges = [
        {
            "id": row["relation_id"],
            "source": row["source_group_id"],
            "target": row["target_group_id"],
            "type": row["relation_type"],
            "metrics": row.get("metrics", {}),
        }
        for row in relations
    ]
    return {
        "schema_version": "0.1",
        "nodes": nodes,
        "edges": edges,
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "membership_count": len(membership),
        },
    }
