from __future__ import annotations

import hashlib
import math
import traceback as tb
from typing import Any

import pandas as pd
from rdkit.Chem.Pharm2D import Generate, Gobbi_Pharm2D

from .run_support import base_record


def _fold_index(raw_idx: int, n_bits: int) -> int:
    digest = hashlib.blake2b(str(int(raw_idx)).encode("ascii"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % int(n_bits)


def calc_gobbi_pharm2d_folded_bit(mol, n_bits: int = 2048) -> dict:
    fp = Generate.Gen2DFingerprint(mol, Gobbi_Pharm2D.factory)
    on_bits = {_fold_index(bit, n_bits) for bit in fp.GetOnBits()}
    return {f"pharm2d_folded__bit_{i:04d}": int(i in on_bits) for i in range(n_bits)}


def compute_gobbi_pharm2d_svd_set(mol_table: pd.DataFrame, set_id: str, spec: dict[str, Any]) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    try:
        import numpy as np
        from scipy import sparse
        from sklearn.decomposition import TruncatedSVD
    except ImportError as exc:
        raise RuntimeError("scipy and scikit-learn are required for L25 gobbi_pharm2d_svd.") from exc

    params = dict(spec.get("params") or {})
    target_dim = int(params.get("target_dim", 1024))
    min_dim = int(params.get("min_dim", 32))
    max_dim = int(params.get("max_dim", 1024))
    random_seed = int(params.get("random_seed", 61453))

    valid_indices = [idx for idx, row in mol_table.iterrows() if bool(row["mol_parse_ok"])]
    n_valid = len(valid_indices)
    if n_valid < 2:
        raise ValueError("L25 gobbi_pharm2d_svd requires at least two valid molecules.")

    raw_dim = int(Gobbi_Pharm2D.factory.GetSigSize())
    actual_dim = min(target_dim, max_dim, max(1, math.floor(n_valid / 2)), n_valid - 1, raw_dim)
    if actual_dim < min_dim and n_valid - 1 >= min_dim:
        actual_dim = min_dim

    row_ids: list[int] = []
    col_ids: list[int] = []
    data: list[int] = []
    errors: list[dict[str, Any]] = []
    valid_position_by_index: dict[int, int] = {}

    for pos, idx in enumerate(valid_indices):
        mol_row = mol_table.loc[idx]
        valid_position_by_index[idx] = pos
        try:
            fp = Generate.Gen2DFingerprint(mol_row["mol"], Gobbi_Pharm2D.factory)
            for bit in fp.GetOnBits():
                row_ids.append(pos)
                col_ids.append(int(bit))
                data.append(1)
        except Exception as exc:
            errors.append(
                {
                    "compound_id": mol_row["compound_id"],
                    "input_smiles": mol_row["input_smiles"],
                    "canonical_smiles": mol_row["canonical_smiles"],
                    "descriptor_set": set_id,
                    "error_type": "descriptor_error",
                    "error_message": str(exc),
                    "traceback": tb.format_exc(),
                }
            )

    matrix = sparse.csr_matrix((data, (row_ids, col_ids)), shape=(n_valid, raw_dim), dtype=float)
    reducer = TruncatedSVD(n_components=actual_dim, random_state=random_seed)
    transformed = reducer.fit_transform(matrix)
    feature_cols = [f"pharm2d_svd__dim_{i:04d}" for i in range(actual_dim)]

    rows: list[dict[str, Any]] = []
    for idx, mol_row in mol_table.iterrows():
        if not bool(mol_row["mol_parse_ok"]):
            message = str(mol_row["mol_error"])
            rows.append(base_record(mol_row, message))
            errors.append(
                {
                    "compound_id": mol_row["compound_id"],
                    "input_smiles": mol_row["input_smiles"],
                    "canonical_smiles": mol_row["canonical_smiles"],
                    "descriptor_set": set_id,
                    "error_type": "mol_parse_error",
                    "error_message": message,
                    "traceback": "",
                }
            )
            continue
        pos = valid_position_by_index[idx]
        values = {col: float(value) for col, value in zip(feature_cols, transformed[pos])}
        rows.append({**base_record(mol_row), **values})

    df = pd.DataFrame(rows)
    common = ["compound_id", "canonical_smiles", "mol_parse_ok", "descriptor_error"]
    df.attrs["descriptor_metadata"] = {
        "raw_dimension": raw_dim,
        "target_dimension": target_dim,
        "actual_dimension": actual_dim,
        "explained_variance_ratio_sum": float(np.sum(reducer.explained_variance_ratio_)),
        "reducer": "TruncatedSVD",
        "random_seed": random_seed,
    }
    return df[common + feature_cols], errors
