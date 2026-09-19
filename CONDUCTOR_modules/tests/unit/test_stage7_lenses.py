from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from conductor_fragment_engine import FragmentationConfig, fragment_compound
from conductor_lens_l1b import local_flatness, run_l1b
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
from rdkit import Chem


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


def test_l1b_family_is_split_by_space(tmp_path) -> None:
    identifiers = [f"C{index:02d}" for index in range(12)]
    positions = np.arange(12, dtype=float)
    distance_path = tmp_path / "distance.npy"
    metadata_path = tmp_path / "distance.json"
    np.save(distance_path, np.abs(positions[:, None] - positions[None, :]).astype(np.float32))
    metadata_path.write_text(json.dumps({"compound_ids": identifiers}), encoding="utf-8")
    result = run_l1b(
        pd.DataFrame({"compound_id": identifiers, "canonical_smiles": ["CC"] * 12}),
        pd.DataFrame({"compound_id": identifiers, "endpoint_id": ["EP"] * 12, "oriented_value": positions}),
        pd.DataFrame([{"context_id": "CTX", "is_representative": True, "eligible": True, "translation_status": "native"}]),
        pd.DataFrame([{"context_id": "CTX", "compound_id": value} for value in identifiers]),
        [
            {"space_id": "D001", "tier": 1, "distance_path": str(distance_path), "distance_metadata_path": str(metadata_path)},
            {"space_id": "D002", "tier": 1, "distance_path": str(distance_path), "distance_metadata_path": str(metadata_path)},
        ],
        "EP",
        run_seed=3,
        neighbor_k=2,
        screen_permutations=1,
        final_permutations=1,
        screen_p_max=1.0,
        report_q_max=0.05,
        calibration_permutations=1,
    )
    assert set(result.tests["family_key"]) == {
        "L1b|D001|conditional_flatness",
        "L1b|D002|conditional_flatness",
    }


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
    assert len(result.findings) == 2
    assert set(result.evidence["context_b"]) == {"complement"}
    assert set(result.tests["family_key"]) == {"L5|AX|correlation_sign_conflict"}
    assert result.evidence.loc[result.evidence["context_a"].eq("A"), "r_a"].iloc[0] > 0.99
    assert result.evidence.loc[result.evidence["context_a"].eq("A"), "r_b"].iloc[0] < -0.99


