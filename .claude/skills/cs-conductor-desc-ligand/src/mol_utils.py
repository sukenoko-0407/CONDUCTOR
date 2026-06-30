from __future__ import annotations

from typing import Any

import pandas as pd

try:
    from rdkit import Chem, rdBase
except ImportError:  # pragma: no cover
    Chem = None
    rdBase = None


def require_rdkit() -> None:
    if Chem is None:
        raise RuntimeError("RDKit is required for descriptor generation but is not installed in this Python environment.")


def smiles_to_mol(smiles: str):
    """Return (mol, error_message) for an input SMILES string."""
    require_rdkit()
    if pd.isna(smiles) or str(smiles).strip() == "":
        return None, "empty_smiles"
    try:
        with rdBase.BlockLogs():
            mol = Chem.MolFromSmiles(str(smiles).strip(), sanitize=True)
    except Exception as exc:
        return None, str(exc)
    if mol is None:
        return None, "Chem.MolFromSmiles returned None"
    return mol, ""


def canonicalize_smiles(mol) -> str:
    require_rdkit()
    if mol is None:
        return ""
    return Chem.MolToSmiles(mol, canonical=True)


def prepare_molecule_table(df: pd.DataFrame, id_col: str | None, smiles_col: str) -> pd.DataFrame:
    """Build the common molecule table used by every descriptor set."""
    require_rdkit()
    rows: list[dict[str, Any]] = []
    for idx, row in df.iterrows():
        compound_id = row[id_col] if id_col and id_col in df.columns else f"row_{idx + 1:06d}"
        input_smiles = row[smiles_col]
        mol, error = smiles_to_mol(input_smiles)
        rows.append(
            {
                "compound_id": str(compound_id),
                "input_smiles": "" if pd.isna(input_smiles) else str(input_smiles),
                "canonical_smiles": canonicalize_smiles(mol) if mol is not None else "",
                "mol_parse_ok": mol is not None,
                "mol": mol,
                "mol_error": error,
            }
        )
    return pd.DataFrame(rows)
