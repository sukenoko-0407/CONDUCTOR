from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from conductor_runtime.phase1 import prepare_phase1


MODULE_ROOT = Path(__file__).resolve().parents[2]


def _registry(path: Path, *, lower_is_better: bool = False) -> Path:
    value = {
        "schema_version": "0.2.1",
        "selected_endpoint_id": "EP_A",
        "endpoints": [
            {
                "endpoint_id": "EP_A",
                "role": "primary",
                "kind": "measured",
                "source_column": "a",
                "transform": "none",
                "higher_is_better": not lower_is_better,
                "unit": "log_molar",
                "dependencies": [],
            },
            {
                "endpoint_id": "EP_B",
                "role": "secondary",
                "kind": "measured",
                "source_column": "b",
                "transform": "none",
                "higher_is_better": True,
                "unit": "score",
                "dependencies": [],
            },
        ],
    }
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_phase1_orients_values_and_detects_missingness(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.csv"
    pd.DataFrame(
        {
            "compound_id": [f"C{i:02d}" for i in range(12)],
            "smiles": ["CC" + "C" * (i % 3) for i in range(12)],
            "a": list(range(1, 7)) + [np.nan] * 6,
            "b": list(range(1, 7)) + list(range(20, 26)),
        }
    ).to_csv(dataset, index=False)
    result = prepare_phase1(
        dataset_path=dataset,
        registry_path=_registry(tmp_path / "registry.json", lower_is_better=True),
        selected_endpoint_id="EP_A",
        output_directory=tmp_path / "out",
        schema_directory=MODULE_ROOT / "schemas",
    )

    endpoint_a = result.endpoints[result.endpoints["endpoint_id"] == "EP_A"]
    assert endpoint_a.iloc[0]["oriented_value"] == -1.0
    tested = result.missingness[result.missingness["status"] == "tested"]
    assert len(tested) == 1
    assert bool(tested.iloc[0]["selection_biased"])
    assert tested.iloc[0]["rank_biserial"] < 0
    assert list(result.compounds.columns)[0] == "row_id"
    assert (tmp_path / "out" / "endpoints.csv").is_file()


def test_phase1_rejects_same_id_with_different_structure(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.csv"
    pd.DataFrame(
        {
            "compound_id": ["C1", "C1"],
            "smiles": ["CC", "CCC"],
            "a": [1.0, 2.0],
            "b": [1.0, 2.0],
        }
    ).to_csv(dataset, index=False)
    with pytest.raises(ValueError, match="different structures"):
        prepare_phase1(
            dataset_path=dataset,
            registry_path=_registry(tmp_path / "registry.json"),
            selected_endpoint_id="EP_A",
            output_directory=tmp_path / "out",
            schema_directory=MODULE_ROOT / "schemas",
        )


def test_phase1_rejects_log_transform_domain_violation(tmp_path: Path) -> None:
    registry_path = _registry(tmp_path / "registry.json")
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["endpoints"][0]["transform"] = "log10"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    dataset = tmp_path / "dataset.csv"
    pd.DataFrame(
        {"compound_id": ["C1"], "smiles": ["CC"], "a": [0.0], "b": [1.0]}
    ).to_csv(dataset, index=False)
    with pytest.raises(ValueError, match="domain violation"):
        prepare_phase1(
            dataset_path=dataset,
            registry_path=registry_path,
            selected_endpoint_id="EP_A",
            output_directory=tmp_path / "out",
            schema_directory=MODULE_ROOT / "schemas",
        )
