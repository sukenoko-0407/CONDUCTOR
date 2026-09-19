from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from description_adapter import (
    DESCRIPTION_IDS,
    build_feature_spaces,
    compute_distance_matrix,
    discover_description_capabilities,
    feature_space_metadata,
    run_description_capability,
)
from description_database import (
    finalize_cached_output,
    inspect_records,
    prepare_cache_plan,
    register_misses,
)


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


def test_conformer_failure_is_negative_cached_and_excluded_from_distance(
    tmp_path,
) -> None:
    capability = next(
        item
        for item in discover_description_capabilities(PROJECT_ROOT / ".claude" / "skills")
        if item["capability_id"] == "D012"
    )
    identity = {
        "project": "test",
        "run_id": "RUN-1",
        "round_id": "P01",
        "node_id": "NODE-D012",
        "attempt_id": "ATT-1",
        "capability_id": "D012",
        "skill_name": capability["skill_name"],
    }
    initial_dataset = tmp_path / "initial.csv"
    pd.DataFrame(
        [
            {"compound_id": "A", "smiles": "CCO"},
            {"compound_id": "C", "smiles": "CCN"},
        ]
    ).to_csv(initial_dataset, index=False)
    initial_output = tmp_path / "initial-output"
    initial_output.mkdir()
    initial_plan = prepare_cache_plan(
        project_root=tmp_path,
        program_name="negative-cache",
        dataset_path=initial_dataset,
        id_column="compound_id",
        smiles_column="smiles",
        capability=capability,
        parameters={},
        scratch=tmp_path / "initial-scratch",
        source_run_id="RUN-1",
    )
    initial_payload = initial_output / "D012_rdkit_3d.csv"
    pd.DataFrame(
        [
            {"compound_id": "A", "input_smiles": "CCO", "mol_parse_ok": True, "description_error": "", "rdkit3d__PMI1": 1.0},
            {"compound_id": "C", "input_smiles": "CCN", "mol_parse_ok": True, "description_error": "", "rdkit3d__PMI1": 3.0},
        ]
    ).to_csv(initial_payload, index=False)
    initial_manifest = {
        "feature_columns": ["rdkit3d__PMI1"],
        "value_semantics": capability["value_semantics"],
        "natural_metric": capability["natural_metric"],
        "errors": [],
    }
    assert register_misses(
        plan=initial_plan,
        payload_path=initial_payload,
        manifest=initial_manifest,
        identity=identity,
    ) == 2

    expanded_dataset = tmp_path / "expanded.csv"
    pd.DataFrame(
        [
            {"compound_id": "A", "smiles": "CCO"},
            {"compound_id": "C", "smiles": "CCN"},
            {"compound_id": "B", "smiles": "CCC"},
        ]
    ).to_csv(expanded_dataset, index=False)
    failure_output = tmp_path / "failure-output"
    failure_output.mkdir()
    failure_plan = prepare_cache_plan(
        project_root=tmp_path,
        program_name="negative-cache",
        dataset_path=expanded_dataset,
        id_column="compound_id",
        smiles_column="smiles",
        capability=capability,
        parameters={},
        scratch=tmp_path / "failure-scratch",
        source_run_id="RUN-2",
    )
    assert failure_plan["hit_count"] == 2
    assert failure_plan["miss_ids"] == ["B"]
    failure_payload = failure_output / "D012_rdkit_3d.csv"
    pd.DataFrame(
        [
            {
                "compound_id": "B",
                "input_smiles": "CCC",
                "mol_parse_ok": True,
                "description_error": "RDKit conformer generation failed",
            }
        ]
    ).to_csv(failure_payload, index=False)
    failure_manifest = {
        "feature_columns": [],
        "value_semantics": capability["value_semantics"],
        "natural_metric": capability["natural_metric"],
        "errors": [
            {
                "compound_id": "B",
                "error_type": "conformer_generation_failed",
                "message": "RDKit conformer generation failed",
            }
        ],
    }
    assert register_misses(
        plan=failure_plan,
        payload_path=failure_payload,
        manifest=failure_manifest,
        identity={**identity, "run_id": "RUN-2", "attempt_id": "ATT-2"},
    ) == 1
    assert failure_plan["registered_ok_count"] == 0
    assert failure_plan["registered_skip_count"] == 1
    merged = finalize_cached_output(
        plan=failure_plan,
        output=failure_output,
        request={
            "identity": {**identity, "run_id": "RUN-2", "attempt_id": "ATT-2"},
            "conductor_version": "0.2.1",
        },
        capability=capability,
    )
    merged_frame = pd.read_csv(merged)
    assert merged_frame["compound_id"].tolist() == ["A", "C", "B"]
    assert pd.isna(
        merged_frame.loc[
            merged_frame["compound_id"].eq("B"), "rdkit3d__PMI1"
        ].iloc[0]
    )

    records = inspect_records(Path(failure_plan["database_path"]), "B")
    assert len(records) == 1
    assert records[0]["outcome_status"] == "skipped"
    assert "conformer generation failed" in records[0]["row_json"]

    warm_plan = prepare_cache_plan(
        project_root=tmp_path,
        program_name="negative-cache",
        dataset_path=expanded_dataset,
        id_column="compound_id",
        smiles_column="smiles",
        capability=capability,
        parameters={},
        scratch=tmp_path / "warm-scratch",
        source_run_id="RUN-3",
    )
    assert warm_plan["hit_count"] == 3
    assert warm_plan["miss_count"] == 0
    assert warm_plan["cache_outcome_counts"] == {"ok": 2, "skipped": 1}

    distance, metadata = compute_distance_matrix(
        merged,
        {"space_id": "D012", "metric": "euclidean"},
    )
    assert distance.shape == (3, 3)
    assert metadata["eligible_compound_ids"] == ["A", "C"]
    assert metadata["ineligible_count"] == 1
    assert np.isnan(distance[2]).all()
    assert np.isnan(distance[:, 2]).all()

    transient_dataset = tmp_path / "transient.csv"
    pd.DataFrame(
        [
            {"compound_id": "A", "smiles": "CCO"},
            {"compound_id": "C", "smiles": "CCN"},
            {"compound_id": "B", "smiles": "CCC"},
            {"compound_id": "D", "smiles": "CCCl"},
        ]
    ).to_csv(transient_dataset, index=False)
    transient_plan = prepare_cache_plan(
        project_root=tmp_path,
        program_name="negative-cache",
        dataset_path=transient_dataset,
        id_column="compound_id",
        smiles_column="smiles",
        capability=capability,
        parameters={},
        scratch=tmp_path / "transient-scratch",
        source_run_id="RUN-4",
    )
    assert transient_plan["hit_count"] == 3
    assert transient_plan["miss_ids"] == ["D"]
    transient_payload = tmp_path / "transient-output.csv"
    pd.DataFrame(
        [
            {
                "compound_id": "D",
                "input_smiles": "CCCl",
                "mol_parse_ok": True,
                "description_error": "unexpected worker failure",
                "rdkit3d__PMI1": None,
            }
        ]
    ).to_csv(transient_payload, index=False)
    transient_manifest = {
        "feature_columns": ["rdkit3d__PMI1"],
        "value_semantics": capability["value_semantics"],
        "natural_metric": capability["natural_metric"],
        "errors": [
            {
                "compound_id": "D",
                "error_type": "description_error",
                "message": "unexpected worker failure",
            }
        ],
    }
    assert register_misses(
        plan=transient_plan,
        payload_path=transient_payload,
        manifest=transient_manifest,
        identity={**identity, "run_id": "RUN-4", "attempt_id": "ATT-4"},
    ) == 0
    assert transient_plan["registered_ok_count"] == 0
    assert transient_plan["registered_skip_count"] == 0
    assert transient_plan["registration_skipped_count"] == 1
    retry_plan = prepare_cache_plan(
        project_root=tmp_path,
        program_name="negative-cache",
        dataset_path=transient_dataset,
        id_column="compound_id",
        smiles_column="smiles",
        capability=capability,
        parameters={},
        scratch=tmp_path / "retry-scratch",
        source_run_id="RUN-5",
    )
    assert retry_plan["hit_count"] == 3
    assert retry_plan["miss_ids"] == ["D"]


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
    assert spaces["D019"]["cost_class"] == "very_high"


