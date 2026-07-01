from __future__ import annotations


def base_record(row, descriptor_error: str = "") -> dict:
    return {
        "compound_id": row["compound_id"],
        "canonical_smiles": row["canonical_smiles"],
        "mol_parse_ok": bool(row["mol_parse_ok"]),
        "descriptor_error": descriptor_error,
    }
