from __future__ import annotations

import json
import sqlite3

import pandas as pd
from rdkit import Chem

from conductor_fragment_engine import FragmentationConfig, build_fragment_database, fragment_compound


def _heavy_atoms(smiles: str) -> int:
    molecule = Chem.MolFromSmiles(smiles)
    assert molecule is not None
    return molecule.GetNumHeavyAtoms()


def test_fragmentation_builds_terminal_linker_and_ring_classes() -> None:
    records = fragment_compound("C1", "CCCCc1ccccc1CCCC")
    accepted = {record.transform_class for record in records if record.status == "accepted"}
    assert accepted == {
        "terminal_substitution",
        "linker_replacement",
        "ring_system_replacement",
    }


def test_ring_side_is_selected_by_original_atom_indices() -> None:
    records = fragment_compound("C1", "CCCCc1ccccc1CCCC")
    ring = next(
        record
        for record in records
        if record.status == "accepted"
        and record.transform_class == "ring_system_replacement"
        and record.cut_count == 2
    )
    assert _heavy_atoms(ring.variable_smiles) == 6
    assert sorted(_heavy_atoms(item) for item in ring.constant_key.split(" | ")) == [4, 4]


def test_ring_attachment_and_individual_constant_limits_are_audited() -> None:
    crowded = fragment_compound("C1", "CCCCc1c(CCCC)c(CCCC)c(CCCC)c(CCCC)c1CCCC")
    assert any(record.exclusion_reason == "ring_attachment_count_exceeded" for record in crowded)

    tiny_constants = fragment_compound("C2", "Cc1ccccc1C")
    ring = [record for record in tiny_constants if record.transform_class == "ring_system_replacement"]
    assert ring and all(record.exclusion_reason == "constant_too_small" for record in ring)


def test_database_orients_pairs_collapses_observations_and_marks_complete(tmp_path) -> None:
    compounds = pd.DataFrame(
        [
            {"compound_id": "A", "canonical_smiles": "CCCCc1ccccc1", "mol_parse_ok": True},
            {"compound_id": "A2", "canonical_smiles": "CCCCc1ccccc1", "mol_parse_ok": True},
            {"compound_id": "B", "canonical_smiles": "CCCCCc1ccccc1", "mol_parse_ok": True},
            {"compound_id": "R1", "canonical_smiles": "CCCCc1ccccc1CCCC", "mol_parse_ok": True},
            {"compound_id": "R2", "canonical_smiles": "CCCCc1ncccc1CCCC", "mol_parse_ok": True},
        ]
    )
    endpoints = pd.DataFrame(
        [
            {"compound_id": "A", "endpoint_id": "EP", "oriented_value": 1.0},
            {"compound_id": "A2", "endpoint_id": "EP", "oriented_value": 3.0},
            {"compound_id": "B", "endpoint_id": "EP", "oriented_value": 4.0},
            {"compound_id": "R1", "endpoint_id": "EP", "oriented_value": 5.0},
            {"compound_id": "R2", "endpoint_id": "EP", "oriented_value": 6.0},
        ]
    )
    result = build_fragment_database(compounds, endpoints, "EP", tmp_path)
    parallel = build_fragment_database(
        compounds,
        endpoints,
        "EP",
        tmp_path / "parallel",
        similar_core_workers=2,
    )

    assert not result.pairs.empty
    assert (result.pairs["variable_from"] < result.pairs["variable_to"]).all()
    duplicate = result.observations.loc[result.observations["compound_ids_json"].eq('["A","A2"]')]
    assert len(duplicate) >= 1
    assert (duplicate["n_compounds"] == 2).all()
    assert (duplicate["endpoint_mean"] == 2.0).all()
    assert result.similar_core_map.to_dict(orient="records") == parallel.similar_core_map.to_dict(orient="records")
    for name in (
        "mmp.sqlite",
        "fragment_observations.csv",
        "fragmentation_exclusions.csv",
        "pair_endpoint_values.csv",
        "cliff_candidates.csv",
    ):
        assert (tmp_path / name).read_bytes() == (tmp_path / "parallel" / name).read_bytes(), name

    with sqlite3.connect(tmp_path / "mmp.sqlite") as connection:
        metadata = {key: json.loads(value) for key, value in connection.execute("SELECT key,value_json FROM metadata")}
        assert metadata["complete"] is True
        assert metadata["tables"]["pairs"]["count"] == len(result.pairs)
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_size_boundaries_are_configurable() -> None:
    strict = FragmentationConfig(min_constant_heavy_atoms=5)
    records = fragment_compound("C1", "CCCCc1ccccc1CCCC", strict)
    target = [
        record
        for record in records
        if record.transform_class == "ring_system_replacement" and record.cut_count == 2
    ]
    assert target and target[0].exclusion_reason == "constant_too_small"
