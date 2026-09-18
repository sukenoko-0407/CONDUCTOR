from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from rdkit import Chem

from conductor_fragment_engine import FragmentationConfig, fragment_compound
from conductor_lens_l1b import local_flatness
from conductor_lens_l2 import run_l2a
from conductor_lens_l4 import (
    L4GenerationResult,
    L4ScaleGuardError,
    assemble_fragments,
    candidate_distance_matrix,
    generate_l4_candidates,
    select_l4_candidates,
)
from conductor_lens_l5 import run_l5
from conductor_lens_l7 import run_l7


def test_l1b_flatness_excludes_self_and_requires_full_neighbor_count() -> None:
    positions = np.arange(12, dtype=float)
    distance = np.abs(positions[:, None] - positions[None, :])
    endpoint = positions.copy()
    value, predictions, errors = local_flatness(
        distance, endpoint, np.arange(12), neighbor_k=2, global_variance=float(np.var(endpoint, ddof=1))
    )
    assert value > 0.9
    assert len(predictions) == 12
    assert predictions[0] == 1.5
    assert errors[0] == 2.25


def test_l5_detects_planted_same_axis_sign_reversal(tmp_path) -> None:
    identifiers = [f"C{index:02d}" for index in range(20)]
    local_x = np.tile(np.arange(10, dtype=float), 2)
    endpoint = np.r_[np.arange(10, dtype=float), np.arange(9, -1, -1, dtype=float)]
    feature_path = tmp_path / "features.csv"
    pd.DataFrame({"compound_id": identifiers, "feature": local_x}).to_csv(feature_path, index=False)
    contexts = pd.DataFrame([
        {"context_id": "A", "axis_id": "AX", "is_representative": True, "eligible": True, "translation_status": "native"},
        {"context_id": "B", "axis_id": "AX", "is_representative": True, "eligible": True, "translation_status": "native"},
    ])
    membership = pd.DataFrame(
        [{"context_id": "A" if index < 10 else "B", "compound_id": identifier} for index, identifier in enumerate(identifiers)]
    )
    result = run_l5(
        pd.DataFrame({"compound_id": identifiers, "canonical_smiles": ["CCc1ccccc1"] * 20}),
        pd.DataFrame({"compound_id": identifiers, "endpoint_id": ["EP"] * 20, "oriented_value": endpoint}),
        contexts,
        membership,
        [{"space_id": "D001", "tier": 1, "path": str(feature_path)}],
        "EP",
        run_seed=7,
        screen_permutations=99,
        final_permutations=199,
        screen_p_max=0.20,
        report_q_max=0.20,
        calibration_permutations=20,
    )
    assert len(result.findings) == 1
    assert result.evidence.iloc[0]["r_a"] > 0.99
    assert result.evidence.iloc[0]["r_b"] < -0.99


def test_l2a_excludes_crossing_pairs_and_keeps_shift_and_variance_questions() -> None:
    pair_rows = []
    endpoint_rows = []
    inside_ids: set[str] = set()
    for index in range(10):
        left, right = f"L{index}", f"R{index}"
        inside = index < 5
        if inside:
            inside_ids.update((left, right))
        left_value = float(index % 2)
        right_value = left_value + (2.0 if inside else -2.0)
        endpoint_rows.extend([{"compound_id": left, "endpoint_id": "EP", "oriented_value": left_value}, {"compound_id": right, "endpoint_id": "EP", "oriented_value": right_value}])
        pair_rows.append({"pair_id": f"P{index}", "class": "terminal_substitution", "compound_from": left, "compound_to": right, "constant_key": f"K{index}", "variable_from": "[*]C", "variable_to": "[*]N", "transformation_id": "TR|same"})
    pair_rows.append({"pair_id": "PX", "class": "terminal_substitution", "compound_from": "L0", "compound_to": "R9", "constant_key": "KX", "variable_from": "[*]C", "variable_to": "[*]N", "transformation_id": "TR|same"})
    result = run_l2a(
        pd.DataFrame(pair_rows), pd.DataFrame(endpoint_rows),
        pd.DataFrame([{"context_id": "CTX", "is_representative": True, "eligible": True, "translation_status": "native"}]),
        pd.DataFrame([{"context_id": "CTX", "compound_id": value} for value in sorted(inside_ids)]),
        "EP", run_seed=11, min_pairs_in=3, min_pairs_out=3,
        screen_permutations=99, final_permutations=199, screen_p_max=1.0, report_q_max=0.25,
    )
    evidence = result.evidence.iloc[0]
    assert evidence["n_in"] == 5
    assert evidence["n_out"] == 5
    assert set(result.tests["question"]) == {"mean_shift", "variance_reduction"}


def test_l7_detects_reversed_common_r_group_ranking() -> None:
    endpoint_rows = []
    observation_rows = []
    for series_index, values in enumerate((range(6), range(5, -1, -1))):
        for fragment_index, value in enumerate(values):
            compound_id = f"S{series_index}C{fragment_index}"
            endpoint_rows.append({"compound_id": compound_id, "endpoint_id": "EP", "oriented_value": float(value)})
            observation_rows.append({"series_key": f"S{series_index}", "transform_class": "terminal_substitution", "constant_key": f"K{series_index}", "fragment_id": f"F{fragment_index}", "compound_ids_json": json.dumps([compound_id])})
    result = run_l7(pd.DataFrame(observation_rows), pd.DataFrame(endpoint_rows), "EP", run_seed=5, screen_permutations=99, final_permutations=199, screen_p_max=0.20, report_q_max=0.20)
    assert len(result.findings) == 1
    assert result.findings[0]["labels"] == ["sar_ranking_reversal"]
    assert result.evidence.iloc[0]["spearman_rho"] == -1.0


