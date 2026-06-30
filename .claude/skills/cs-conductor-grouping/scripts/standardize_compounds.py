from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

try:
    from rdkit import Chem  # type: ignore
    from rdkit import RDLogger  # type: ignore

    RDLogger.DisableLog("rdApp.error")
    RDLogger.DisableLog("rdApp.warning")
    RDKIT_AVAILABLE = True
except Exception:
    Chem = None
    RDKIT_AVAILABLE = False


TRUE_VALUES = {"true", "1", "yes", "y", "virtual", "predicted", "in_silico", "insilico"}
FALSE_VALUES = {"false", "0", "no", "n", "wet", "measured", "experimental", "real"}


def fallback_smiles_like(value: str) -> bool:
    text = str(value).strip()
    if not text:
        return False
    allowed = set("0123456789@+-#%=()[]/\\.:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
    if any(char not in allowed for char in text):
        return False
    atom_tokens = ["Cl", "Br", "Si", "Se", "Na", "Li", "Mg", "Ca", "Al", "B", "C", "N", "O", "P", "S", "F", "I", "H", "K", "b", "c", "n", "o", "p", "s"]
    atom_count = 0
    i = 0
    while i < len(text):
        char = text[i]
        if char.isalpha():
            matched = next((token for token in atom_tokens if text.startswith(token, i)), None)
            if matched is None:
                return False
            atom_count += 1
            i += len(matched)
            continue
        i += 1
    return atom_count > 0


def normalize_virtual(value: Any) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    text = str(value).strip().lower()
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    return False


def canonicalize_smiles(smiles: Any) -> tuple[str | None, str | None]:
    text = "" if smiles is None or (isinstance(smiles, float) and pd.isna(smiles)) else str(smiles).strip()
    if not text:
        return None, "empty_smiles"
    if RDKIT_AVAILABLE:
        try:
            mol = Chem.MolFromSmiles(text)
            if mol is None:
                return None, "rdkit_parse_failed"
            canonical = Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)
            return canonical, None
        except Exception as exc:
            return None, f"rdkit_error:{exc}"
    if fallback_smiles_like(text):
        return text, None
    return None, "heuristic_smiles_parse_failed"


def standardize_compounds(
    df: pd.DataFrame,
    id_column: str,
    smiles_column: str,
    is_virtual_column: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    warnings: list[str] = []
    if not RDKIT_AVAILABLE:
        warnings.append("RDKit is not installed; canonical SMILES and structure QA used heuristic fallback.")

    rows: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for index, row in df.iterrows():
        compound_id = str(row.get(id_column, "")).strip()
        if not compound_id:
            raise ValueError(f"Missing molecule ID at row {index + 1}.")
        if compound_id in seen_ids:
            raise ValueError(f"Duplicate molecule ID '{compound_id}' at row {index + 1}.")
        seen_ids.add(compound_id)

        original_smiles = row.get(smiles_column, "")
        canonical, reason = canonicalize_smiles(original_smiles)
        if reason:
            excluded.append(
                {
                    "compound_id": compound_id,
                    "row_index": index,
                    "original_smiles": original_smiles,
                    "exclusion_reason": reason,
                }
            )
            continue

        out = {str(col): row.get(col) for col in df.columns}
        out.update(
            {
                "compound_id": compound_id,
                "original_smiles": str(original_smiles).strip(),
                "canonical_smiles": canonical,
                "is_virtual": normalize_virtual(row.get(is_virtual_column)) if is_virtual_column else False,
                "source_row_index": int(index),
            }
        )
        rows.append(out)

    compounds = pd.DataFrame(rows)
    excluded_df = pd.DataFrame(excluded, columns=["compound_id", "row_index", "original_smiles", "exclusion_reason"])
    return compounds, excluded_df, warnings
