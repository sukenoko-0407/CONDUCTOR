"""Generate one-step MMP products and score their exact Description neighborhoods."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
from rdkit import Chem
from scipy import stats

from conductor_stat_core import TestRecord, assign_finding_ids, base_finding, benjamini_hochberg, stable_id


@dataclass(frozen=True)
class L4GenerationResult:
    candidates: pd.DataFrame
    audit: pd.DataFrame


@dataclass(frozen=True)
class L4Result:
    evidence: pd.DataFrame
    tests: pd.DataFrame
    generation_audit: pd.DataFrame
    score_observations: pd.DataFrame
    findings: tuple[dict[str, Any], ...]
    metrics: dict[str, Any]


@dataclass(frozen=True)
class L4ScalePlan:
    generated_candidate_count: int
    selected_candidate_count: int
    excluded_by_cap_count: int
    description_space_count: int
    planned_description_rows: int
    planned_description_cost_units: int
    description_cost_class_rows: dict[str, int]
    candidate_cap: int
    max_candidate_description_rows: int
    max_candidate_description_cost_units: int


DESCRIPTION_COST_WEIGHTS = {
    "low": 1,
    "medium": 4,
    "high": 16,
    "very_high": 64,
}


class L4ScaleGuardError(ValueError):
    def __init__(self, plan: L4ScalePlan):
        self.plan = plan
        reasons: list[str] = []
        if plan.planned_description_rows > plan.max_candidate_description_rows:
            reasons.append(
                "rows "
                f"{plan.planned_description_rows}>{plan.max_candidate_description_rows}"
            )
        if (
            plan.planned_description_cost_units
            > plan.max_candidate_description_cost_units
        ):
            reasons.append(
                "cost_units "
                f"{plan.planned_description_cost_units}>"
                f"{plan.max_candidate_description_cost_units}"
            )
        super().__init__("L4_SCALE_GUARD: " + ", ".join(reasons))


def _read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, dtype={"compound_id": "string"})


def assemble_fragments(constant_key: str, variable_smiles: str) -> str:
    """Reconnect matching isotope-labelled dummy atoms and return sanitized canonical SMILES."""
    smiles = [value.strip() for value in str(constant_key).split(" | ") if value.strip()] + [str(variable_smiles)]
    molecules = [Chem.MolFromSmiles(value) for value in smiles]
    if any(value is None for value in molecules):
        raise ValueError("fragment_parse_failed")
    combined = molecules[0]
    for molecule in molecules[1:]:
        combined = Chem.CombineMols(combined, molecule)
    dummy_groups: dict[int, list[tuple[int, int, Chem.BondType]]] = {}
    for atom in combined.GetAtoms():
        if atom.GetAtomicNum() != 0:
            continue
        neighbors = list(atom.GetNeighbors())
        if len(neighbors) != 1:
            raise ValueError("invalid_dummy_degree")
        bond = combined.GetBondBetweenAtoms(atom.GetIdx(), neighbors[0].GetIdx())
        dummy_groups.setdefault(atom.GetIsotope(), []).append((atom.GetIdx(), neighbors[0].GetIdx(), bond.GetBondType()))
    if not dummy_groups or any(len(values) != 2 for values in dummy_groups.values()):
        raise ValueError("attachment_labels_do_not_pair")
    editable = Chem.RWMol(combined)
    for label, values in sorted(dummy_groups.items()):
        left, right = values
        if left[2] != right[2] and Chem.BondType.SINGLE not in (left[2], right[2]):
            raise ValueError(f"attachment_bond_mismatch:{label}")
        bond_type = right[2] if right[2] != Chem.BondType.UNSPECIFIED else left[2]
        editable.AddBond(left[1], right[1], bond_type)
    for index in sorted((item[0] for values in dummy_groups.values() for item in values), reverse=True):
        editable.RemoveAtom(index)
    molecule = editable.GetMol()
    Chem.SanitizeMol(molecule)
    if any(atom.GetAtomicNum() == 0 for atom in molecule.GetAtoms()):
        raise ValueError("unresolved_dummy_atom")
    return Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True)


def generate_l4_candidates(
    compounds: pd.DataFrame,
    fragmentations: pd.DataFrame,
    transformations: pd.DataFrame,
) -> L4GenerationResult:
    """Apply every observed transformation in both directions to matching sources."""
    existing = set(compounds["canonical_smiles"].astype(str))
    accepted = fragmentations.loc[fragmentations["status"].astype(str).eq("accepted")]
    by_variable: dict[tuple[str, str], list[pd.Series]] = {}
    for _, row in accepted.iterrows():
        by_variable.setdefault((str(row["class"]), str(row["variable_smiles"])), []).append(row)

    pair_support = {
        str(row["transformation_id"]): int(row["pair_count"])
        for _, row in transformations.iterrows()
    }
    generated: dict[str, dict[str, Any]] = {}
    audit: list[dict[str, Any]] = []
    for _, transformation in transformations.sort_values("transformation_id").iterrows():
        transformation_id = str(transformation["transformation_id"])
        transform_class = str(transformation["class"])
        directions = (
            (str(transformation["variable_from"]), str(transformation["variable_to"])),
            (str(transformation["variable_to"]), str(transformation["variable_from"])),
        )
        for source_variable, target_variable in directions:
            for source in by_variable.get((transform_class, source_variable), []):
                source_id = str(source["compound_id"])
                audit_id = stable_id("L4GEN", {"transformation": transformation_id, "source": source_id, "target_variable": target_variable})
                try:
                    candidate_smiles = assemble_fragments(str(source["constant_key"]), target_variable)
                    if candidate_smiles in existing:
                        raise ValueError("already_observed")
                    candidate_id = stable_id("REGION", {"smiles": candidate_smiles})
                    current = generated.setdefault(
                        candidate_id,
                        {"compound_id": candidate_id, "canonical_smiles": candidate_smiles, "source_compound_ids": set(), "transformation_ids": set(), "paths": set()},
                    )
                    current["source_compound_ids"].add(source_id)
                    current["transformation_ids"].add(transformation_id)
                    current["paths"].add((source_id, transformation_id))
                    status, reason = "accepted", ""
                except Exception as exc:
                    candidate_id, candidate_smiles, status, reason = "", "", "excluded", str(exc)
                audit.append({"row_id": audit_id, "source_compound_id": source_id, "transformation_id": transformation_id, "candidate_id": candidate_id, "candidate_smiles": candidate_smiles, "status": status, "reason": reason})
    candidates = pd.DataFrame(
        [
            {
                "compound_id": candidate_id,
                "canonical_smiles": item["canonical_smiles"],
                "source_compound_ids_json": json.dumps(sorted(item["source_compound_ids"]), separators=(",", ":")),
                "transformation_ids_json": json.dumps(sorted(item["transformation_ids"]), separators=(",", ":")),
                "paths_json": json.dumps(sorted([list(value) for value in item["paths"]]), separators=(",", ":")),
                "reachability_path_count": len(item["paths"]),
                "source_compound_count": len(item["source_compound_ids"]),
                "transformation_pair_support": sum(
                    pair_support.get(value, 0) for value in item["transformation_ids"]
                ),
            }
            for candidate_id, item in sorted(generated.items())
        ],
        columns=[
            "compound_id", "canonical_smiles", "source_compound_ids_json",
            "transformation_ids_json", "paths_json", "reachability_path_count",
            "source_compound_count", "transformation_pair_support",
        ],
    )
    return L4GenerationResult(candidates, pd.DataFrame(audit))


def select_l4_candidates(
    generation: L4GenerationResult,
    *,
    candidate_cap: int,
    description_space_count: int,
    max_candidate_description_rows: int,
    description_cost_classes: list[str] | None = None,
    max_candidate_description_cost_units: int | None = None,
) -> tuple[L4GenerationResult, L4ScalePlan]:
    """Apply the deterministic pre-description L4 scale contract."""

    if candidate_cap < 1:
        raise ValueError("lenses.l4.candidate_cap must be >= 1")
    if description_space_count < 1:
        raise ValueError("L4 requires at least one Tier 1/2 Description space")
    if max_candidate_description_rows < 1:
        raise ValueError("lenses.l4.max_candidate_description_rows must be >= 1")
    cost_classes = (
        ["low"] * description_space_count
        if description_cost_classes is None
        else list(description_cost_classes)
    )
    if len(cost_classes) != description_space_count:
        raise ValueError(
            "description_cost_classes must have one entry per Tier 1/2 space"
        )
    unknown_cost_classes = sorted(set(cost_classes) - set(DESCRIPTION_COST_WEIGHTS))
    if unknown_cost_classes:
        raise ValueError(
            f"Unsupported Description cost classes: {unknown_cost_classes}"
        )
    maximum_cost = (
        max_candidate_description_rows
        if max_candidate_description_cost_units is None
        else int(max_candidate_description_cost_units)
    )
    if maximum_cost < 1:
        raise ValueError(
            "lenses.l4.max_candidate_description_cost_units must be >= 1"
        )
    generated_count = len(generation.candidates)
    ranked = generation.candidates.sort_values(
        [
            "reachability_path_count",
            "transformation_pair_support",
            "source_compound_count",
            "compound_id",
        ],
        ascending=[False, False, False, True],
        kind="mergesort",
    )
    selected = ranked.head(candidate_cap).reset_index(drop=True)
    planned_rows = len(selected) * description_space_count
    cost_class_rows = {
        cost_class: len(selected) * cost_classes.count(cost_class)
        for cost_class in sorted(set(cost_classes))
    }
    planned_cost_units = len(selected) * sum(
        DESCRIPTION_COST_WEIGHTS[cost_class] for cost_class in cost_classes
    )
    plan = L4ScalePlan(
        generated_candidate_count=generated_count,
        selected_candidate_count=len(selected),
        excluded_by_cap_count=max(0, generated_count - len(selected)),
        description_space_count=description_space_count,
        planned_description_rows=planned_rows,
        planned_description_cost_units=planned_cost_units,
        description_cost_class_rows=cost_class_rows,
        candidate_cap=candidate_cap,
        max_candidate_description_rows=max_candidate_description_rows,
        max_candidate_description_cost_units=maximum_cost,
    )
    if (
        planned_rows > max_candidate_description_rows
        or planned_cost_units > maximum_cost
    ):
        raise L4ScaleGuardError(plan)
    excluded = ranked.iloc[len(selected):]
    audit = generation.audit.copy()
    if not excluded.empty:
        cap_rows = excluded.loc[:, ["compound_id", "canonical_smiles"]].rename(
            columns={
                "compound_id": "candidate_id",
                "canonical_smiles": "candidate_smiles",
            }
        ).copy()
        cap_rows.insert(
            0,
            "row_id",
            [
                stable_id("L4CAP", {"candidate": str(candidate_id)})
                for candidate_id in cap_rows["candidate_id"]
            ],
        )
        cap_rows["source_compound_id"] = ""
        cap_rows["transformation_id"] = ""
        cap_rows["status"] = "excluded"
        cap_rows["reason"] = "scale_cap"
        cap_rows = cap_rows.loc[:, [
            "row_id", "source_compound_id", "transformation_id", "candidate_id",
            "candidate_smiles", "status", "reason",
        ]]
        audit = pd.concat([audit, cap_rows], ignore_index=True)
    return L4GenerationResult(selected, audit), plan


def candidate_distance_matrix(space: dict[str, Any], candidate_ids: list[str]) -> tuple[list[str], np.ndarray]:
    """Return candidate-to-observed distances using Phase 1 fitted representation rules."""
    required = {"path", "candidate_path", "distance_metadata_path", "metric", "space_id"}
    missing = required - set(space)
    if missing:
        raise ValueError(f"L4 feature space is missing fields {sorted(missing)}: {space.get('space_id')}")
    metadata = json.loads(Path(space["distance_metadata_path"]).read_text(encoding="utf-8"))
    all_observed_ids = [str(value) for value in metadata["compound_ids"]]
    eligible_ids = {
        str(value)
        for value in metadata.get("eligible_compound_ids", all_observed_ids)
    }
    if not eligible_ids.issubset(set(all_observed_ids)):
        raise ValueError(
            f"Distance eligibility contains unknown compounds: {space['space_id']}"
        )
    observed_ids = [
        value for value in all_observed_ids if value in eligible_ids
    ]
    columns = [str(value) for value in metadata["feature_columns"]]
    observed = _read_table(Path(space["path"])).assign(compound_id=lambda frame: frame["compound_id"].astype(str)).set_index("compound_id")
    candidates = _read_table(Path(space["candidate_path"])).assign(compound_id=lambda frame: frame["compound_id"].astype(str)).set_index("compound_id")
    if observed.index.duplicated().any() or candidates.index.duplicated().any():
        raise ValueError(f"Feature payload requires unique compound_id: {space['space_id']}")
    if set(observed_ids) - set(observed.index):
        raise ValueError(f"Observed payload is missing distance-metadata compounds: {space['space_id']}")
    if set(candidate_ids) - set(candidates.index):
        raise ValueError(f"Candidate payload is incomplete: {space['space_id']}")
    if set(columns) - set(observed.columns) or set(columns) - set(candidates.columns):
        raise ValueError(f"Candidate and observed feature columns differ: {space['space_id']}")
    left = observed.loc[observed_ids, columns].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float, copy=True)
    right = candidates.loc[candidate_ids, columns].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float, copy=True)
    if str(space["metric"]) == "tanimoto":
        left = np.nan_to_num(left, nan=0.0, posinf=0.0, neginf=0.0)
        right = np.nan_to_num(right, nan=0.0, posinf=0.0, neginf=0.0)
        dot = right @ left.T
        denominator = np.einsum("ij,ij->i", right, right)[:, None] + np.einsum("ij,ij->i", left, left)[None, :] - dot
        similarity = np.divide(dot, denominator, out=np.zeros_like(dot), where=denominator > 0)
        distance = 1.0 - similarity
    elif str(space["metric"]) == "euclidean":
        medians = np.nanmedian(left, axis=0)
        if not np.isfinite(medians).all():
            raise ValueError(f"Observed feature has no finite calibration values: {space['space_id']}")
        left_missing = np.where(~np.isfinite(left)); left[left_missing] = medians[left_missing[1]]
        right_missing = np.where(~np.isfinite(right)); right[right_missing] = medians[right_missing[1]]
        means = np.mean(left, axis=0); standard = np.std(left, axis=0, ddof=0); keep = standard > 0
        if not bool(keep.any()):
            raise ValueError(f"All calibrated features are constant: {space['space_id']}")
        normalized_left = (left[:, keep] - means[keep]) / standard[keep]
        normalized_right = (right[:, keep] - means[keep]) / standard[keep]
        distance = np.sqrt(np.sum((normalized_right[:, None, :] - normalized_left[None, :, :]) ** 2, axis=2))
    else:
        raise ValueError(f"Unsupported L4 metric: {space['metric']}")
    if not np.isfinite(distance).all():
        raise ValueError(f"Non-finite candidate distance: {space['space_id']}")
    return observed_ids, np.asarray(distance, dtype=float)


def score_l4_candidates(
    endpoints: pd.DataFrame,
    generation: L4GenerationResult,
    feature_spaces: list[dict[str, Any]],
    endpoint_id: str,
    *,
    neighbor_k: int = 10,
    min_context_size: int = 5,
    report_q_max: float = 0.05,
    progress_callback: Callable[[int, int], None] | None = None,
) -> L4Result:
    selected = endpoints.loc[endpoints["endpoint_id"].astype(str).eq(endpoint_id), ["compound_id", "oriented_value"]].copy()
    selected["compound_id"] = selected["compound_id"].astype(str)
    selected["oriented_value"] = pd.to_numeric(selected["oriented_value"], errors="coerce")
    selected = selected.loc[np.isfinite(selected["oriented_value"])]
    endpoint_values = dict(zip(selected["compound_id"], selected["oriented_value"].astype(float), strict=True))
    if not endpoint_values:
        raise ValueError("L4 requires finite selected Endpoint values")
    candidate_ids = generation.candidates["compound_id"].astype(str).tolist()
    if not candidate_ids:
        empty = pd.DataFrame()
        metrics = {
            "attempt_count": int(
                generation.audit.get("reason", pd.Series(dtype=str))
                .astype(str).ne("scale_cap").sum()
            ),
            "accepted_unique_candidate_count": 0,
            "tested_candidate_count": 0,
            "finding_count": 0,
            "generation_failure_count": int(
                (
                    generation.audit["status"].eq("excluded")
                    & generation.audit.get("reason", pd.Series("", index=generation.audit.index)).astype(str).ne("scale_cap")
                ).sum()
            ) if not generation.audit.empty else 0,
            "candidate_distance_mode": "exact_description_cross_distance",
        }
        return L4Result(empty, empty, generation.audit, empty, (), metrics)
    global_median = float(np.median(list(endpoint_values.values())))
    spaces = []
    for space in sorted((item for item in feature_spaces if int(item["tier"]) <= 2), key=lambda item: item["space_id"]):
        observed_ids, distances = candidate_distance_matrix(space, candidate_ids)
        spaces.append((str(space["space_id"]), observed_ids, distances))
    if not spaces:
        raise ValueError("L4 requires at least one Tier 1/2 candidate feature space")

    evidence_rows: list[dict[str, Any]] = []
    candidate_records: list[TestRecord] = []
    score_material: dict[str, list[dict[str, Any]]] = {}
    material_by_candidate: dict[str, dict[str, Any]] = {}
    for candidate_index, candidate in generation.candidates.iterrows():
        candidate_id = str(candidate["compound_id"])
        space_rows = []
        for space_id, observed_ids, distances in spaces:
            eligible = np.asarray([index for index, value in enumerate(observed_ids) if value in endpoint_values], dtype=int)
            if len(eligible) < neighbor_k:
                continue
            values_for_candidate = distances[candidate_index, eligible]
            lexical = np.asarray([observed_ids[index] for index in eligible], dtype=str)
            order = np.lexsort((lexical, values_for_candidate))
            neighbors = eligible[order[:neighbor_k]]
            neighbor_ids = [observed_ids[index] for index in neighbors]
            values = np.asarray([endpoint_values[value] for value in neighbor_ids], dtype=float)
            standard_error = float(np.std(values, ddof=1) / math.sqrt(len(values)))
            lower = float(np.mean(values) - stats.t.ppf(0.95, len(values) - 1) * standard_error)
            nearest = float(distances[candidate_index, neighbors[0]])
            region_n = int(np.count_nonzero(values_for_candidate <= nearest + 1e-12))
            gap = float(1.0 - min(region_n / min_context_size, 1.0))
            standard = float(np.std(values, ddof=1))
            p_value = float(stats.ttest_1samp(values, global_median, alternative="greater").pvalue) if standard > 0 else (0.0 if float(np.mean(values)) > global_median else 1.0)
            space_rows.append({"space_id": space_id, "neighbor_ids": neighbor_ids, "values": values, "lower": lower, "region_n": region_n, "gap": gap, "p": p_value})
        if not space_rows:
            continue
        conservative = min(space_rows, key=lambda row: (row["lower"], row["space_id"]))
        density_gap = min(row["gap"] for row in space_rows)
        score = float(conservative["lower"] * density_gap)
        p_value = max(row["p"] for row in space_rows)
        evidence_id = stable_id("L4", {"candidate": candidate_id, "endpoint": endpoint_id})
        sources = json.loads(str(candidate["source_compound_ids_json"])); transformations = json.loads(str(candidate["transformation_ids_json"]))
        evidence_rows.append({"row_id": evidence_id, "candidate_id": candidate_id, "candidate_smiles": candidate["canonical_smiles"], "source_compound_ids_json": candidate["source_compound_ids_json"], "transformation_ids_json": candidate["transformation_ids_json"], "space_count": len(space_rows), "neighbor_k": neighbor_k, "lower_confidence_limit": conservative["lower"], "density_gap": density_gap, "reachability": 1.0, "region_score": score, "conservative_p_value": p_value, "region_definition": "one_step_product_exact_candidate_description_knn"})
        key = stable_id("L4C", {"candidate": candidate_id, "endpoint": endpoint_id})
        candidate_records.append(
            TestRecord(
                candidate_key=key,
                test_id=stable_id("TEST", {"lens": "L4", "candidate": candidate_id}),
                family_key="L4|reachable_region",
                statistic=score,
                alternative="upper",
                p_value=min(max(p_value, 0.0), 1.0),
                null_iterations=0,
                participation=1.0,
                status="final",
            )
        )
        score_material[key] = space_rows
        material_by_candidate[key] = {"candidate_id": candidate_id, "sources": sources, "transformations": transformations, "evidence_id": evidence_id}
        if progress_callback is not None:
            progress_callback(candidate_index + 1, len(generation.candidates))

    adjusted = benjamini_hochberg(candidate_records)
    test_rows: list[dict[str, Any]] = []; score_rows: list[dict[str, Any]] = []; provisional: list[dict[str, Any]] = []
    for record, adjusted_record in zip(candidate_records, adjusted, strict=True):
        item = material_by_candidate[record.candidate_key]
        test_rows.append({"row_id": stable_id("ROW", {"test_id": record.test_id}), "evidence_row_id": item["evidence_id"], "candidate_key": record.candidate_key, "test_id": record.test_id, "family_key": record.family_key, "question": "reachable_promising_region", "statistic": record.statistic, "p_value": record.p_value, "q_value": adjusted_record.q_value, "null_iterations": 0, "status": "final"})
        if adjusted_record.q_value is None or adjusted_record.q_value > report_q_max:
            continue
        test = {"test_id": record.test_id, "question": "reachable_promising_region", "method": "exact_candidate_description_neighbor_lower_bound", "statistic": float(record.statistic), "p_value": float(record.p_value), "q_value": float(adjusted_record.q_value), "null_iterations": 0}
        finding = base_finding(lens="L4", endpoint_id=endpoint_id, subject_type="region", subject_id=item["candidate_id"], condition_id=None, effect_direction="positive", effect_size=float(record.statistic), effect_unit="lcb_density_reachability_product", support_n=neighbor_k, tests=[test], falsification_type="product_validation", falsification_parameters={"one_step": True, "sanitize_required": True, "unobserved_required": True, "candidate_descriptions_recomputed": True}, falsification_rule="reject if product is invalid, observed, or lacks exact Tier 1/2 candidate descriptions", entities={"transformation_ids": item["transformations"], "compound_ids": item["sources"]}, citations=[{"citation_id": stable_id("CIT", {"row_id": item["evidence_id"]}), "table_ref": f"l4_evidence.csv#row_id={item['evidence_id']}"}], labels=["reachable_unexplored_region"])
        provisional.append(finding)
        for space_row in score_material[record.candidate_key]:
            for neighbor_id, value in zip(space_row["neighbor_ids"], space_row["values"], strict=True):
                score_rows.append({"finding_key": finding["finding_key"], "row_id": stable_id("SCOREROW", {"finding": finding["finding_key"], "space": space_row["space_id"], "compound": neighbor_id}), "block_id": space_row["space_id"], "effect": float(value - global_median), "compound_id": neighbor_id, "context_id":"", "target_id":item["candidate_id"], "endpoint_value": float(value), "actionability_level": "exact", "candidate_id": item["candidate_id"], "region_score":float(record.statistic), "density_gap":density_gap, "global_median":global_median, "neighbor_k":neighbor_k})
    non_cap_audit = generation.audit.loc[
        generation.audit.get("reason", pd.Series("", index=generation.audit.index))
        .astype(str).ne("scale_cap")
    ]
    metrics = {"attempt_count": len(non_cap_audit), "accepted_unique_candidate_count": len(generation.candidates), "tested_candidate_count": len(candidate_records), "finding_count": len(provisional), "generation_failure_count": int(non_cap_audit["status"].eq("excluded").sum()) if not non_cap_audit.empty else 0, "candidate_distance_mode": "exact_description_cross_distance"}
    return L4Result(pd.DataFrame(evidence_rows), pd.DataFrame(test_rows), generation.audit, pd.DataFrame(score_rows), assign_finding_ids(provisional), metrics)


def run_l4(
    compounds: pd.DataFrame,
    endpoints: pd.DataFrame,
    fragmentations: pd.DataFrame,
    transformations: pd.DataFrame,
    feature_spaces: list[dict[str, Any]],
    endpoint_id: str,
    *,
    neighbor_k: int = 10,
    min_context_size: int = 5,
    report_q_max: float = 0.05,
) -> L4Result:
    """Convenience wrapper for callers that already supplied candidate feature payloads."""
    generation = generate_l4_candidates(compounds, fragmentations, transformations)
    return score_l4_candidates(endpoints, generation, feature_spaces, endpoint_id, neighbor_k=neighbor_k, min_context_size=min_context_size, report_q_max=report_q_max)
