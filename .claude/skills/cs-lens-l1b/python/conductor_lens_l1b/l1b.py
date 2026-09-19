"""Conditional local-flatness tests with a fixed-context Murcko block null."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
from rdkit import Chem
from rdkit.Chem.Scaffolds import MurckoScaffold

from conductor_stat_core import TestRecord, assign_finding_ids, base_finding, benjamini_hochberg, derive_seed, empirical_p_value, permute_within_blocks, stable_id


@dataclass(frozen=True)
class L1BResult:
    evidence: pd.DataFrame
    tests: pd.DataFrame
    diagnostics: pd.DataFrame
    score_observations: pd.DataFrame
    findings: tuple[dict[str, Any], ...]
    calibration: dict[str, Any]
    metrics: dict[str, Any]


def local_flatness(distance: np.ndarray, endpoint: np.ndarray, indices: np.ndarray, *, neighbor_k: int, global_variance: float) -> tuple[float, np.ndarray, np.ndarray]:
    """Return lambda, predictions, and aligned squared errors for one fixed context."""
    selected = np.asarray(indices, dtype=int)
    selected = selected[np.isfinite(endpoint[selected])]
    if selected.size <= neighbor_k or neighbor_k < 1 or global_variance <= 0 or not math.isfinite(global_variance):
        raise ValueError("Context has insufficient neighbors or non-positive global variance")
    predictions: list[float] = []
    errors: list[float] = []
    for target in selected:
        candidates = selected[selected != target]
        order = np.lexsort((candidates, distance[target, candidates]))
        neighbors = candidates[order[:neighbor_k]]
        prediction = float(np.mean(endpoint[neighbors]))
        predictions.append(prediction)
        errors.append(float((endpoint[target] - prediction) ** 2))
    mse = float(np.mean(errors))
    return float(1.0 - mse / global_variance), np.asarray(predictions), np.asarray(errors)


def _blocks(compounds: pd.DataFrame, ids: list[str]) -> list[str]:
    lookup = compounds.assign(compound_id=compounds["compound_id"].astype(str)).set_index("compound_id")
    result: list[str] = []
    for identifier in ids:
        molecule = Chem.MolFromSmiles(str(lookup.loc[identifier, "canonical_smiles"]))
        if molecule is None:
            result.append(f"INVALID:{identifier}"); continue
        scaffold = MurckoScaffold.GetScaffoldForMol(molecule)
        key = Chem.MolToSmiles(scaffold, canonical=True) if scaffold.GetNumAtoms() else ""
        result.append(key or f"ACYCLIC:{Chem.MolToSmiles(molecule, canonical=True)}")
    return result


def run_l1b(
    compounds: pd.DataFrame,
    endpoints: pd.DataFrame,
    context_catalog: pd.DataFrame,
    context_membership: pd.DataFrame,
    feature_spaces: list[dict[str, Any]],
    endpoint_id: str,
    *,
    run_seed: int,
    neighbor_k: int = 10,
    min_endpoint_n: int = 5,
    lambda_min: float = 0.50,
    screen_permutations: int = 100,
    final_permutations: int = 1000,
    screen_p_max: float = 0.05,
    report_q_max: float = 0.05,
    calibration_permutations: int = 20,
    progress_callback: Callable[[int, int], None] | None = None,
) -> L1BResult:
    if not 1 <= calibration_permutations <= screen_permutations <= final_permutations:
        raise ValueError("Permutation counts must satisfy calibration <= screen <= final")
    selected = endpoints.loc[endpoints["endpoint_id"].astype(str).eq(endpoint_id), ["compound_id", "oriented_value"]].copy()
    selected["compound_id"] = selected["compound_id"].astype(str)
    selected["oriented_value"] = pd.to_numeric(selected["oriented_value"], errors="coerce")
    selected = selected.loc[np.isfinite(selected["oriented_value"])].sort_values("compound_id")
    ids = selected["compound_id"].tolist(); y = selected["oriented_value"].to_numpy(dtype=float)
    if len(ids) <= neighbor_k:
        raise ValueError("Endpoint has fewer observations than neighbor_k + 1")
    global_variance = float(np.var(y, ddof=1))
    if not math.isfinite(global_variance) or global_variance <= 0:
        raise ValueError("Selected Endpoint has non-positive global variance")
    blocks = _blocks(compounds, ids); position = {value: index for index, value in enumerate(ids)}
    membership = {
        str(context_id): np.asarray(sorted(position[value] for value in group["compound_id"].astype(str) if value in position), dtype=int)
        for context_id, group in context_membership.groupby(context_membership["context_id"].astype(str), sort=True)
    }
    catalog = context_catalog.copy()
    if "is_representative" not in catalog: catalog["is_representative"] = True
    if "eligible" not in catalog: catalog["eligible"] = True
    if "translation_status" not in catalog: catalog["translation_status"] = "native"
    catalog = catalog.loc[catalog["is_representative"].astype(bool) & catalog["eligible"].astype(bool) & ~catalog["translation_status"].eq("untranslatable")]
    context_ids = sorted(value for value in catalog["context_id"].astype(str) if value in membership and len(membership[value]) >= max(min_endpoint_n, neighbor_k + 1))
    spaces: dict[str, tuple[np.ndarray, int]] = {}
    diagnostics: list[dict[str, Any]] = []
    for space in sorted((item for item in feature_spaces if int(item["tier"]) <= 2), key=lambda item: item["space_id"]):
        metadata = json.loads(Path(space["distance_metadata_path"]).read_text(encoding="utf-8"))
        source_ids = [str(value) for value in metadata["compound_ids"]]
        source_position = {value: index for index, value in enumerate(source_ids)}
        if any(value not in source_position for value in ids):
            raise ValueError(f"Distance artifact is missing Endpoint compounds: {space['space_id']}")
        matrix = np.load(Path(space["distance_path"]), mmap_mode="r", allow_pickle=False)
        order = [source_position[value] for value in ids]
        aligned = np.asarray(matrix[np.ix_(order, order)], dtype=float)
        if aligned.shape != (len(ids), len(ids)) or not np.allclose(aligned, aligned.T, atol=1e-6):
            raise ValueError(f"Invalid distance matrix: {space['space_id']}")
        spaces[str(space["space_id"])] = (aligned, int(space["tier"]))
        global_lambda, _, _ = local_flatness(aligned, y, np.arange(len(ids)), neighbor_k=neighbor_k, global_variance=global_variance)
        diagnostics.append({"row_id": stable_id("L1A", {"space": space["space_id"], "endpoint": endpoint_id}), "space_id": space["space_id"], "global_lambda": global_lambda, "finding_generated": False})
    universe: list[dict[str, Any]] = []
    candidates: dict[str, dict[str, Any]] = {}
    for space_id, (distance, tier) in sorted(spaces.items()):
        for context_id in context_ids:
            indices = membership[context_id]
            value, predictions, errors = local_flatness(distance, y, indices, neighbor_k=neighbor_k, global_variance=global_variance)
            row = {"space_id": space_id, "tier": tier, "context_id": context_id, "indices": indices, "lambda": value, "predictions": predictions, "errors": errors, "distance": distance}
            universe.append(row)
            if value >= lambda_min:
                key = stable_id("L1BC", {"space": space_id, "context": context_id, "endpoint": endpoint_id})
                row["candidate_key"] = key; candidates[key] = row
    nulls = {key: [] for key in candidates}; calibration_counts: list[int] = []; participation: list[float] = []
    for iteration in range(screen_permutations):
        permuted, fraction = permute_within_blocks(y, blocks, np.random.default_rng(derive_seed(run_seed, "L1b", iteration)))
        participation.append(fraction)
        if iteration < calibration_permutations:
            calibration_counts.append(sum(local_flatness(row["distance"], permuted, row["indices"], neighbor_k=neighbor_k, global_variance=global_variance)[0] >= lambda_min for row in universe))
        for key, row in candidates.items():
            nulls[key].append(local_flatness(row["distance"], permuted, row["indices"], neighbor_k=neighbor_k, global_variance=global_variance)[0])
        if progress_callback is not None:
            progress_callback(iteration + 1, final_permutations)
    screen_p = {key: empirical_p_value(row["lambda"], nulls[key], "upper") for key, row in candidates.items()}
    survivors = {key for key, value in screen_p.items() if value <= screen_p_max}
    for iteration in range(screen_permutations, final_permutations):
        if not survivors: break
        permuted, fraction = permute_within_blocks(y, blocks, np.random.default_rng(derive_seed(run_seed, "L1b", iteration)))
        participation.append(fraction)
        for key in sorted(survivors):
            row = candidates[key]
            nulls[key].append(local_flatness(row["distance"], permuted, row["indices"], neighbor_k=neighbor_k, global_variance=global_variance)[0])
        if progress_callback is not None:
            progress_callback(iteration + 1, final_permutations)
    records = [TestRecord(candidate_key=key, test_id=stable_id("TEST", {"lens": "L1b", "candidate": key}), family_key=f"L1b|{row['space_id']}|conditional_flatness", statistic=float(row["lambda"]), alternative="upper", p_value=empirical_p_value(row["lambda"], nulls[key], "upper") if key in survivors else 1.0, null_iterations=final_permutations if key in survivors else screen_permutations, participation=float(np.mean(participation)) if participation else 0.0, status="final" if key in survivors else "screened_out") for key, row in sorted(candidates.items())]
    adjusted = benjamini_hochberg(records)
    evidence_rows: list[dict[str, Any]] = []; test_rows: list[dict[str, Any]] = []; score_rows: list[dict[str, Any]] = []; provisional: list[dict[str, Any]] = []
    translation_by_context = dict(zip(catalog["context_id"].astype(str), catalog["translation_status"].astype(str), strict=True))
    for record, adjusted_record in zip(records, adjusted, strict=True):
        row = candidates[record.candidate_key]; evidence_id = stable_id("L1B", {"candidate": record.candidate_key})
        evidence_rows.append({"row_id": evidence_id, "candidate_key": record.candidate_key, "space_id": row["space_id"], "context_id": row["context_id"], "endpoint_n": len(row["indices"]), "neighbor_k": neighbor_k, "global_variance": global_variance, "lambda": row["lambda"]})
        test_rows.append({"row_id": stable_id("ROW", {"test_id": record.test_id}), "evidence_row_id": evidence_id, "candidate_key": record.candidate_key, "test_id": record.test_id, "family_key": record.family_key, "question": "conditional_flatness", "statistic": record.statistic, "screen_p_value": screen_p[record.candidate_key], "p_value": record.p_value, "q_value": adjusted_record.q_value, "null_iterations": record.null_iterations, "status": record.status})
        if record.status != "final" or adjusted_record.q_value is None or adjusted_record.q_value > report_q_max: continue
        compounds_in = [ids[index] for index in row["indices"]]
        test = {"test_id": record.test_id, "question": "conditional_flatness", "method": "fixed_context_murcko_block_permutation", "statistic": float(record.statistic), "p_value": float(record.p_value), "q_value": float(adjusted_record.q_value), "null_iterations": int(record.null_iterations)}
        finding = base_finding(lens="L1b", endpoint_id=endpoint_id, subject_type="context", subject_id=row["context_id"], condition_id=row["context_id"], effect_direction="positive", effect_size=float(row["lambda"]), effect_unit="lambda", support_n=len(row["indices"]), tests=[test], falsification_type="murcko_block_permutation", falsification_parameters={"context_fixed": True, "distance_fixed": True, "space_id": row["space_id"]}, falsification_rule=f"lambda >= {lambda_min} and BH q <= {report_q_max}", entities={"context_ids": [row["context_id"]], "feature_ids": [row["space_id"]], "compound_ids": compounds_in}, citations=[{"citation_id": stable_id("CIT", {"row_id": evidence_id}), "table_ref": f"l1b_evidence.csv#row_id={evidence_id}"}], translation_status=translation_by_context.get(row["context_id"], "native"))
        provisional.append(finding)
        for local_index, compound_index in enumerate(row["indices"]):
            neighbor_candidates=row["indices"][row["indices"]!=compound_index]
            neighbor_order=np.lexsort((neighbor_candidates,row["distance"][compound_index,neighbor_candidates]))
            ordered_neighbor_ids=[ids[index] for index in neighbor_candidates[neighbor_order]];neighbor_ids=ordered_neighbor_ids[:neighbor_k]
            score_rows.append({"finding_key": finding["finding_key"], "row_id": stable_id("SCOREROW", {"finding": finding["finding_key"], "compound": ids[compound_index]}), "block_id": blocks[compound_index], "effect": float(global_variance - row["errors"][local_index]), "compound_id": ids[compound_index], "context_id":row["context_id"], "target_id":row["space_id"], "neighbor_compound_ids_json":json.dumps(neighbor_ids,separators=(",",":")), "neighbor_order_compound_ids_json":json.dumps(ordered_neighbor_ids,separators=(",",":")), "neighbor_k":neighbor_k, "global_variance":global_variance, "endpoint_value": float(y[compound_index]), "actionability_level": "descriptive"})
    observed = len(candidates); null_mean = float(np.mean(calibration_counts)) if calibration_counts else 0.0; enrichment = float(observed / null_mean) if null_mean > 0 else None
    calibration = {"iterations": calibration_permutations, "observed": observed, "null_mean": null_mean, "enrichment": enrichment, "acceptance_1_1_to_1_8": enrichment is not None and 1.1 <= enrichment <= 1.8}
    metrics = {"universe_count": len(universe), "screen_candidate_count": len(candidates), "final_candidate_count": len(survivors), "finding_count": len(provisional), "participation_rate": float(np.mean(participation)) if participation else 0.0, "compound_count": len(ids), "space_count": len(spaces), "context_count": len(context_ids), "member_work_count": sum(len(row["indices"]) for row in universe), "max_context_members": max((len(membership[value]) for value in context_ids), default=0), "block_count": len(set(blocks))}
    return L1BResult(pd.DataFrame(evidence_rows), pd.DataFrame(test_rows), pd.DataFrame(diagnostics), pd.DataFrame(score_rows), assign_finding_ids(provisional), calibration, metrics)