def test_mordred_partial_nonfinite_rows_register_but_all_nonfinite_do_not(tmp_path) -> None:
    capability = next(
        item
        for item in discover_description_capabilities(PROJECT_ROOT / ".claude" / "skills")
        if item["capability_id"] == "D015"
    )
    dataset = tmp_path / "compounds.csv"
    pd.DataFrame(
        [
            {"compound_id": "A", "smiles": "CCO"},
            {"compound_id": "B", "smiles": "CCN"},
        ]
    ).to_csv(dataset, index=False)
    plan = prepare_cache_plan(
        project_root=tmp_path,
        program_name="mordred-partial",
        dataset_path=dataset,
        id_column="compound_id",
        smiles_column="smiles",
        capability=capability,
        parameters={},
        scratch=tmp_path / "scratch",
        source_run_id="RUN",
    )
    payload = tmp_path / "mordred.csv"
    pd.DataFrame(
        [
            {"compound_id": "A", "input_smiles": "CCO", "mol_parse_ok": True, "description_error": "", "mordred__MW": 46.0, "mordred__nHeavyAtom": 3.0, "mordred__MINsSeH": None, "mordred__MAXssPbH2": None},
            {"compound_id": "B", "input_smiles": "CCN", "mol_parse_ok": True, "description_error": "", "mordred__MW": None, "mordred__nHeavyAtom": None, "mordred__MINsSeH": None, "mordred__MAXssPbH2": None},
        ]
    ).to_csv(payload, index=False)
    manifest = {
        "feature_columns": [
            "mordred__MW",
            "mordred__nHeavyAtom",
            "mordred__MINsSeH",
            "mordred__MAXssPbH2",
        ],
        "value_semantics": "dense_continuous",
        "natural_metric": "euclidean",
    }
    identity = {
        "run_id": "RUN", "round_id": "RND0001", "node_id": "N000001"
    }
    assert register_misses(
        plan=plan, payload_path=payload, manifest=manifest, identity=identity
    ) == 1
    assert plan["registration_skipped_count"] == 1