def test_l5_complement_is_axis_local_and_skips_an_insufficient_axis(tmp_path) -> None:
    group_size = 6
    identifiers = [f"C{index:02d}" for index in range(group_size * 4)]
    feature = np.tile(np.arange(group_size, dtype=float), 4)
    endpoint = np.concatenate(
        (
            np.arange(group_size, dtype=float),
            np.arange(group_size - 1, -1, -1, dtype=float),
            np.arange(group_size - 1, -1, -1, dtype=float),
            np.arange(group_size, dtype=float),
        )
    )
    feature_path = tmp_path / "features.csv"
    pd.DataFrame({"compound_id": identifiers, "feature": feature}).to_csv(
        feature_path, index=False
    )
    contexts = pd.DataFrame(
        [
            {
                "context_id": context_id,
                "axis_id": axis_id,
                "is_representative": True,
                "eligible": True,
                "translation_status": "native",
            }
            for context_id, axis_id in (("A", "AX"), ("B", "AX"), ("C", "AX"), ("D", "OTHER"))
        ]
    )
    membership = pd.DataFrame(
        [
            {"context_id": "ABCD"[index // group_size], "compound_id": compound_id}
            for index, compound_id in enumerate(identifiers)
        ]
    )
    result = run_l5(
        pd.DataFrame(
            {"compound_id": identifiers, "canonical_smiles": ["CCc1ccccc1"] * len(identifiers)}
        ),
        pd.DataFrame(
            {
                "compound_id": identifiers,
                "endpoint_id": ["EP"] * len(identifiers),
                "oriented_value": endpoint,
            }
        ),
        contexts,
        membership,
        [{"space_id": "D001", "tier": 1, "path": str(feature_path)}],
        "EP",
        run_seed=7,
        min_endpoint_n=group_size,
        min_abs_r=0.0,
        screen_permutations=1,
        final_permutations=1,
        screen_p_max=1.0,
        report_q_max=1.0,
        calibration_permutations=1,
    )
    assert result.metrics["comparison_count"] == 3
    focal = result.evidence.loc[result.evidence["context_a"].eq("A")].iloc[0]
    assert focal["n_a"] == group_size
    assert focal["n_b"] == group_size * 2
    assert focal["shared_n"] == 0
    assert not set(result.score_observations["compound_id"]).intersection(
        identifiers[group_size * 3 :]
    )


def test_l5_support_uses_feature_finite_observations_with_overlapping_contexts(
    tmp_path,
) -> None:
    identifiers = [f"C{index:02d}" for index in range(30)]
    feature = np.full(30, np.nan)
    endpoint = np.zeros(30, dtype=float)

    # The contexts share 20 raw members, but the feature is finite for only four
    # of them.  The retired pairwise formula produced 9 + 9 - 20 = -2 even
    # though the actual unique finite support was 14.
    feature[:4] = [25.0, 30.0, 30.0, 35.0]
    endpoint[:4] = 30.0
    feature[20:25] = [10.0, 20.0, 30.0, 40.0, 50.0]
    endpoint[20:25] = [10.0, 20.0, 30.0, 40.0, 50.0]
    feature[25:30] = [10.0, 20.0, 30.0, 40.0, 50.0]
    endpoint[25:30] = [50.0, 40.0, 30.0, 20.0, 10.0]
    feature_path = tmp_path / "features_with_missing_values.csv"
    pd.DataFrame({"compound_id": identifiers, "feature": feature}).to_csv(
        feature_path, index=False
    )

    contexts = pd.DataFrame(
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
    )
    membership = pd.DataFrame(
        [
            {"context_id": context_id, "compound_id": identifiers[index]}
            for context_id, indices in (
                ("A", range(25)),
                ("B", (*range(20), *range(25, 30))),
            )
            for index in indices
        ]
    )

    result = run_l5(
        pd.DataFrame(
            {"compound_id": identifiers, "canonical_smiles": ["CCc1ccccc1"] * 30}
        ),
        pd.DataFrame(
            {
                "compound_id": identifiers,
                "endpoint_id": ["EP"] * 30,
                "oriented_value": endpoint,
            }
        ),
        contexts,
        membership,
        [{"space_id": "D015", "tier": 1, "path": str(feature_path)}],
        "EP",
        run_seed=23,
        min_endpoint_n=5,
        min_abs_r=0.30,
        screen_permutations=1,
        final_permutations=1,
        screen_p_max=1.0,
        report_q_max=1.0,
        calibration_permutations=1,
    )

    assert 9 + 9 - 20 == -2
    assert len(result.findings) == 2
    assert set(result.evidence["n_a"]) == {9}
    assert set(result.evidence["n_b"]) == {5}
    assert set(result.evidence["shared_n"]) == {0}
    assert set(result.evidence["support_n"]) == {14}
    assert {finding["claim"]["support_n"] for finding in result.findings} == {14}
    assert set(
        result.score_observations.groupby("finding_key")["compound_id"].nunique()
    ) == {14}


def test_l5_bh_family_is_independent_between_axes(tmp_path) -> None:
    group_size = 6
    identifiers = [f"C{index:02d}" for index in range(group_size * 4)]
    feature_path = tmp_path / "features.csv"
    pd.DataFrame(
        {
            "compound_id": identifiers,
            "feature": np.tile(np.arange(group_size, dtype=float), 4),
        }
    ).to_csv(feature_path, index=False)
    endpoint = np.concatenate(
        tuple(
            np.arange(group_size, dtype=float)
            if group_index % 2 == 0
            else np.arange(group_size - 1, -1, -1, dtype=float)
            for group_index in range(4)
        )
    )
    all_contexts = pd.DataFrame(
        [
            {
                "context_id": context_id,
                "axis_id": axis_id,
                "is_representative": True,
                "eligible": True,
                "translation_status": "native",
            }
            for context_id, axis_id in (("A", "AX"), ("B", "AX"), ("C", "AY"), ("D", "AY"))
        ]
    )
    membership = pd.DataFrame(
        [
            {"context_id": "ABCD"[index // group_size], "compound_id": compound_id}
            for index, compound_id in enumerate(identifiers)
        ]
    )
    common = (
        pd.DataFrame(
            {"compound_id": identifiers, "canonical_smiles": ["CCc1ccccc1"] * len(identifiers)}
        ),
        pd.DataFrame(
            {
                "compound_id": identifiers,
                "endpoint_id": ["EP"] * len(identifiers),
                "oriented_value": endpoint,
            }
        ),
    )

    def execute(contexts: pd.DataFrame):
        return run_l5(
            *common,
            contexts,
            membership,
            [{"space_id": "D001", "tier": 1, "path": str(feature_path)}],
            "EP",
            run_seed=17,
            min_endpoint_n=group_size,
            min_abs_r=0.0,
            screen_permutations=9,
            final_permutations=19,
            screen_p_max=1.0,
            report_q_max=1.0,
            calibration_permutations=1,
        )

    baseline = execute(all_contexts.loc[all_contexts["axis_id"].eq("AX")])
    combined = execute(all_contexts)
    baseline_ax = baseline.tests.loc[
        baseline.tests["family_key"].eq("L5|AX|correlation_sign_conflict")
    ].sort_values("candidate_key")
    combined_ax = combined.tests.loc[
        combined.tests["family_key"].eq("L5|AX|correlation_sign_conflict")
    ].sort_values("candidate_key")
    assert set(combined.tests["family_key"]) == {
        "L5|AX|correlation_sign_conflict",
        "L5|AY|correlation_sign_conflict",
    }
    assert baseline_ax["candidate_key"].tolist() == combined_ax["candidate_key"].tolist()
    assert baseline_ax["q_value"].tolist() == combined_ax["q_value"].tolist()


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
    assert set(result.tests["family_key"]) == {
        "L2a|terminal_substitution|TR|same|mean_shift",
        "L2a|terminal_substitution|TR|same|variance_reduction",
    }


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