def test_l4_fragment_reassembly_round_trips_an_accepted_cut() -> None:
    smiles = "CCOc1ccccc1"
    records = fragment_compound("C1", smiles, FragmentationConfig(min_constant_heavy_atoms=2))
    record = next(item for item in records if item.status == "accepted")
    assembled = assemble_fragments(record.constant_key, record.variable_smiles)
    assert assembled == Chem.MolToSmiles(Chem.MolFromSmiles(smiles), canonical=True, isomericSmiles=True)


def test_l4_candidate_generation_reads_reserved_class_column() -> None:
    source_smiles = "CCOc1ccccc1"
    record = next(
        item for item in fragment_compound("C1", source_smiles, FragmentationConfig(min_constant_heavy_atoms=2))
        if item.status == "accepted" and item.transform_class == "terminal_substitution"
    )
    fragmentations = pd.DataFrame([
        {
            "fragmentation_id": "FR1", "compound_id": "C1", "class": record.transform_class,
            "constant_key": record.constant_key, "variable_smiles": record.variable_smiles, "status": "accepted",
        }
    ])
    transformations = pd.DataFrame([
        {
            "transformation_id": "TR1", "class": record.transform_class,
            "variable_from": record.variable_smiles, "variable_to": "[1*]N", "pair_count": 1,
        }
    ])
    result = generate_l4_candidates(
        pd.DataFrame([{"compound_id": "C1", "canonical_smiles": source_smiles}]),
        fragmentations,
        transformations,
    )
    assert len(result.candidates) == 1
    assert result.audit["status"].eq("accepted").any()


def test_l4_uses_exact_candidate_description_with_observed_scaling(tmp_path) -> None:
    observed_path = tmp_path / "observed.csv"
    candidate_path = tmp_path / "candidate.csv"
    metadata_path = tmp_path / "D001.json"
    pd.DataFrame(
        [
            {"compound_id": "A", "x": 0.0, "constant": 7.0},
            {"compound_id": "B", "x": 2.0, "constant": 7.0},
        ]
    ).to_csv(observed_path, index=False)
    pd.DataFrame([{"compound_id": "X", "x": 1.0, "constant": 99.0}]).to_csv(candidate_path, index=False)
    metadata_path.write_text(
        json.dumps({"compound_ids": ["A", "B"], "feature_columns": ["x"]}),
        encoding="utf-8",
    )
    space = {
        "space_id": "D001",
        "metric": "euclidean",
        "path": str(observed_path),
        "candidate_path": str(candidate_path),
        "distance_metadata_path": str(metadata_path),
    }
    observed_ids, distance = candidate_distance_matrix(space, ["X"])
    assert observed_ids == ["A", "B"]
    assert np.allclose(distance, [[1.0, 1.0]])

    del space["candidate_path"]
    with pytest.raises(ValueError, match="candidate_path"):
        candidate_distance_matrix(space, ["X"])


def test_l4_scale_cap_is_support_ranked_and_deterministic() -> None:
    candidates = pd.DataFrame([
        {"compound_id": "C", "canonical_smiles": "CC", "reachability_path_count": 1, "transformation_pair_support": 3, "source_compound_count": 1},
        {"compound_id": "A", "canonical_smiles": "CN", "reachability_path_count": 2, "transformation_pair_support": 1, "source_compound_count": 1},
        {"compound_id": "B", "canonical_smiles": "CO", "reachability_path_count": 2, "transformation_pair_support": 5, "source_compound_count": 1},
    ])
    generation = L4GenerationResult(candidates, pd.DataFrame(columns=["row_id", "status", "reason"]))
    selected, plan = select_l4_candidates(
        generation, candidate_cap=2, description_space_count=9,
        max_candidate_description_rows=18,
    )
    assert selected.candidates["compound_id"].tolist() == ["B", "A"]
    assert plan.generated_candidate_count == 3
    assert plan.selected_candidate_count == 2
    assert plan.excluded_by_cap_count == 1
    assert plan.planned_description_cost_units == 18
    assert selected.audit.iloc[-1]["reason"] == "scale_cap"


def test_l4_scale_guard_stops_before_description_work() -> None:
    candidates = pd.DataFrame([
        {"compound_id": f"C{i}", "canonical_smiles": "CC", "reachability_path_count": 1, "transformation_pair_support": 1, "source_compound_count": 1}
        for i in range(3)
    ])
    generation = L4GenerationResult(candidates, pd.DataFrame())
    with pytest.raises(L4ScaleGuardError) as caught:
        select_l4_candidates(
            generation, candidate_cap=3, description_space_count=9,
            max_candidate_description_rows=20,
        )
    assert caught.value.plan.planned_description_rows == 27


def test_l4_cost_guard_distinguishes_very_high_cost_descriptions() -> None:
    candidates = pd.DataFrame([
        {"compound_id": "C0", "canonical_smiles": "CC", "reachability_path_count": 1, "transformation_pair_support": 1, "source_compound_count": 1}
    ])
    generation = L4GenerationResult(candidates, pd.DataFrame())
    with pytest.raises(L4ScaleGuardError) as caught:
        select_l4_candidates(
            generation,
            candidate_cap=1,
            description_space_count=2,
            max_candidate_description_rows=2,
            description_cost_classes=["low", "very_high"],
            max_candidate_description_cost_units=64,
        )
    assert caught.value.plan.planned_description_rows == 2
    assert caught.value.plan.planned_description_cost_units == 65
    assert caught.value.plan.description_cost_class_rows == {
        "low": 1,
        "very_high": 1,
    }