def test_strict_description_still_rejects_one_nonfinite_feature(tmp_path) -> None:
    capability = next(
        item
        for item in discover_description_capabilities(PROJECT_ROOT / ".claude" / "skills")
        if item["capability_id"] == "D001"
    )
    dataset = tmp_path / "compounds.csv"
    pd.DataFrame([{"compound_id": "A", "smiles": "CCO"}]).to_csv(dataset, index=False)
    plan = prepare_cache_plan(
        project_root=tmp_path, program_name="strict", dataset_path=dataset,
        id_column="compound_id", smiles_column="smiles", capability=capability,
        parameters={}, scratch=tmp_path / "scratch", source_run_id="RUN",
    )
    payload = tmp_path / "strict.csv"
    pd.DataFrame([{"compound_id": "A", "input_smiles": "CCO", "mol_parse_ok": True, "description_error": "", "f1": 1.0, "f2": None}]).to_csv(payload, index=False)
    manifest = {"feature_columns": ["f1", "f2"], "value_semantics": "dense_continuous", "natural_metric": "euclidean"}
    identity = {"run_id": "RUN", "round_id": "RND0001", "node_id": "N000001"}
    assert register_misses(plan=plan, payload_path=payload, manifest=manifest, identity=identity) == 0


def test_feature_space_distances_are_always_below_distance_directory(tmp_path) -> None:
    capability = next(
        item
        for item in discover_description_capabilities(PROJECT_ROOT / ".claude" / "skills")
        if item["capability_id"] == "D001"
    )
    payload = tmp_path / "D001.csv"
    pd.DataFrame([
        {"compound_id": "A", "input_smiles": "CCO", "mol_parse_ok": True, "description_error": "", "x": 1.0},
        {"compound_id": "B", "input_smiles": "CCN", "mol_parse_ok": True, "description_error": "", "x": 2.0},
    ]).to_csv(payload, index=False)
    output = tmp_path / "node-output"
    spaces = build_feature_spaces([(capability, payload)], output)
    assert Path(spaces[0]["distance_path"]).parent == output / "distance"
    assert (output / "distance" / "D001.npy").is_file()


def test_description_adapter_uses_external_temporary_subset_and_legacy_identity(tmp_path, monkeypatch) -> None:
    skill = tmp_path / "skill"
    (skill / "scripts").mkdir(parents=True)
    (skill / "scripts" / "launch.py").write_text("# fixture\n", encoding="utf-8")
    capability = {
        "capability_id": "D999", "skill_name": "cs-fixture", "version": "1",
        "calculation_version": "1", "output": {"basename": "fixture"},
        "implementation": {"algorithm": "fixture"}, "value_semantics": "dense_continuous",
        "natural_metric": "euclidean", "_skill_path": str(skill), "_skill_dir": str(skill),
    }
    dataset = tmp_path / "input.csv"
    pd.DataFrame([{"compound_id": "A", "smiles": "CCO"}]).to_csv(dataset, index=False)
    output = tmp_path / "output" / "D999"

    def fake_run(command, **kwargs):
        subset = Path(command[command.index("--input") + 1])
        assert subset.is_file()
        assert output not in subset.parents
        assert command[command.index("--round-id") + 1] == "RND0001"
        assert command[command.index("--node-id") + 1].startswith("N")
        assert len(command[command.index("--node-id") + 1]) == 7
        assert kwargs["env"]["CONDUCTOR_AVAILABLE_CPU_CORES"] == "4"
        output.mkdir(parents=True)
        pd.DataFrame([{"compound_id": "A", "input_smiles": "CCO", "mol_parse_ok": True, "description_error": "", "x": 1.0}]).to_csv(output / "fixture.csv", index=False)
        (output / "description_manifest.json").write_text(json.dumps({"output": "fixture.csv", "feature_columns": ["x"], "value_semantics": "dense_continuous", "natural_metric": "euclidean"}), encoding="utf-8")
        return type("Completed", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr("description_adapter.subprocess.run", fake_run)
    _, plan = run_description_capability(
        project_root=tmp_path, program_name="program", dataset_path=dataset,
        id_column="compound_id", smiles_column="smiles", capability=capability,
        parameters={}, output_directory=output,
        identity={"project": "P", "run_id": "RUN", "phase_id": "P01", "node_id": "NODE-P01-D999", "attempt_id": "ATT-uuid"},
        available_cpu_cores=4,
    )
    assert plan["subset_was_materialized"] is True
    assert plan["subset_path"] is None
