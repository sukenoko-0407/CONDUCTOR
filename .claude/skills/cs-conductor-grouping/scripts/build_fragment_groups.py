from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from grouping_io import write_csv
from grouping_models import assign_group_ids, registry_entry, stable_hash

try:
    from rdkit import Chem  # type: ignore
    from rdkit import RDLogger  # type: ignore
    from rdkit.Chem import BRICS, Recap  # type: ignore

    RDLogger.DisableLog("rdApp.error")
    RDLogger.DisableLog("rdApp.warning")
    RDKIT_AVAILABLE = True
except Exception:
    Chem = None
    BRICS = None
    Recap = None
    RDKIT_AVAILABLE = False


FRAGMENT_SUMMARY_COLUMNS = [
    "method",
    "fragment_smiles",
    "fragment_heavy_atoms",
    "compound_count",
    "wet_count",
    "virtual_count",
    "group_id",
]


def _fragment_heavy_atoms(fragment_smiles: str) -> int:
    if not RDKIT_AVAILABLE:
        return 0
    mol = Chem.MolFromSmiles(fragment_smiles)
    if mol is None:
        return 0
    return int(mol.GetNumHeavyAtoms())


def _brics_fragments(mol: Any) -> set[str]:
    try:
        return {str(fragment) for fragment in BRICS.BRICSDecompose(mol)}
    except Exception:
        return set()


def _recap_fragments(mol: Any) -> set[str]:
    try:
        tree = Recap.RecapDecompose(mol)
        return {str(fragment) for fragment in tree.GetLeaves().keys()} if tree is not None else set()
    except Exception:
        return set()


def build_fragment_groups(
    compounds: pd.DataFrame,
    config: dict[str, Any],
    outdir: str | Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    if not RDKIT_AVAILABLE:
        return [], [], ["RDKit is not installed; BRICS/RECAP fragment groups were skipped."]

    cfg = config or {}
    min_compounds = int(cfg.get("min_fragment_compound_count", 3))
    min_heavy_atoms = int(cfg.get("min_fragment_heavy_atoms", 4))
    max_per_method = int(cfg.get("max_fragments_per_method", 200))
    include_single_atom = bool(cfg.get("include_single_atom_fragments", False))
    warnings: list[str] = []

    members: dict[str, dict[str, set[str]]] = {"brics": defaultdict(set), "recap": defaultdict(set)}
    for _, row in compounds.sort_values("compound_id").iterrows():
        canonical = str(row.get("canonical_smiles", "")).strip()
        if not canonical:
            continue
        mol = Chem.MolFromSmiles(canonical)
        if mol is None:
            continue
        compound_id = str(row["compound_id"])
        for fragment in _brics_fragments(mol):
            members["brics"][fragment].add(compound_id)
        for fragment in _recap_fragments(mol):
            members["recap"][fragment].add(compound_id)

    pending: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    for method in ["brics", "recap"]:
        method_items: list[dict[str, Any]] = []
        for fragment, compound_ids in members[method].items():
            heavy_atoms = _fragment_heavy_atoms(fragment)
            if not include_single_atom and heavy_atoms <= 1:
                continue
            if heavy_atoms < min_heavy_atoms:
                continue
            if len(compound_ids) < min_compounds:
                continue
            method_items.append(
                {
                    "method": method,
                    "fragment_smiles": fragment,
                    "fragment_heavy_atoms": heavy_atoms,
                    "compound_ids": sorted(compound_ids),
                    "sort_key": f"{method}:{-len(compound_ids):05d}:{-heavy_atoms:03d}:{fragment}",
                }
            )
        method_items = sorted(method_items, key=lambda item: item["sort_key"])[:max_per_method]
        pending.extend(
            {
                "group_label": f"{method.upper()}_{stable_hash(item['fragment_smiles'], 8)}",
                **item,
            }
            for item in method_items
        )

    registry: list[dict[str, Any]] = []
    membership: list[dict[str, Any]] = []
    assigned = assign_group_ids(pending, "FRAG")
    for item in assigned:
        group_id = item["group_id"]
        method = str(item["method"])
        fragment = str(item["fragment_smiles"])
        group_type = "brics_fragment" if method == "brics" else "recap_fragment"
        registry.append(
            registry_entry(
                group_id=group_id,
                label=item["group_label"],
                group_type=group_type,
                source="brics_recap_fragment_builder",
                source_column=None,
                definition={
                    "method": method,
                    "fragment_smiles": fragment,
                    "fragment_heavy_atoms": int(item["fragment_heavy_atoms"]),
                    "min_fragment_compound_count": min_compounds,
                    "min_fragment_heavy_atoms": min_heavy_atoms,
                },
                compounds=compounds,
                compound_ids=item["compound_ids"],
            )
        )
        for compound_id in item["compound_ids"]:
            membership.append(
                {
                    "group_id": group_id,
                    "compound_id": compound_id,
                    "membership_source": f"fragment:{method}",
                    "membership_reason": f"{method}_fragment={stable_hash(fragment, 12)}",
                }
            )

        total = next(row for row in registry if row["group_id"] == group_id)
        summary_rows.append(
            {
                "method": method,
                "fragment_smiles": fragment,
                "fragment_heavy_atoms": int(item["fragment_heavy_atoms"]),
                "compound_count": total["compound_count"],
                "wet_count": total["wet_count"],
                "virtual_count": total["virtual_count"],
                "group_id": group_id,
            }
        )

    if outdir is not None and bool(cfg.get("write_fragment_diagnostics", True)):
        write_csv(Path(outdir) / "fragment_group_summary.csv", summary_rows, FRAGMENT_SUMMARY_COLUMNS)

    if not registry:
        warnings.append("No BRICS/RECAP fragment groups passed configured filters.")
    return registry, membership, warnings

