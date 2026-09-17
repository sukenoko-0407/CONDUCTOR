from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from conductor_lens_l2 import run_l2b
from conductor_stat_core import validate_instance


SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"


def _planted_series(count: int = 12) -> tuple[pd.DataFrame, pd.DataFrame]:
    observations: list[dict] = []
    endpoints: list[dict] = []
    for index in range(count):
        series = f"S{index:02d}"
        target_compounds = [f"T{index:02d}a", f"T{index:02d}b"] if index == 0 else [f"T{index:02d}"]
        target_values = [2.0 + 0.05 * index + 0.02 * offset for offset in range(len(target_compounds))]
        other_compound = f"O{index:02d}"
        observations.extend(
            [
                {
                    "row_id": f"RT{index}",
                    "series_key": series,
                    "transform_class": "terminal_substitution",
                    "fragment_id": "FRAG|0000000000000001",
                    "fragment_smiles": "[1*]N",
                    "compound_ids_json": json.dumps(target_compounds),
                    "n_compounds": len(target_compounds),
                    "endpoint_mean": sum(target_values) / len(target_values),
                },
                {
                    "row_id": f"RO{index}",
                    "series_key": series,
                    "transform_class": "terminal_substitution",
                    "fragment_id": f"FRAG|{index + 100:016x}",
                    "fragment_smiles": f"[1*]C{index}",
                    "compound_ids_json": json.dumps([other_compound]),
                    "n_compounds": 1,
                    "endpoint_mean": 0.0,
                },
            ]
        )
        endpoints.extend(
            {"compound_id": identifier, "endpoint_id": "EP", "oriented_value": value}
            for identifier, value in zip(target_compounds, target_values, strict=True)
        )
        endpoints.append({"compound_id": other_compound, "endpoint_id": "EP", "oriented_value": 0.0})
    return pd.DataFrame(observations), pd.DataFrame(endpoints)


def test_l2b_detects_planted_series_effect_and_is_deterministic() -> None:
    observations, endpoints = _planted_series()
    result = run_l2b(
        observations,
        endpoints,
        "EP",
        run_seed=17,
        screen_permutations=100,
        final_permutations=300,
        calibration_permutations=20,
    )
    repeated = run_l2b(
        observations,
        endpoints,
        "EP",
        run_seed=17,
        screen_permutations=100,
        final_permutations=300,
        calibration_permutations=20,
    )
    assert result.tests.to_dict(orient="records") == repeated.tests.to_dict(orient="records")
    target = result.tests.loc[
        result.tests["fragment_id"].eq("FRAG|0000000000000001")
        & result.tests["question"].eq("consistent_effect")
    ].iloc[0]
    assert target["status"] == "final"
    assert target["q_value"] <= 0.05
    assert len(result.findings) == 1
    validate_instance(result.findings[0], SCHEMA_DIR / "finding.schema.json")
    evidence = result.evidence.loc[result.evidence["fragment_id"].eq("FRAG|0000000000000001")].iloc[0]
    assert evidence["series_count"] == 12
    assert json.loads(evidence["compound_ids_json"])[0] == "T00a"
    assert result.calibration["acceptance_gt_1_5"]


def test_zero_variance_consistent_effect_has_p_one() -> None:
    observations, endpoints = _planted_series(2)
    endpoints.loc[endpoints["compound_id"].str.startswith("T"), "oriented_value"] = 2.0
    result = run_l2b(
        observations,
        endpoints,
        "EP",
        run_seed=9,
        screen_permutations=20,
        final_permutations=20,
        calibration_permutations=5,
    )
    target = result.tests.loc[result.tests["fragment_id"].eq("FRAG|0000000000000001")].iloc[0]
    assert target["screen_p_value"] == 1.0
    assert target["p_value"] == 1.0
    assert target["status"] == "screened_out"
    assert not result.findings
