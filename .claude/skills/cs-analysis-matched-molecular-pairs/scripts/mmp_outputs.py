from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pandas as pd


def load_database(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Read the canonical one-cut Type-III SQLite index without mutating it."""
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        details = pd.read_sql_query(
            """
            SELECT p.mmp_id,
                   cf.compound_id AS compound_id_from,
                   ct.compound_id AS compound_id_to,
                   cf.smiles AS smiles_from,
                   ct.smiles AS smiles_to,
                   cf.endpoint AS endpoint_from,
                   ct.endpoint AS endpoint_to,
                   p.endpoint_delta,
                   p.favorable_delta,
                   t.transform_id,
                   t.variable_from,
                   t.variable_to,
                   t.transform_smirks,
                   t.cut_count,
                   c.core_id,
                   c.exact_core_smiles,
                   c.core_heavy_atoms,
                   c.core_molecular_weight,
                   p.core_fraction_from,
                   p.core_fraction_to,
                   p.native_rule_id,
                   p.endpoint_missing,
                   p.quality_flags
              FROM mmp_pairs p
              JOIN compounds cf ON cf.compound_key = p.compound_from_key
              JOIN compounds ct ON ct.compound_key = p.compound_to_key
              JOIN transforms t ON t.transform_key = p.transform_key
              JOIN cores c ON c.core_key = p.core_key
             ORDER BY p.pair_key
            """,
            connection,
        )
        rows = connection.execute("SELECT key, value_json FROM metadata").fetchall()
    return details, {key: json.loads(value) for key, value in rows}
