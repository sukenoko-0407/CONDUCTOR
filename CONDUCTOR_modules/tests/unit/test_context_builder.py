from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from conductor_context_builder import build_contexts, deduplicate_contexts
from conductor_stat_core import validate_instance


CONTEXT_SCHEMA = Path(__file__).resolve().parents[2] / "schemas" / "context.schema.json"


def _space(tmp_path, identifier: str, tier: int, values: np.ndarray, compounds: list[str]) -> dict:
    payload = tmp_path / f"{identifier}.csv"
    frame = pd.DataFrame(
        {
            "compound_id": compounds,
            "input_smiles": ["CC"] * len(compounds),
            "mol_parse_ok": [True] * len(compounds),
            "description_error": [""] * len(compounds),
            "signal": values[:, 0],
            "noise": values[:, 1],
        }
    )
    frame.to_csv(payload, index=False)
    difference = values[:, None, :] - values[None, :, :]
    distance = np.sqrt(np.square(difference).sum(axis=2)).astype(np.float32)
    matrix = tmp_path / f"{identifier}.npy"
    np.save(matrix, distance, allow_pickle=False)
    metadata = tmp_path / f"{identifier}.json"
    metadata.write_text(json.dumps({"compound_ids": compounds}), encoding="utf-8")
    return {
        "space_id": identifier,
        "tier": tier,
        "structurality": "non_structural",
        "path": str(payload),
        "distance_path": str(matrix),
        "distance_metadata_path": str(metadata),
    }


def test_deduplication_uses_connected_components_and_stable_representative() -> None:
    memberships = {
        "A": {"1", "2", "3", "4"},
        "B": {"1", "2", "3", "4", "5"},
        "C": {"2", "3", "4", "5"},
        "D": {"9"},
    }
    result = deduplicate_contexts(memberships, threshold=0.75).set_index("context_id")
    assert result.loc["A", "representative_context_id"] == "B"
    assert result.loc["C", "representative_context_id"] == "B"
    assert result.loc["B", "is_representative"]
    assert result.loc["D", "representative_context_id"] == "D"


def test_contexts_are_deterministic_quantiles_are_lower_only_and_translation_is_leakage_safe(tmp_path) -> None:
    identifiers = [f"C{index:02d}" for index in range(12)]
    signal = np.r_[np.zeros(6), np.full(6, 10.0)]
    noise = np.arange(12, dtype=float)
    values = np.column_stack((signal, noise))
    spaces = [
        _space(tmp_path, "D001", 1, values, identifiers),
        _space(tmp_path, "D002", 3, values, identifiers),
    ]
    compounds = pd.DataFrame(
        {
            "compound_id": identifiers,
            "canonical_smiles": ["CCc1ccccc1", "CCCc1ccncc1"] * 6,
            "mol_parse_ok": [True] * 12,
        }
    )
    endpoints = pd.DataFrame(
        {
            "compound_id": identifiers,
            "endpoint_id": ["EP"] * 12,
            "oriented_value": np.arange(12, dtype=float),
        }
    )
    result = build_contexts(
        compounds.sample(frac=1, random_state=4),
        endpoints,
        spaces,
        "EP",
        cluster_counts=[2],
        quantiles=[0.5],
        min_endpoint_n=2,
        translation_auc_min=0.70,
    )
    repeated = build_contexts(
        compounds,
        endpoints,
        spaces,
        "EP",
        cluster_counts=[2],
        quantiles=[0.5],
        min_endpoint_n=2,
        translation_auc_min=0.70,
    )
    assert result.catalog["context_id"].tolist() == repeated.catalog["context_id"].tolist()

    quantile = result.catalog.loc[
        result.catalog["context_type"].eq("quantile") & result.catalog["feature_id"].eq("D001:noise")
    ].iloc[0]
    members = result.membership.loc[result.membership["context_id"].eq(quantile.context_id), "compound_id"]
    selected_positions = [identifiers.index(value) for value in members]
    assert max(selected_positions) <= 5
    assert len(selected_positions) == 6

    translated = result.translations.loc[result.translations["status"].eq("translated")]
    assert not translated.empty
    assert translated["auc"].max() >= 0.95
    assert result.catalog["calibration_scope"].any()
    assert set(result.activity_diagnostic["favorable"]) == {False, True}
    scaffold_members = (
        result.membership.merge(result.catalog[["context_id", "scaffold_type"]], on="context_id")
        .groupby(["scaffold_type", "context_id"])["compound_id"]
        .nunique()
    )
    assert scaffold_members.loc["murcko"].max() == 6
    assert scaffold_members.loc["mcs"].max() == 12
    mcs_key = result.catalog.loc[result.catalog["scaffold_type"].eq("mcs"), "scaffold_key"].iloc[0]
    assert "#6" in mcs_key
    for raw in result.catalog.to_dict(orient="records"):
        record = {key: None if pd.isna(value) else value for key, value in raw.items()}
        validate_instance(record, CONTEXT_SCHEMA)
