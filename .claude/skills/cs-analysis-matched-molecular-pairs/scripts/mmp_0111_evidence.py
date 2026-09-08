from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

import pandas as pd
from rdkit import Chem, DataStructs

from mmp_engine import stable_id
from mmp_0111_model import (
    NEUTRAL_TOLERANCE,
    attachment_neutral_structure,
    attachment_topology,
    attachment_topology_unlabeled,
    canonical_structure,
    core_similarity_mapping,
    core_fingerprint,
    environment_signature,
    maximum_disjoint_pair_count,
    weld_labeled_fragments,
)


EVIDENCE_COLUMNS = [
    "evidence_id", "target_compound_id", "target_fragmentation_id",
    "pair_id", "compound_pair_id", "pair_transformation_id", "mmp_id", "cut_count", "connection_scope",
    "evidence_class", "environment_group_id", "environment_match_radius",
    "mapping_status", "core_tanimoto", "mcs_coverage",
    "transformation_family_id", "transformation_id", "core_id",
    "exact_core_smiles", "target_core_smiles", "mapped_mcs_smarts",
    "variable_from", "variable_to",
    "target_current_variable", "target_variable_side_fixed",
    "consensus_direction", "target_variable_side_favorable",
    "interpretation_role", "observation_status", "target_evidence_quality",
    "compound_id_from", "compound_id_to", "smiles_from", "smiles_to",
    "endpoint_from", "endpoint_to", "neighbor_compound_id",
    "target_smiles", "neighbor_smiles", "target_endpoint", "neighbor_endpoint",
    "normalized_signed_delta", "fixed_direction_effect",
    "consensus_aligned_delta", "pair_favorable_gain", "target_oriented_delta", "effect_status",
    "two_cut_quality_class", "two_cut_quality_reasons",
    "unique_pair_count", "unique_compound_count", "unique_context_count",
    "supporting_pair_count", "conflicting_pair_count", "neutral_pair_count",
    "missing_pair_count", "direction_consistency", "disjoint_pair_count",
    "median_consensus_aligned_delta", "iqr_consensus_aligned_delta",
]


