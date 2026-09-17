"""L5 context-pair correlation sign-conflict tests."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from rdkit import Chem
from rdkit.Chem.Scaffolds import MurckoScaffold

from conductor_stat_core import (
    TestRecord,
    assign_finding_ids,
    base_finding,
    benjamini_hochberg,
    derive_seed,
    empirical_p_value,
    permute_within_blocks,
    stable_id,
)


COMMON_COLUMNS = frozenset({"compound_id", "input_smiles", "mol_parse_ok", "description_error"})


@dataclass(frozen=True)
class L5Result:
    evidence: pd.DataFrame
    tests: pd.DataFrame
    score_observations: pd.DataFrame
    findings: tuple[dict[str, Any], ...]
    calibration: dict[str, Any]
    metrics: dict[str, Any]


def _read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, dtype={"compound_id": "string"})


def _feature_matrix(spaces: list[dict[str, Any]], compound_ids: list[str]) -> pd.DataFrame:
    result = pd.DataFrame(index=pd.Index(compound_ids, name="compound_id"))
    for space in sorted((item for item in spaces if int(item["tier"]) <= 2), key=lambda item: item["space_id"]):
        frame = _read_table(Path(space["path"]))
        frame["compound_id"] = frame["compound_id"].astype(str)
        if frame["compound_id"].duplicated().any():
            raise ValueError(f"Duplicate compound_id in {space['space_id']}")
        frame = frame.set_index("compound_id").reindex(compound_ids)
        for column in sorted(frame.columns):
            if column in COMMON_COLUMNS:
                continue
            values = pd.to_numeric(frame[column], errors="coerce")
            if int(np.isfinite(values).sum()) >= 3 and float(values[np.isfinite(values)].std(ddof=0)) > 0:
                result[f"{space['space_id']}:{column}"] = values
    if result.empty:
        raise ValueError("L5 requires at least one finite Tier 1/2 feature")
    return result


def _murcko_blocks(compounds: pd.DataFrame, compound_ids: list[str]) -> list[str]:
    by_id = compounds.set_index(compounds["compound_id"].astype(str))
    blocks: list[str] = []
    for compound_id in compound_ids:
        if compound_id not in by_id.index:
            raise ValueError(f"Compound is absent from compounds table: {compound_id}")
        row = by_id.loc[compound_id]
        molecule = Chem.MolFromSmiles(str(row["canonical_smiles"]))
        if molecule is None:
            blocks.append(f"INVALID:{compound_id}")
            continue
        scaffold = MurckoScaffold.GetScaffoldForMol(molecule)
        key = Chem.MolToSmiles(scaffold, canonical=True) if scaffold.GetNumAtoms() else ""
        blocks.append(key or f"ACYCLIC:{Chem.MolToSmiles(molecule, canonical=True)}")
    return blocks


def _correlation(x: np.ndarray, y: np.ndarray, indices: np.ndarray) -> tuple[float, int]:
    selected = indices[np.isfinite(x[indices]) & np.isfinite(y[indices])]
    if selected.size < 3:
        return math.nan, int(selected.size)
    left, right = x[selected], y[selected]
    if float(np.std(left)) == 0.0 or float(np.std(right)) == 0.0:
        return math.nan, int(selected.size)
    return float(np.corrcoef(left, right)[0, 1]), int(selected.size)


def _fisher_difference(left: float, right: float) -> float:
    epsilon = np.finfo(float).eps
    return float(np.arctanh(np.clip(left, -1 + epsilon, 1 - epsilon)) - np.arctanh(np.clip(right, -1 + epsilon, 1 - epsilon)))


def run_l5(
    compounds: pd.DataFrame,
    endpoints: pd.DataFrame,
    context_catalog: pd.DataFrame,
    context_membership: pd.DataFrame,
    feature_spaces: list[dict[str, Any]],
    endpoint_id: str,
    *,
    run_seed: int,
    min_endpoint_n: int = 5,
    min_abs_r: float = 0.30,
    screen_permutations: int = 100,
    final_permutations: int = 1000,
    screen_p_max: float = 0.05,
    report_q_max: float = 0.05,
    calibration_permutations: int = 20,
) -> L5Result:
    if not 1 <= calibration_permutations <= screen_permutations <= final_permutations:
        raise ValueError("Permutation counts must satisfy calibration <= screen <= final")
    selected = endpoints.loc[endpoints["endpoint_id"].astype(str).eq(endpoint_id), ["compound_id", "oriented_value"]].copy()
    selected["compound_id"] = selected["compound_id"].astype(str)
    selected["oriented_value"] = pd.to_numeric(selected["oriented_value"], errors="coerce")
    selected = selected.loc[np.isfinite(selected["oriented_value"])].sort_values("compound_id")
    if selected["compound_id"].duplicated().any():
        raise ValueError("Endpoint table contains duplicate selected Endpoint rows")
    compound_ids = selected["compound_id"].tolist()
    y = selected["oriented_value"].to_numpy(dtype=float)
    features = _feature_matrix(feature_spaces, compound_ids)
    blocks = _murcko_blocks(compounds, compound_ids)
    position = {value: index for index, value in enumerate(compound_ids)}
    membership: dict[str, np.ndarray] = {}
    for context_id, group in context_membership.groupby(context_membership["context_id"].astype(str), sort=True):
        membership[str(context_id)] = np.asarray(sorted(position[value] for value in group["compound_id"].astype(str) if value in position), dtype=int)
    eligible = context_catalog.copy()
    for column, default in (("is_representative", True), ("eligible", True)):
        if column not in eligible:
            eligible[column] = default
    if "translation_status" in eligible:
        eligible = eligible.loc[~eligible["translation_status"].eq("untranslatable")]
    eligible = eligible.loc[eligible["is_representative"].astype(bool) & eligible["eligible"].astype(bool)]
    axes = {
        str(axis): sorted(str(value) for value in group["context_id"] if str(value) in membership)
        for axis, group in eligible.groupby("axis_id", sort=True)
    }
    context_pairs = [(axis, left, right) for axis, ids in sorted(axes.items()) for left, right in combinations(ids, 2)]
    feature_values = {name: features[name].to_numpy(dtype=float) for name in sorted(features.columns)}
    universe: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for axis_id, left_id, right_id in context_pairs:
        shared_n = len(set(membership[left_id]).intersection(set(membership[right_id])))
        for feature_id, x in feature_values.items():
            left_r, left_n = _correlation(x, y, membership[left_id])
            right_r, right_n = _correlation(x, y, membership[right_id])
            if left_n < min_endpoint_n or right_n < min_endpoint_n or not math.isfinite(left_r) or not math.isfinite(right_r):
                continue
            row = {
                "axis_id": axis_id,
                "context_a": left_id,
                "context_b": right_id,
                "feature_id": feature_id,
                "r_a": left_r,
                "r_b": right_r,
                "n_a": left_n,
                "n_b": right_n,
                "shared_n": shared_n,
                "statistic": _fisher_difference(left_r, right_r),
                "global_r": _correlation(x, y, np.arange(len(y), dtype=int))[0],
                "x": x,
            }
            universe.append(row)
            if abs(left_r) >= min_abs_r and abs(right_r) >= min_abs_r and left_r * right_r < 0:
                candidates.append(row)
    nulls: dict[str, list[float]] = {}
    candidate_by_key: dict[str, dict[str, Any]] = {}
    for row in candidates:
        key = stable_id("L5C", {name: row[name] for name in ("axis_id", "context_a", "context_b", "feature_id")})
        row["candidate_key"] = key
        candidate_by_key[key] = row
        nulls[key] = []
    calibration_counts: list[int] = []
    participation: list[float] = []
    for iteration in range(screen_permutations):
        permuted, fraction = permute_within_blocks(y, blocks, np.random.default_rng(derive_seed(run_seed, "L5", iteration)))
        participation.append(fraction)
        if iteration < calibration_permutations:
            count = 0
            for row in universe:
                left_r, _ = _correlation(row["x"], permuted, membership[row["context_a"]])
                right_r, _ = _correlation(row["x"], permuted, membership[row["context_b"]])
                count += bool(math.isfinite(left_r) and math.isfinite(right_r) and abs(left_r) >= min_abs_r and abs(right_r) >= min_abs_r and left_r * right_r < 0)
            calibration_counts.append(count)
        for key, row in candidate_by_key.items():
            left_r, _ = _correlation(row["x"], permuted, membership[row["context_a"]])
            right_r, _ = _correlation(row["x"], permuted, membership[row["context_b"]])
            nulls[key].append(_fisher_difference(left_r, right_r) if math.isfinite(left_r) and math.isfinite(right_r) else math.nan)
    screen_p = {key: empirical_p_value(row["statistic"], nulls[key], "two_sided_abs") for key, row in candidate_by_key.items()}
    survivors = {key for key, value in screen_p.items() if value <= screen_p_max}
    for iteration in range(screen_permutations, final_permutations):
        if not survivors:
            break
        permuted, fraction = permute_within_blocks(y, blocks, np.random.default_rng(derive_seed(run_seed, "L5", iteration)))
        participation.append(fraction)
        for key in sorted(survivors):
            row = candidate_by_key[key]
            left_r, _ = _correlation(row["x"], permuted, membership[row["context_a"]])
            right_r, _ = _correlation(row["x"], permuted, membership[row["context_b"]])
            nulls[key].append(_fisher_difference(left_r, right_r) if math.isfinite(left_r) and math.isfinite(right_r) else math.nan)
    records: list[TestRecord] = []
    for key, row in sorted(candidate_by_key.items()):
        final = key in survivors
        records.append(TestRecord(
            candidate_key=key,
            test_id=stable_id("TEST", {"lens": "L5", "candidate": key, "question": "correlation_sign_conflict"}),
            family_key="L5|correlation_sign_conflict",
            statistic=float(row["statistic"]),
            alternative="two_sided_abs",
            p_value=empirical_p_value(row["statistic"], nulls[key], "two_sided_abs") if final else 1.0,
            null_iterations=final_permutations if final else screen_permutations,
            participation=float(np.mean(participation)) if participation else 0.0,
            status="final" if final else "screened_out",
        ))
    adjusted = benjamini_hochberg(records)
    evidence_rows: list[dict[str, Any]] = []
    test_rows: list[dict[str, Any]] = []
    score_rows: list[dict[str, Any]] = []
    provisional: list[dict[str, Any]] = []
    for record, adjusted_record in zip(records, adjusted, strict=True):
        row = candidate_by_key[record.candidate_key]
        evidence_id = stable_id("L5", {"candidate": record.candidate_key, "endpoint": endpoint_id})
        evidence_rows.append({
            "row_id": evidence_id, "candidate_key": record.candidate_key, "axis_id": row["axis_id"],
            "context_a": row["context_a"], "context_b": row["context_b"], "feature_id": row["feature_id"],
            "r_a": row["r_a"], "r_b": row["r_b"], "global_r": row["global_r"],
            "n_a": row["n_a"], "n_b": row["n_b"], "shared_n": row["shared_n"],
            "fisher_z_difference": row["statistic"],
        })
        test_rows.append({
            "row_id": stable_id("ROW", {"test_id": record.test_id}), "evidence_row_id": evidence_id,
            "candidate_key": record.candidate_key, "test_id": record.test_id, "family_key": record.family_key,
            "question": "correlation_sign_conflict", "statistic": record.statistic,
            "screen_p_value": screen_p[record.candidate_key], "p_value": record.p_value,
            "q_value": adjusted_record.q_value, "null_iterations": record.null_iterations, "status": record.status,
        })
        if record.status != "final" or adjusted_record.q_value is None or adjusted_record.q_value > report_q_max:
            continue
        involved = sorted(set(compound_ids[index] for index in np.concatenate((membership[row["context_a"]], membership[row["context_b"]]))))
        test = {
            "test_id": record.test_id, "question": "correlation_sign_conflict", "method": "murcko_block_permutation_fisher_z",
            "statistic": float(record.statistic), "p_value": float(record.p_value), "q_value": float(adjusted_record.q_value),
            "null_iterations": int(record.null_iterations),
        }
        subject = f"{row['feature_id']}|{row['context_a']}|{row['context_b']}"
        finding = base_finding(
            lens="L5", endpoint_id=endpoint_id, subject_type="feature", subject_id=subject,
            condition_id=f"{row['context_a']}|{row['context_b']}", effect_direction="mixed",
            effect_size=float(row["statistic"]), effect_unit="fisher_z_difference",
            support_n=int(row["n_a"] + row["n_b"] - row["shared_n"]), tests=[test],
            falsification_type="murcko_block_permutation",
            falsification_parameters={"membership_fixed": True, "axis_id": row["axis_id"]},
            falsification_rule=f"BH q <= {report_q_max} with opposite correlation signs",
            entities={"context_ids": [row["context_a"], row["context_b"]], "feature_ids": [row["feature_id"]], "compound_ids": involved},
            citations=[{"citation_id": stable_id("CIT", {"row_id": evidence_id}), "table_ref": f"l5_evidence.csv#row_id={evidence_id}"}],
        )
        provisional.append(finding)
        for context_id, role, sign in ((row["context_a"], "a", 1.0), (row["context_b"], "b", -1.0)):
            for index in membership[context_id]:
                if np.isfinite(row["x"][index]):
                    score_rows.append({
                        "finding_key": finding["finding_key"], "row_id": stable_id("SCOREROW", {"finding": finding["finding_key"], "context": context_id, "compound": compound_ids[index]}),
                        "block_id": blocks[index], "effect": float(sign * row["x"][index] * y[index]),
                        "compound_id": compound_ids[index], "context_id":context_id, "target_id":row["feature_id"], "context_role":role, "feature_value":float(row["x"][index]), "endpoint_value": float(y[index]), "actionability_level": "direction_only",
                    })
    observed_count = len(candidates)
    null_mean = float(np.mean(calibration_counts)) if calibration_counts else 0.0
    enrichment = float(observed_count / null_mean) if null_mean > 0 else None
    calibration = {"iterations": calibration_permutations, "observed": observed_count, "null_mean": null_mean, "enrichment": enrichment, "acceptance_gt_1_5": enrichment is not None and enrichment > 1.5}
    metrics = {
        "universe_count": len(universe), "screen_candidate_count": len(candidates), "final_candidate_count": len(survivors),
        "finding_count": len(provisional), "participation_rate": float(np.mean(participation)) if participation else 0.0,
    }
    return L5Result(pd.DataFrame(evidence_rows), pd.DataFrame(test_rows), pd.DataFrame(score_rows), assign_finding_ids(provisional), calibration, metrics)
