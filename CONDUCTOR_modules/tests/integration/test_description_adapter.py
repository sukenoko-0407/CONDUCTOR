from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from description_adapter import (
    DESCRIPTION_IDS,
    compute_distance_matrix,
    discover_description_capabilities,
    feature_space_metadata,
)
from description_database import finalize_cached_output, prepare_cache_plan, register_misses


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_all_18_description_capabilities_support_cold_and_warm_cache(tmp_path) -> None:
    capabilities = discover_description_capabilities(PROJECT_ROOT / ".claude" / "skills")
    assert tuple(item["capability_id"] for item in capabilities) == DESCRIPTION_IDS
    dataset = tmp_path / "compounds.csv"
    pd.DataFrame(
        [
            {"compound_id": "A", "smiles": "CCO"},
            {"compound_id": "B", "smiles": "CCN"},
        ]
    ).to_csv(dataset, index=False)

    for capability in capabilities:
        identifier = capability["capability_id"]
        cold = tmp_path / "cold" / identifier
        cold.mkdir(parents=True)
        plan = prepare_cache_plan(
            project_root=tmp_path,
            program_name="adapter-test",
            dataset_path=dataset,
            id_column="compound_id",
            smiles_column="smiles",
            capability=capability,
            parameters={},
            scratch=cold / "scratch",
            source_run_id="RUN-1",
        )
        assert plan["hit_count"] == 0 and plan["miss_count"] == 2
        payload = cold / f"{capability['output']['basename']}.csv"
        pd.DataFrame(
            [
                {"compound_id": "A", "input_smiles": "CCO", "mol_parse_ok": True, "description_error": "", f"{identifier}_0": 1.0},
                {"compound_id": "B", "input_smiles": "CCN", "mol_parse_ok": True, "description_error": "", f"{identifier}_0": 2.0},
            ]
        ).to_csv(payload, index=False)
        manifest = {
            "feature_columns": [f"{identifier}_0"],
            "value_semantics": capability["value_semantics"],
            "natural_metric": capability["natural_metric"],
        }
        identity = {
            "project": "test",
            "run_id": "RUN-1",
            "round_id": "P01",
            "node_id": f"NODE-{identifier}",
            "attempt_id": "ATT-1",
            "capability_id": identifier,
            "skill_name": capability["skill_name"],
        }
        assert register_misses(plan=plan, payload_path=payload, manifest=manifest, identity=identity) == 2
        finalize_cached_output(
            plan=plan,
            output=cold,
            request={"identity": identity, "conductor_version": "0.2.1"},
            capability=capability,
        )

        warm = tmp_path / "warm" / identifier
        warm.mkdir(parents=True)
        warm_plan = prepare_cache_plan(
            project_root=tmp_path,
            program_name="adapter-test",
            dataset_path=dataset,
            id_column="compound_id",
            smiles_column="smiles",
            capability=capability,
            parameters={},
            scratch=warm / "scratch",
            source_run_id="RUN-2",
        )
        assert warm_plan["hit_count"] == 2 and warm_plan["miss_count"] == 0
        merged = finalize_cached_output(
            plan=warm_plan,
            output=warm,
            request={"identity": {**identity, "run_id": "RUN-2", "attempt_id": "ATT-2"}, "conductor_version": "0.2.1"},
            capability=capability,
        )
        assert pd.read_csv(merged)["compound_id"].tolist() == ["A", "B"]


def test_distance_contract_for_structural_and_descriptor_spaces(tmp_path) -> None:
    structural_path = tmp_path / "structural.csv"
    pd.DataFrame(
        [
            {"compound_id": "A", "input_smiles": "CC", "mol_parse_ok": True, "description_error": "", "b0": 1, "b1": 0},
            {"compound_id": "B", "input_smiles": "CN", "mol_parse_ok": True, "description_error": "", "b0": 1, "b1": 1},
        ]
    ).to_csv(structural_path, index=False)
    structural = {"space_id": "D002", "metric": "tanimoto"}
    distance, metadata = compute_distance_matrix(structural_path, structural)
    assert distance.dtype == np.float32
    assert distance[0, 1] == 0.5
    assert np.array_equal(np.diag(distance), np.zeros(2, dtype=np.float32))
    assert metadata["compound_ids"] == ["A", "B"]

    descriptor_path = tmp_path / "descriptor.csv"
    pd.DataFrame(
        [
            {"compound_id": "A", "input_smiles": "CC", "mol_parse_ok": True, "description_error": "", "x": 1.0, "constant": 2.0},
            {"compound_id": "B", "input_smiles": "CN", "mol_parse_ok": True, "description_error": "", "x": None, "constant": 2.0},
            {"compound_id": "C", "input_smiles": "CO", "mol_parse_ok": True, "description_error": "", "x": 3.0, "constant": 2.0},
        ]
    ).to_csv(descriptor_path, index=False)
    distance, metadata = compute_distance_matrix(descriptor_path, {"space_id": "D001", "metric": "euclidean"})
    assert distance.shape == (3, 3)
    assert metadata["feature_columns"] == ["x"]
    assert np.isfinite(distance).all()


def test_tier_and_structurality_mapping_is_data_driven() -> None:
    capabilities = discover_description_capabilities(PROJECT_ROOT / ".claude" / "skills")
    spaces = {item["capability_id"]: feature_space_metadata(item, Path("x.csv")) for item in capabilities}
    assert spaces["D001"]["tier"] == 1 and spaces["D001"]["structurality"] == "non_structural"
    assert spaces["D003"]["tier"] == 2 and spaces["D003"]["structurality"] == "structural"
    assert spaces["D020"]["tier"] == 3 and spaces["D020"]["structurality"] == "non_structural"
    assert spaces["D002"]["parameters"]["radius"] == 2
