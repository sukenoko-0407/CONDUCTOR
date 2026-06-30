from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


def read_input_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path)


def ensure_output_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def write_descriptor_csv(df: pd.DataFrame, output_path: str) -> None:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)


def write_run_metadata(metadata: dict[str, Any], output_dir: str) -> None:
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    metadata = dict(metadata)
    metadata.setdefault("datetime", datetime.now().isoformat(timespec="seconds"))
    with Path(output_dir, "run_metadata.json").open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, ensure_ascii=False, default=str)


def write_error_report(errors: list[dict[str, Any]], output_dir: str) -> None:
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    columns = [
        "compound_id",
        "input_smiles",
        "canonical_smiles",
        "descriptor_set",
        "error_type",
        "error_message",
        "traceback",
    ]
    with Path(output_dir, "errors.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in errors:
            writer.writerow({col: row.get(col, "") for col in columns})
