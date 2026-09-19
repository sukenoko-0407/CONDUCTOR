from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from lens_work_estimators import estimate_work


def _write_csv(path: Path, frame: pd.DataFrame) -> str:
    frame.to_csv(path, index=False)
    return str(path)


def test_l5_estimate_is_exact_for_units_and_feature_dependent_for_memory(
    tmp_path: Path,
) -> None:
    group_size = 6
    identifiers = [f"C{index:02d}" for index in range(group_size * 2)]
    feature = np.tile(np.arange(group_size, dtype=float), 2)
    compounds = _write_csv(
        tmp_path / "compounds.csv",
        pd.DataFrame(
            {
                "compound_id": identifiers,
                "canonical_smiles": ["CCc1ccccc1"] * len(identifiers),
            }
        ),
    )
    endpoints = _write_csv(
        tmp_path / "endpoints.csv",
        pd.DataFrame(
            {
                "compound_id": identifiers,
                "endpoint_id": ["EP"] * len(identifiers),
                "oriented_value": np.concatenate(
                    (
                        np.arange(group_size, dtype=float),
                        np.arange(group_size - 1, -1, -1, dtype=float),
                    )
                ),
            }
        ),
    )
    catalog = _write_csv(
        tmp_path / "contexts.csv",
        pd.DataFrame(
            [
                {
                    "context_id": context_id,
                    "axis_id": "AX",
                    "is_representative": True,
                    "eligible": True,
                    "translation_status": "native",
                }
                for context_id in ("A", "B")
            ]
        ),
    )
    membership = _write_csv(
        tmp_path / "membership.csv",
        pd.DataFrame(
            [
                {
                    "context_id": "A" if index < group_size else "B",
                    "compound_id": compound_id,
                }
                for index, compound_id in enumerate(identifiers)
            ]
        ),
    )
    one_feature = _write_csv(
        tmp_path / "one.csv",
        pd.DataFrame({"compound_id": identifiers, "f1": feature}),
    )
    two_features = _write_csv(
        tmp_path / "two.csv",
        pd.DataFrame({"compound_id": identifiers, "f1": feature, "f2": feature**2}),
    )

    def registry(path: Path, feature_path: str) -> str:
        path.write_text(
            json.dumps(
                {
                    "spaces": [
                        {"space_id": "D001", "tier": 1, "path": feature_path}
                    ]
                }
            ),
            encoding="utf-8",
        )
        return str(path)

    inputs = [
        {"role": "compounds", "path": compounds},
        {"role": "endpoint_table", "path": endpoints},
        {"role": "context_catalog", "path": catalog},
        {"role": "context_membership", "path": membership},
    ]
    request = {
        "endpoint_id": "EP",
        "random_seed": 7,
        "parameters": {"operation": "l5"},
        "inputs": inputs,
    }
    config = {
        "statistics": {"final_permutations": 1000},
        "contexts": {"min_endpoint_n": group_size},
        "lenses": {"l5": {"min_abs_r": 0.0}},
        "runtime": {"units_per_second": {"l5": 3_650_000}},
    }
    estimate_one = estimate_work(
        {
            **request,
            "inputs": inputs
            + [
                {
                    "role": "feature_spaces",
                    "path": registry(tmp_path / "one.json", one_feature),
                }
            ],
        },
        config,
        workers=1,
    )
    estimate_two = estimate_work(
        {
            **request,
            "inputs": inputs
            + [
                {
                    "role": "feature_spaces",
                    "path": registry(tmp_path / "two.json", two_features),
                }
            ],
        },
        config,
        workers=1,
    )

    assert estimate_one.unit_count == 1001 * 2
    assert estimate_two.unit_count == estimate_one.unit_count * 2
    assert estimate_two.peak_memory_bytes > estimate_one.peak_memory_bytes
    assert estimate_one.detail["comparison_count"] == 2
    assert estimate_one.detail["feature_count"] == 1