def normalize_target_registry(
    parameters: dict[str, Any], data: pd.DataFrame, compound_id_column: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Normalize explicit targets and preserve all selection sources."""
    entries = parameters.get("targets")
    if entries is None:
        ids = parameters.get("target_compound_ids") or []
        if isinstance(ids, str):
            ids = [ids]
        source_map = parameters.get("target_selection_sources") or {}
        entries = [
            {
                "compound_id": str(value),
                "selection_sources": source_map.get(str(value), [
                    {"source_type": "human_explicit", "source_id": "on_demand"}
                ]),
            }
            for value in ids
        ]
    if not isinstance(entries, list) or not entries:
        raise ValueError("MMP mode=target requires a non-empty parameters.targets list")
    known = set(data[compound_id_column].astype(str))
    registry: dict[str, dict[str, Any]] = {}
    source_rows: list[dict[str, str]] = []
    allowed_sources = {"analysis_unit_top1", "global_top1", "human_explicit"}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Each MMP target entry must be an object")
        target_id = str(entry.get("compound_id", "")).strip()
        if not target_id:
            raise ValueError("Each MMP target requires compound_id")
        if target_id not in known:
            raise ValueError(f"MMP target is not present in this Run: {target_id}")
        registry.setdefault(target_id, {"target_compound_id": target_id})
        sources = entry.get("selection_sources") or []
        if not sources:
            raise ValueError(f"MMP target {target_id} requires at least one selection source")
        for source in sources:
            if not isinstance(source, dict):
                raise ValueError("selection_sources entries must be objects")
            source_type = str(source.get("source_type", "")).strip()
            source_id = str(source.get("source_id", "")).strip()
            if source_type not in allowed_sources:
                raise ValueError(f"Unsupported MMP selection source_type: {source_type}")
            key = (target_id, source_type, source_id)
            if not any(
                (row["target_compound_id"], row["source_type"], row["source_id"]) == key
                for row in source_rows
            ):
                source_rows.append({
                    "target_compound_id": target_id,
                    "source_type": source_type,
                    "source_id": source_id,
                })
    registry_frame = pd.DataFrame(registry.values()).sort_values("target_compound_id")
    source_frame = pd.DataFrame(
        source_rows,
        columns=["target_compound_id", "source_type", "source_id"],
    ).sort_values(["target_compound_id", "source_type", "source_id"])
    return registry_frame.reset_index(drop=True), source_frame.reset_index(drop=True)


def _direct_evidence(
    target_id: str,
    details: pd.DataFrame,
    data_lookup: pd.DataFrame,
    neutral_tolerance: float,
) -> list[dict[str, Any]]:
    mask = details["compound_id_from"].astype(str).eq(target_id) | details[
        "compound_id_to"
    ].astype(str).eq(target_id)
    rows: list[dict[str, Any]] = []
    for record in details.loc[mask].to_dict(orient="records"):
        target_is_from = str(record["compound_id_from"]) == target_id
        effect = float(record["fixed_direction_effect"]) if pd.notna(record["fixed_direction_effect"]) else math.nan
        if not math.isfinite(effect) or abs(effect) < neutral_tolerance:
            role = "neutral"
            fixed_side = "A" if target_is_from else "B"
            favorable_side = "neutral"
            gain = abs(effect) if math.isfinite(effect) else math.nan
        else:
            fixed_side = "A" if target_is_from else "B"
            # target_variable_side_favorable is the Target's position after
            # orienting this pair as less-favorable A -> favorable B.
            if effect > 0:
                favorable_side = fixed_side
            else:
                favorable_side = "B" if fixed_side == "A" else "A"
            role = "target_explanation" if favorable_side == "B" else "observed_improvement"
            gain = abs(effect)
        neighbor_id = str(record["compound_id_to"] if target_is_from else record["compound_id_from"])
        neighbor = data_lookup.loc[neighbor_id] if neighbor_id in data_lookup.index else None
        target = data_lookup.loc[target_id]
        row = dict(record)
        from_id = str(record["compound_id_from"])
        to_id = str(record["compound_id_to"])
        from_compound = data_lookup.loc[from_id] if from_id in data_lookup.index else None
        to_compound = data_lookup.loc[to_id] if to_id in data_lookup.index else None
        row.update({
            "evidence_id": stable_id("EVD-DIRECT", target_id, record["mmp_id"]),
            "target_compound_id": target_id,
            "target_fragmentation_id": "",
            "connection_scope": "direct",
            "evidence_class": "Exact-core evidence",
            "environment_group_id": stable_id(
                "ENVG", int(record["cut_count"]), record["attachment_topology"],
                "exact", record.get("environment_signature_radius_2", ""),
            ),
            "environment_match_radius": "exact",
            "mapping_status": "unique",
            "core_tanimoto": 1.0,
            "mcs_coverage": 1.0,
            "target_core_smiles": record["exact_core_smiles"],
            "mapped_mcs_smarts": record["exact_core_smiles"],
            "target_current_variable": record["variable_from"] if target_is_from else record["variable_to"],
            "target_variable_side_fixed": fixed_side,
            "consensus_direction": "fixed" if not math.isfinite(effect) or effect >= 0 else "reverse",
            "target_variable_side_favorable": favorable_side,
            "interpretation_role": role,
            "observation_status": "observed",
            "target_evidence_quality": "high",
            "neighbor_compound_id": neighbor_id,
            "smiles_from": str(from_compound["smiles"]) if from_compound is not None else "",
            "smiles_to": str(to_compound["smiles"]) if to_compound is not None else "",
            "endpoint_from": from_compound["endpoint"] if from_compound is not None else math.nan,
            "endpoint_to": to_compound["endpoint"] if to_compound is not None else math.nan,
            "target_smiles": str(target["smiles"]),
            "neighbor_smiles": str(neighbor["smiles"]) if neighbor is not None else "",
            "target_endpoint": target["endpoint"],
            "neighbor_endpoint": neighbor["endpoint"] if neighbor is not None else math.nan,
            "consensus_aligned_delta": abs(effect) if math.isfinite(effect) else math.nan,
            "pair_favorable_gain": gain,
            # Target reports always display Neighbor -> Target.  This signed
            # value therefore means "Target minus Neighbor" after applying
            # the Run's higher/lower-is-better convention.  It is deliberately
            # not forced positive: positive observations support the Target's
            # Endpoint, negative observations expose an improvement direction.
            "target_oriented_delta": (
                (-effect if target_is_from else effect)
                if math.isfinite(effect) else math.nan
            ),
        })
        rows.append(row)
    return rows


def _environment_class(target_fragment: pd.Series, candidate: dict[str, Any]) -> tuple[str, Any, str]:
    if str(target_fragment["constant_structure_key"]) == str(candidate["exact_core_key"]):
        label, radius = "Exact-core evidence", "exact"
    elif (
        str(target_fragment["environment_signature_radius_2"])
        == str(candidate.get("environment_signature_radius_2", ""))
    ):
        label, radius = "Radius-2 matched similar-core evidence", 2
    elif (
        str(target_fragment["environment_signature_radius_1"])
        == str(candidate.get("environment_signature_radius_1", ""))
    ):
        label, radius = "Radius-1 matched related-core evidence", 1
    else:
        label, radius = "Attachment-mapped but environment-mismatched reference", "mismatch"
    signature = (
        candidate.get("environment_signature_radius_2", "") if radius in ("exact", 2)
        else candidate.get("environment_signature_radius_1", "") if radius == 1
        else candidate.get("core_id", "")
    )
    group_id = stable_id(
        "ENVG", int(candidate["cut_count"]), candidate["attachment_topology"],
        radius, signature,
    )
    return label, radius, group_id


def _consensus_sign(frame: pd.DataFrame, neutral_tolerance: float) -> int:
    values = (
        frame.assign(
            _effect=pd.to_numeric(frame["fixed_direction_effect"], errors="coerce")
        )
        .groupby("pair_id", dropna=False)["_effect"]
        .median()
    )
    values = values[values.abs().ge(neutral_tolerance)]
    positive = int(values.gt(0).sum())
    negative = int(values.lt(0).sum())
    # Count descending, then canonical fixed direction first. This is the
    # deliberately simple deterministic tie rule approved for 0.1.11.
    return 1 if positive >= negative else -1


def _add_group_metrics(
    frame: pd.DataFrame,
    neutral_tolerance: float,
    direction_anchors: dict[tuple[str, str], pd.DataFrame] | None = None,
) -> pd.DataFrame:
    if frame.empty:
        return frame
    output: list[pd.DataFrame] = []
    keys = ["target_compound_id", "transformation_family_id", "environment_group_id"]
    for _, group in frame.groupby(keys, dropna=False, sort=True):
        group = group.copy()
        anchor_key = (
            str(group.iloc[0]["target_compound_id"]),
            str(group.iloc[0]["transformation_family_id"]),
        )
        vote = (direction_anchors or {}).get(anchor_key, group)
        sign = _consensus_sign(vote, neutral_tolerance)
        group["consensus_direction"] = "fixed" if sign > 0 else "reverse"
        group["consensus_aligned_delta"] = (
            pd.to_numeric(group["fixed_direction_effect"], errors="coerce") * sign
        )
        pair_effects = (
            group.assign(_aligned=pd.to_numeric(group["consensus_aligned_delta"], errors="coerce"))
            .groupby("pair_id", dropna=False)["_aligned"].median()
        )
        nonneutral = pair_effects[pair_effects.abs().ge(neutral_tolerance)].dropna()
        supporting = int(nonneutral.gt(0).sum())
        conflicting = int(nonneutral.lt(0).sum())
        pair_values = group[["pair_id", "compound_id_from", "compound_id_to"]].drop_duplicates("pair_id")
        unique_pairs = int(len(pair_values))
        compounds = set(pair_values["compound_id_from"].astype(str)) | set(pair_values["compound_id_to"].astype(str))
        unique_context = int(group["core_id"].nunique())
        neutral_count = int(pair_effects.abs().lt(neutral_tolerance).sum())
        missing_count = int(pair_effects.isna().sum())
        direction_consistency = supporting / (supporting + conflicting) if supporting + conflicting else math.nan
        group["unique_pair_count"] = unique_pairs
        group["unique_compound_count"] = len(compounds)
        group["unique_context_count"] = unique_context
        group["supporting_pair_count"] = supporting
        group["conflicting_pair_count"] = conflicting
        group["neutral_pair_count"] = neutral_count
        group["missing_pair_count"] = missing_count
        group["direction_consistency"] = direction_consistency
        group["disjoint_pair_count"] = maximum_disjoint_pair_count(
            pair_values[["compound_id_from", "compound_id_to"]].itertuples(index=False, name=None)
        )
        group["median_consensus_aligned_delta"] = float(nonneutral.median()) if len(nonneutral) else math.nan
        group["iqr_consensus_aligned_delta"] = (
            float(nonneutral.quantile(.75) - nonneutral.quantile(.25)) if len(nonneutral) else math.nan
        )
        output.append(group)
    return pd.concat(output, ignore_index=True)


def build_target_evidence(
    target_id: str,
    *,
    details: pd.DataFrame,
    fragmentations: pd.DataFrame,
    data: pd.DataFrame,
    compound_id_column: str,
    smiles_column: str,
    endpoint_column: str,
    neutral_tolerance: float = NEUTRAL_TOLERANCE,
    core_tanimoto_threshold: float = 0.70,
    mcs_coverage_threshold: float = 0.70,
) -> pd.DataFrame:
    """Build Direct and Transferred evidence without mutating the database."""
    details = details.copy()
    fragmentations = fragmentations.copy()
    # Schema 2 stores both original ordered attachment structures and
    # label-neutral query keys.  Derive keys when loading an early 0.1.11
    # development database so reuse fails gracefully rather than silently
    # yielding no Transferred evidence.
    if "variable_from_key" not in details:
        details["variable_from_key"] = details["variable_from"].map(attachment_neutral_structure)
    if "variable_to_key" not in details:
        details["variable_to_key"] = details["variable_to"].map(attachment_neutral_structure)
    if "variable_from_ordered_key" not in details:
        details["variable_from_ordered_key"] = details["variable_from"].map(canonical_structure)
    if "variable_to_ordered_key" not in details:
        details["variable_to_ordered_key"] = details["variable_to"].map(canonical_structure)
    if "exact_core_key" not in details:
        details["exact_core_key"] = details["exact_core_smiles"].map(attachment_neutral_structure)
    if "attachment_topology_unlabeled" not in details:
        details["attachment_topology_unlabeled"] = details["exact_core_smiles"].map(
            attachment_topology_unlabeled
        )
    if "variable_structure_key" not in fragmentations:
        fragmentations["variable_structure_key"] = fragmentations["variable_smiles"].map(
            attachment_neutral_structure
        )
    if "constant_structure_key" not in fragmentations:
        fragmentations["constant_structure_key"] = fragmentations["constant_smiles"].map(
            attachment_neutral_structure
        )
    if "variable_ordered_key" not in fragmentations:
        fragmentations["variable_ordered_key"] = fragmentations["variable_smiles"].map(
            canonical_structure
        )
    if "constant_ordered_key" not in fragmentations:
        fragmentations["constant_ordered_key"] = fragmentations["constant_smiles"].map(
            canonical_structure
        )
    if "attachment_topology_unlabeled" not in fragmentations:
        fragmentations["attachment_topology_unlabeled"] = fragmentations["constant_smiles"].map(
            attachment_topology_unlabeled
        )
    # Recompute with the 0.1.11 label-neutral definition.  This also makes an
    # early development database safe to inspect without treating [*:1] and
    # unlabeled * as different chemical environments.
    for radius in (1, 2):
        details[f"environment_signature_radius_{radius}"] = details[
            "exact_core_smiles"
        ].map(lambda value, r=radius: environment_signature(value, r))
        fragmentations[f"environment_signature_radius_{radius}"] = fragmentations[
            "constant_smiles"
        ].map(lambda value, r=radius: environment_signature(value, r))
    lookup = data[[compound_id_column, smiles_column, endpoint_column]].copy()
    lookup.columns = ["compound_id", "smiles", "endpoint"]
    lookup["compound_id"] = lookup["compound_id"].astype(str)
    lookup = lookup.drop_duplicates("compound_id").set_index("compound_id")
    direct_rows = _direct_evidence(target_id, details, lookup, neutral_tolerance)
    direct_anchor_frame = pd.DataFrame(direct_rows)
    direction_anchors: dict[tuple[str, str], pd.DataFrame] = {}
    if len(direct_anchor_frame):
        for family_id, group in direct_anchor_frame.groupby(
            "transformation_family_id", dropna=False, sort=True
        ):
            direction_anchors[(target_id, str(family_id))] = group

    target_fragments = fragmentations.loc[
        fragmentations["compound_id"].astype(str).eq(target_id)
    ].copy()
    transferred: list[dict[str, Any]] = []
    mapping_cache: dict[tuple[str, str], dict[str, Any]] = {}
    fingerprint_cache: dict[str, Any] = {}
    # Restrict by cut count and attachment topology before the expensive MCS
    # check.  Do not require the current variable to equal A/B here: a mapped
    # Core with a third fragment is retained as the user-approved `neither`
    # reference class.
    for _, target_fragment in target_fragments.iterrows():
        cut_count = int(target_fragment["cut_count"])
        current_variable = str(target_fragment.get(
            "variable_ordered_smiles", canonical_structure(target_fragment["variable_smiles"])
        ))
        current_key = str(target_fragment["variable_ordered_key"])
        candidates = details.loc[
            details["cut_count"].eq(cut_count)
            & details["attachment_topology_unlabeled"].eq(
                target_fragment["attachment_topology_unlabeled"]
            )
            & ~details["compound_id_from"].astype(str).eq(target_id)
            & ~details["compound_id_to"].astype(str).eq(target_id)
        ]
        if cut_count == 2:
            candidates = candidates.loc[
                candidates["two_cut_quality_class"].isin(["2C-A", "2C-B"])
            ]
        if candidates.empty:
            continue
        target_core = str(target_fragment["constant_smiles"])
        target_fp = fingerprint_cache.get(target_core)
        if target_fp is None:
            target_fp = core_fingerprint(target_core)
            fingerprint_cache[target_core] = target_fp
        if target_fp is None:
            continue
        candidate_cores = candidates["exact_core_smiles"].astype(str).drop_duplicates().tolist()
        valid_cores: list[str] = []
        valid_fps: list[Any] = []
        for candidate_core in candidate_cores:
            fingerprint = fingerprint_cache.get(candidate_core)
            if fingerprint is None:
                fingerprint = core_fingerprint(candidate_core)
                fingerprint_cache[candidate_core] = fingerprint
            if fingerprint is not None:
                valid_cores.append(candidate_core)
                valid_fps.append(fingerprint)
        similarities = DataStructs.BulkTanimotoSimilarity(target_fp, valid_fps)
        eligible_cores = {
            core for core, similarity in zip(valid_cores, similarities)
            if similarity >= core_tanimoto_threshold
        }
        candidates = candidates.loc[
            candidates["exact_core_smiles"].astype(str).isin(eligible_cores)
        ]
        for record in candidates.to_dict(orient="records"):
            core_pair = (str(target_fragment["constant_smiles"]), str(record["exact_core_smiles"]))
            exact = (
                str(target_fragment["constant_ordered_key"])
                == canonical_structure(record["exact_core_smiles"])
            )
            mapping = {
                "core_tanimoto": 1.0,
                "mcs_coverage": 1.0,
                "mapping_status": "unique",
            } if exact else mapping_cache.get(core_pair)
            if mapping is None:
                mapping = core_similarity_mapping(
                    *core_pair,
                    minimum_tanimoto=core_tanimoto_threshold,
                    left_fingerprint=target_fp,
                    right_fingerprint=fingerprint_cache.get(core_pair[1]),
                )
                mapping_cache[core_pair] = mapping
            if not exact and (
                float(mapping.get("core_tanimoto", 0)) < core_tanimoto_threshold
                or float(mapping.get("mcs_coverage", 0)) < mcs_coverage_threshold
                or mapping.get("mapping_status") not in {"unique", "symmetry_equivalent"}
            ):
                continue
            label, radius, environment_group = _environment_class(target_fragment, record)
            matches_from = current_key == str(record["variable_from_ordered_key"])
            matches_to = current_key == str(record["variable_to_ordered_key"])
            fixed_side = "both" if matches_from and matches_to else "A" if matches_from else "B" if matches_to else "neither"
            row = dict(record)
            from_id = str(record["compound_id_from"])
            to_id = str(record["compound_id_to"])
            from_compound = lookup.loc[from_id] if from_id in lookup.index else None
            to_compound = lookup.loc[to_id] if to_id in lookup.index else None
            row.update({
                "evidence_id": stable_id(
                    "EVD-XFER", target_id, target_fragment["fragmentation_id"],
                    record["mmp_id"], environment_group,
                ),
                "target_compound_id": target_id,
                "target_fragmentation_id": target_fragment["fragmentation_id"],
                "connection_scope": "transferred",
                "evidence_class": label,
                "environment_group_id": environment_group,
                "environment_match_radius": radius,
                "mapping_status": "unique" if exact else mapping.get("mapping_status", "failed"),
                "core_tanimoto": 1.0 if exact else mapping.get("core_tanimoto", 0.0),
                "mcs_coverage": 1.0 if exact else mapping.get("mcs_coverage", 0.0),
                "target_core_smiles": str(target_fragment.get(
                    "constant_ordered_smiles", target_fragment["constant_smiles"]
                )),
                "mapped_mcs_smarts": (
                    str(target_fragment.get(
                        "constant_ordered_smiles", target_fragment["constant_smiles"]
                    )) if exact else str(mapping.get("mcs_smarts", ""))
                ),
                "target_current_variable": current_variable,
                "target_variable_side_fixed": fixed_side,
                "smiles_from": str(from_compound["smiles"]) if from_compound is not None else "",
                "smiles_to": str(to_compound["smiles"]) if to_compound is not None else "",
                "endpoint_from": from_compound["endpoint"] if from_compound is not None else math.nan,
                "endpoint_to": to_compound["endpoint"] if to_compound is not None else math.nan,
                "target_smiles": str(lookup.loc[target_id, "smiles"]),
                "target_endpoint": lookup.loc[target_id, "endpoint"],
                "neighbor_compound_id": "",
                "neighbor_smiles": "",
                "neighbor_endpoint": math.nan,
                "observation_status": "observed_reference",
            })
            transferred.append(row)

    transfer_frame = pd.DataFrame(transferred)
    if len(transfer_frame):
        transfer_frame = _add_group_metrics(
            transfer_frame, neutral_tolerance, direction_anchors
        )
        favorable_side: list[str] = []
        roles: list[str] = []
        qualities: list[str] = []
        gains: list[float] = []
        target_deltas: list[float] = []
        for record in transfer_frame.to_dict(orient="records"):
            fixed_side = str(record["target_variable_side_fixed"])
            consensus_sign = 1 if record["consensus_direction"] == "fixed" else -1
            if fixed_side in {"both", "neither"}:
                side = fixed_side
            elif consensus_sign > 0:
                side = fixed_side
            else:
                side = "B" if fixed_side == "A" else "A"
            favorable_side.append(side)
            if side == "A":
                role = "proposed_improvement"
            elif side == "B":
                role = "transferred_explanation"
            elif side == "neither":
                role = "not_applicable"
            else:
                role = "ambiguous"
            roles.append(role)
            direction_ok = (
                int(record.get("unique_pair_count", 0)) >= 3
                and int(record.get("unique_context_count", 0)) >= 2
                and float(record.get("direction_consistency", 0) or 0) >= .80
            )
            mapping_ok = record.get("mapping_status") in {"unique", "symmetry_equivalent"}
            environment_ok = record.get("environment_match_radius") in {"exact", 2}
            if role == "not_applicable":
                quality = "not_applicable"
            elif role == "ambiguous" or not mapping_ok:
                quality = "ambiguous"
            elif direction_ok and environment_ok:
                quality = "high"
            else:
                quality = "limited"
            qualities.append(quality)
            value = record.get("consensus_aligned_delta")
            gains.append(max(0.0, float(value)) if pd.notna(value) else math.nan)
            # A Transferred row does not contain the Target as an observed
            # compound.  Orient its observed effect toward the side matching
            # the Target's current fragment so that the sign has the same
            # report meaning as Direct evidence.  `neither`/`both` cannot be
            # given a Target-oriented effect and remain references.
            if pd.isna(value) or side not in {"A", "B"}:
                target_deltas.append(math.nan)
            else:
                target_deltas.append(float(value) if side == "B" else -float(value))
        transfer_frame["target_variable_side_favorable"] = favorable_side
        transfer_frame["interpretation_role"] = roles
        transfer_frame["target_evidence_quality"] = qualities
        transfer_frame["pair_favorable_gain"] = gains
        transfer_frame["target_oriented_delta"] = target_deltas
    direct_frame = pd.DataFrame(direct_rows)
    if len(direct_frame):
        direct_frame = _add_group_metrics(direct_frame, neutral_tolerance)
        direct_frame["target_evidence_quality"] = "high"
        direct_frame.loc[
            direct_frame["cut_count"].eq(2)
            & direct_frame["two_cut_quality_class"].eq("2C-B"),
            "target_evidence_quality",
        ] = "limited"
        direct_frame.loc[
            direct_frame["cut_count"].eq(2)
            & direct_frame["two_cut_quality_class"].eq("2C-X"),
            "target_evidence_quality",
        ] = "ambiguous"
    combined = pd.concat([direct_frame, transfer_frame], ignore_index=True, sort=False)
    if combined.empty:
        return pd.DataFrame(columns=EVIDENCE_COLUMNS)
    for column in EVIDENCE_COLUMNS:
        if column not in combined:
            combined[column] = ""
    return combined[EVIDENCE_COLUMNS].drop_duplicates("evidence_id").sort_values(
        ["connection_scope", "interpretation_role", "pair_favorable_gain", "evidence_id"],
        ascending=[True, True, False, True], na_position="last", kind="mergesort",
    ).reset_index(drop=True)


def build_virtual_candidates(
    target_id: str,
    evidence: pd.DataFrame,
    fragmentations: pd.DataFrame,
    data: pd.DataFrame,
    compound_id_column: str,
    smiles_column: str,
    endpoint_column: str,
) -> pd.DataFrame:
    """Apply high-quality proposed transformations and validate products."""
    columns = [
        "virtual_candidate_id", "target_compound_id", "source_evidence_id",
        "source_evidence_ids", "source_evidence_count",
        "candidate_smiles", "candidate_status", "observed_compound_id",
        "candidate_endpoint", "mapping_status", "stereochemistry_status",
        "candidate_display_class", "target_evidence_quality", "evidence_class",
        "direction_consistency", "unique_pair_count", "median_consensus_aligned_delta",
    ]
    proposed = evidence.loc[
        evidence["interpretation_role"].eq("proposed_improvement")
        & evidence["target_evidence_quality"].eq("high")
    ]
    if proposed.empty:
        return pd.DataFrame(columns=columns)
    known: dict[str, list[str]] = defaultdict(list)
    known_endpoint: dict[str, Any] = {}
    for record in data[[compound_id_column, smiles_column]].itertuples(index=False, name=None):
        molecule = Chem.MolFromSmiles(str(record[1]))
        if molecule is not None:
            key = Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True)
            known[key].append(str(record[0]))
    known_endpoint = dict(zip(
        data[compound_id_column].astype(str),
        pd.to_numeric(data[endpoint_column], errors="coerce"),
    ))
    fragment_lookup = fragmentations.set_index("fragmentation_id", drop=False)
    output: list[dict[str, Any]] = []
    for record in proposed.drop_duplicates(
        ["target_fragmentation_id", "transformation_family_id", "consensus_direction"]
    ).itertuples(index=False):
        if record.target_fragmentation_id not in fragment_lookup.index:
            continue
        fragment = fragment_lookup.loc[record.target_fragmentation_id]
        destination = record.variable_to if record.consensus_direction == "fixed" else record.variable_from
        try:
            destination_molecule = Chem.MolFromSmiles(str(destination))
            if destination_molecule is None or sum(
                atom.GetAtomicNum() == 0 for atom in destination_molecule.GetAtoms()
            ) != int(fragment["cut_count"]):
                continue
            constant = str(fragment.get("constant_ordered_smiles", fragment["constant_smiles"]))
            product = weld_labeled_fragments(constant, str(destination))
            canonical = Chem.MolToSmiles(product, canonical=True, isomericSmiles=True)
        except Exception:
            continue
        target_canonical = canonical_structure(record.target_smiles)
        if canonical == target_canonical:
            continue
        observed_ids = known.get(canonical, [])
        status = "observed_compound" if observed_ids else "virtual"
        target_molecule = Chem.MolFromSmiles(str(record.target_smiles))
        target_centers = (
            Chem.FindMolChiralCenters(
                target_molecule, includeUnassigned=True, useLegacyImplementation=False
            ) if target_molecule is not None else []
        )
        product_centers = Chem.FindMolChiralCenters(
            product, includeUnassigned=True, useLegacyImplementation=False
        )
        target_defined = sum(label != "?" for _, label in target_centers)
        target_unassigned = sum(label == "?" for _, label in target_centers)
        product_defined = sum(label != "?" for _, label in product_centers)
        product_unassigned = sum(label == "?" for _, label in product_centers)
        if product_unassigned > target_unassigned:
            stereo_status = "unresolved_new_center"
        elif target_defined and product_defined < target_defined:
            stereo_status = "stereochemistry_reduced_or_undefined"
        elif target_defined:
            stereo_status = "retained_where_defined"
        else:
            stereo_status = "not_applicable"
        output.append({
            "virtual_candidate_id": stable_id("VC", target_id, record.evidence_id, canonical),
            "target_compound_id": target_id,
            "source_evidence_id": record.evidence_id,
            "source_evidence_ids": record.evidence_id,
            "source_evidence_count": 1,
            "candidate_smiles": canonical,
            "candidate_status": status,
            "observed_compound_id": "|".join(sorted(observed_ids)),
            "candidate_endpoint": (
                known_endpoint.get(sorted(observed_ids)[0], math.nan)
                if observed_ids else math.nan
            ),
            "mapping_status": record.mapping_status,
            "stereochemistry_status": stereo_status,
            "candidate_display_class": (
                "reference" if stereo_status == "unresolved_new_center" else "standard"
            ),
            "target_evidence_quality": record.target_evidence_quality,
            "evidence_class": record.evidence_class,
            "direction_consistency": record.direction_consistency,
            "unique_pair_count": record.unique_pair_count,
            "median_consensus_aligned_delta": record.median_consensus_aligned_delta,
        })
    if not output:
        return pd.DataFrame(columns=columns)
    frame = pd.DataFrame(output, columns=columns).sort_values(
        ["candidate_smiles", "candidate_display_class", "source_evidence_id"], kind="mergesort"
    )
    collapsed: list[dict[str, Any]] = []
    for _, group in frame.groupby("candidate_smiles", sort=True):
        row = group.iloc[0].to_dict()
        source_ids = sorted(set(group["source_evidence_id"].astype(str)))
        row["source_evidence_id"] = source_ids[0]
        row["source_evidence_ids"] = "|".join(source_ids)
        row["source_evidence_count"] = len(source_ids)
        collapsed.append(row)
    ranked = pd.DataFrame(collapsed, columns=columns)
    ranked["_display_rank"] = ranked["candidate_display_class"].map(
        {"standard": 0, "reference": 1}
    ).fillna(2)
    ranked["_environment_rank"] = ranked["evidence_class"].map({
        "Exact-core evidence": 0,
        "Radius-2 matched similar-core evidence": 1,
        "Radius-1 matched related-core evidence": 2,
        "Attachment-mapped but environment-mismatched reference": 3,
    }).fillna(4)
    ranked = ranked.sort_values(
        ["_display_rank", "_environment_rank", "direction_consistency",
         "unique_pair_count", "median_consensus_aligned_delta", "virtual_candidate_id"],
        ascending=[True, True, False, False, False, True],
        na_position="last", kind="mergesort",
    ).drop(columns=["_display_rank", "_environment_rank"])
    return ranked.reset_index(drop=True)
