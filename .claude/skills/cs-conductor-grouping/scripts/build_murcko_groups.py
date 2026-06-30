from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from grouping_models import assign_group_ids, registry_entry, stable_hash

try:
    from rdkit import Chem  # type: ignore
    from rdkit import RDLogger  # type: ignore
    from rdkit.Chem.Scaffolds import MurckoScaffold  # type: ignore

    RDLogger.DisableLog("rdApp.error")
    RDLogger.DisableLog("rdApp.warning")
    RDKIT_AVAILABLE = True
except Exception:
    Chem = None
    MurckoScaffold = None
    RDKIT_AVAILABLE = False


def build_murcko_groups(
    compounds: pd.DataFrame,
    config: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    if not RDKIT_AVAILABLE:
        return [], [], ["RDKit is not installed; Murcko scaffold groups were skipped."]

    scaffold_members: dict[str, set[str]] = defaultdict(set)
    warnings: list[str] = []
    for _, row in compounds.iterrows():
        smiles = row.get("canonical_smiles")
        mol = Chem.MolFromSmiles(str(smiles))
        if mol is None:
            continue
        scaffold = MurckoScaffold.MurckoScaffoldSmiles(mol=mol, includeChirality=True)
        if not scaffold:
            scaffold = Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)
        scaffold_members[scaffold].add(str(row["compound_id"]))

    pending = [
        {"group_label": f"MURCKO_{stable_hash(scaffold, 8)}", "scaffold_smiles": scaffold, "compound_ids": sorted(ids), "sort_key": scaffold}
        for scaffold, ids in scaffold_members.items()
        if ids
    ]

    registry: list[dict[str, Any]] = []
    membership: list[dict[str, Any]] = []
    for item in assign_group_ids(pending, "MURCKO"):
        group_id = item["group_id"]
        registry.append(
            registry_entry(
                group_id=group_id,
                label=item["group_label"],
                group_type="murcko_scaffold",
                source="murcko_group_builder",
                source_column=None,
                definition={"method": "bemis_murcko", "scaffold_smiles": item["scaffold_smiles"]},
                compounds=compounds,
                compound_ids=item["compound_ids"],
                exploratory=False,
            )
        )
        for compound_id in item["compound_ids"]:
            membership.append(
                {
                    "group_id": group_id,
                    "compound_id": compound_id,
                    "membership_source": "murcko",
                    "membership_reason": f"scaffold_hash={stable_hash(item['scaffold_smiles'], 12)}",
                }
            )
    return registry, membership, warnings
