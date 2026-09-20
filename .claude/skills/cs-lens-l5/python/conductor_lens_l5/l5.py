"""L5 context-versus-axis-complement correlation sign-conflict tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from conductor_stat_core import (
    TestRecord,
    assign_finding_ids,
    base_finding,
    benjamini_hochberg,
    derive_seed,
    permute_within_blocks,
    stable_id,
)
from rdkit import Chem
from rdkit.Chem.Scaffolds import MurckoScaffold

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


def _fisher_difference_array(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    """Vectorized Fisher-z difference with the scalar implementation's clipping."""

    epsilon = np.finfo(float).eps
    return np.arctanh(np.clip(left, -1 + epsilon, 1 - epsilon)) - np.arctanh(
        np.clip(right, -1 + epsilon, 1 - epsilon)
    )


@dataclass(frozen=True)
class _CorrelationTableEngine:
    """Compute every support-by-feature correlation with matrix products.

    ``masks`` contains fixed focal and complement membership.  Feature finite
    masks and all x-only sufficient statistics are compiled once.  A
    permutation therefore changes only the three y-dependent matrix products.
    """

    masks: np.ndarray
    finite: np.ndarray
    values: np.ndarray
    counts: np.ndarray
    sum_x: np.ndarray
    sum_x2: np.ndarray

    @classmethod
    def compile(cls, masks: np.ndarray, values: np.ndarray) -> _CorrelationTableEngine:
        mask_values = np.asarray(masks, dtype=np.float64, order="C")
        feature_values = np.asarray(values, dtype=np.float64, order="C")
        finite = np.asarray(np.isfinite(feature_values), dtype=np.float64, order="C")
        zeroed = np.nan_to_num(feature_values, nan=0.0, posinf=0.0, neginf=0.0)
        counts = mask_values @ finite
        sum_x = mask_values @ zeroed
        sum_x2 = mask_values @ np.square(zeroed)
        return cls(mask_values, finite, zeroed, counts, sum_x, sum_x2)

    def correlate(self, endpoint: np.ndarray) -> np.ndarray:
        values = np.asarray(endpoint, dtype=np.float64)
        if values.ndim != 1 or values.size != self.values.shape[0]:
            raise ValueError("L5 Endpoint vector has an incompatible shape")
        weighted_finite = self.finite * values[:, None]
        sum_y = self.masks @ weighted_finite
        sum_y2 = self.masks @ (self.finite * np.square(values)[:, None])
        sum_xy = self.masks @ (self.values * values[:, None])
        numerator = self.counts * sum_xy - self.sum_x * sum_y
        denominator = np.sqrt(
            np.maximum(self.counts * self.sum_x2 - np.square(self.sum_x), 0.0)
            * np.maximum(self.counts * sum_y2 - np.square(sum_y), 0.0)
        )
        output = np.full_like(numerator, np.nan, dtype=np.float64)
        np.divide(numerator, denominator, out=output, where=denominator > 0.0)
        return output


@dataclass(frozen=True)
class _CandidateCorrelationEngine:
    """Compile fixed candidate supports for batched permutation evaluation."""

    centered_x: np.ndarray
    support: np.ndarray
    counts: np.ndarray
    norm_x: np.ndarray
    candidate_count: int

    @classmethod
    def compile(
        cls,
        masks: np.ndarray,
        values: np.ndarray,
        comparison_indices: np.ndarray,
        feature_indices: np.ndarray,
    ) -> _CandidateCorrelationEngine:
        candidate_count = int(comparison_indices.size)
        if candidate_count == 0:
            empty = np.empty((0, values.shape[0]), dtype=np.float64)
            return cls(empty, empty.copy(), np.empty(0), np.empty(0), 0)

        side_rows = np.concatenate((comparison_indices, comparison_indices + masks.shape[0] // 2))
        side_features = np.concatenate((feature_indices, feature_indices))
        selected_values = np.asarray(values[:, side_features].T, dtype=np.float64, order="C")
        support = np.asarray(
            masks[side_rows] & np.isfinite(selected_values), dtype=np.float64, order="C"
        )
        selected_values = np.nan_to_num(
            selected_values, nan=0.0, posinf=0.0, neginf=0.0
        )
        counts = support.sum(axis=1)
        means = np.divide(
            np.sum(selected_values * support, axis=1),
            counts,
            out=np.zeros_like(counts),
            where=counts > 0,
        )
        centered = np.asarray(
            (selected_values - means[:, None]) * support,
            dtype=np.float64,
            order="C",
        )
        norm_x = np.sqrt(np.sum(np.square(centered), axis=1))
        return cls(centered, support, counts, norm_x, candidate_count)

    def correlate_batch(self, endpoints: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        batch = np.asarray(endpoints, dtype=np.float64, order="F")
        if batch.ndim == 1:
            batch = batch[:, None]
        if batch.ndim != 2 or batch.shape[0] != self.centered_x.shape[1]:
            raise ValueError("L5 permutation batch has an incompatible shape")
        if self.candidate_count == 0:
            shape = (0, batch.shape[1])
            return np.empty(shape), np.empty(shape)

        numerator = self.centered_x @ batch
        sum_y = self.support @ batch
        sum_y2 = self.support @ np.square(batch)
        variance_y = np.maximum(
            sum_y2 - np.divide(
                np.square(sum_y),
                self.counts[:, None],
                out=np.zeros_like(sum_y),
                where=self.counts[:, None] > 0,
            ),
            0.0,
        )
        denominator = self.norm_x[:, None] * np.sqrt(variance_y)
        correlations = np.full_like(numerator, np.nan, dtype=np.float64)
        np.divide(
            numerator,
            denominator,
            out=correlations,
            where=denominator > 0.0,
        )
        return (
            correlations[: self.candidate_count],
            correlations[self.candidate_count :],
        )


def _permutation_batch(
    y: np.ndarray,
    blocks: list[str],
    run_seed: int,
    start: int,
    stop: int,
) -> tuple[np.ndarray, list[float]]:
    values: list[np.ndarray] = []
    participation: list[float] = []
    for iteration in range(start, stop):
        permuted, fraction = permute_within_blocks(
            y,
            blocks,
            np.random.default_rng(derive_seed(run_seed, "L5", iteration)),
        )
        values.append(permuted)
        participation.append(fraction)
    return np.column_stack(values), participation


def _update_extreme_counts(
    observed: np.ndarray,
    null_statistics: np.ndarray,
    valid_counts: np.ndarray,
    extreme_counts: np.ndarray,
) -> None:
    finite = np.isfinite(null_statistics)
    valid_counts += finite.sum(axis=1, dtype=np.int64)
    extreme_counts += (
        finite & (np.abs(null_statistics) >= np.abs(observed)[:, None])
    ).sum(axis=1, dtype=np.int64)


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
    permutation_batch_size: int = 64,
    progress_callback: Callable[[int, int], None] | None = None,
) -> L5Result:
    if not 1 <= calibration_permutations <= screen_permutations <= final_permutations:
        raise ValueError("Permutation counts must satisfy calibration <= screen <= final")
    if permutation_batch_size <= 0:
        raise ValueError("permutation_batch_size must be positive")
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
        membership[str(context_id)] = np.asarray(
            sorted(
                {
                    position[value]
                    for value in group["compound_id"].astype(str)
                    if value in position
                }
            ),
            dtype=int,
        )
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
    comparisons: list[tuple[str, str, np.ndarray]] = []
    for axis_id, context_ids in sorted(axes.items()):
        if not context_ids:
            continue
        axis_union = np.asarray(
            sorted({int(index) for context_id in context_ids for index in membership[context_id]}),
            dtype=int,
        )
        for context_id in context_ids:
            focal = membership[context_id]
            complement = np.setdiff1d(axis_union, focal, assume_unique=True)
            if np.intersect1d(focal, complement, assume_unique=True).size:
                raise ValueError(
                    "L5 focal context and axis-local complement must be disjoint"
                )
            if focal.size < min_endpoint_n or complement.size < min_endpoint_n:
                continue
            comparisons.append((axis_id, context_id, complement))
    feature_ids = sorted(features.columns)
    feature_matrix = features[feature_ids].to_numpy(dtype=np.float64)
    comparison_count = len(comparisons)
    focal_masks = np.zeros((comparison_count, len(y)), dtype=bool)
    complement_masks = np.zeros_like(focal_masks)
    for comparison_index, (_, context_id, complement_indices) in enumerate(comparisons):
        focal_masks[comparison_index, membership[context_id]] = True
        complement_masks[comparison_index, complement_indices] = True
    if np.any(focal_masks & complement_masks):
        raise ValueError("L5 focal context and axis-local complement must be disjoint")

    combined_masks = np.vstack((focal_masks, complement_masks))
    table_engine = _CorrelationTableEngine.compile(combined_masks, feature_matrix)
    observed_correlations = table_engine.correlate(y)
    left_r_table = observed_correlations[:comparison_count]
    right_r_table = observed_correlations[comparison_count:]
    left_n_table = table_engine.counts[:comparison_count].astype(np.int64)
    right_n_table = table_engine.counts[comparison_count:].astype(np.int64)
    universe_mask = (
        (left_n_table >= min_endpoint_n)
        & (right_n_table >= min_endpoint_n)
        & np.isfinite(left_r_table)
        & np.isfinite(right_r_table)
    )
    candidate_mask = (
        universe_mask
        & (np.abs(left_r_table) >= min_abs_r)
        & (np.abs(right_r_table) >= min_abs_r)
        & (left_r_table * right_r_table < 0.0)
    )
    candidate_positions = np.argwhere(candidate_mask)
    comparison_indices = candidate_positions[:, 0].astype(np.int64, copy=False)
    feature_indices = candidate_positions[:, 1].astype(np.int64, copy=False)

    global_engine = _CorrelationTableEngine.compile(
        np.ones((1, len(y)), dtype=bool), feature_matrix
    )
    global_correlations = global_engine.correlate(y)[0]
    observed_statistics = _fisher_difference_array(
        left_r_table[comparison_indices, feature_indices],
        right_r_table[comparison_indices, feature_indices],
    )
    candidate_engine = _CandidateCorrelationEngine.compile(
        combined_masks,
        feature_matrix,
        comparison_indices,
        feature_indices,
    )
    valid_counts = np.zeros(len(candidate_positions), dtype=np.int64)
    extreme_counts = np.zeros(len(candidate_positions), dtype=np.int64)
    calibration_counts: list[int] = []
    participation: list[float] = []

    # Calibration needs the complete correlation table.  Its candidate nulls
    # are reused by the screen instead of being calculated a second time.
    for iteration in range(calibration_permutations):
        batch, fractions = _permutation_batch(y, blocks, run_seed, iteration, iteration + 1)
        participation.extend(fractions)
        permuted_correlations = table_engine.correlate(batch[:, 0])
        permuted_left = permuted_correlations[:comparison_count]
        permuted_right = permuted_correlations[comparison_count:]
        calibration_counts.append(
            int(
                np.count_nonzero(
                    universe_mask
                    & np.isfinite(permuted_left)
                    & np.isfinite(permuted_right)
                    & (np.abs(permuted_left) >= min_abs_r)
                    & (np.abs(permuted_right) >= min_abs_r)
                    & (permuted_left * permuted_right < 0.0)
                )
            )
        )
        null_statistics = _fisher_difference_array(
            permuted_left[comparison_indices, feature_indices],
            permuted_right[comparison_indices, feature_indices],
        )[:, None]
        _update_extreme_counts(
            observed_statistics, null_statistics, valid_counts, extreme_counts
        )
        if progress_callback is not None:
            progress_callback(iteration + 1, final_permutations)

    # Screen and final stages use only observed candidates.  Permutations are
    # batched so BLAS can use the CPU allocation without changing RNG seeds.
    for start in range(calibration_permutations, screen_permutations, permutation_batch_size):
        stop = min(screen_permutations, start + permutation_batch_size)
        batch, fractions = _permutation_batch(y, blocks, run_seed, start, stop)
        participation.extend(fractions)
        permuted_left, permuted_right = candidate_engine.correlate_batch(batch)
        _update_extreme_counts(
            observed_statistics,
            _fisher_difference_array(permuted_left, permuted_right),
            valid_counts,
            extreme_counts,
        )
        if progress_callback is not None:
            for completed in range(start + 1, stop + 1):
                progress_callback(completed, final_permutations)

    if np.any(valid_counts == 0):
        raise ValueError("L5 produced a candidate without a finite screen null statistic")
    screen_p_values = np.divide(1.0 + extreme_counts, 1.0 + valid_counts)
    survivor_indices = np.flatnonzero(screen_p_values <= screen_p_max)
    del candidate_engine
    if survivor_indices.size:
        survivor_engine = _CandidateCorrelationEngine.compile(
            combined_masks,
            feature_matrix,
            comparison_indices[survivor_indices],
            feature_indices[survivor_indices],
        )
        for start in range(screen_permutations, final_permutations, permutation_batch_size):
            stop = min(final_permutations, start + permutation_batch_size)
            batch, fractions = _permutation_batch(y, blocks, run_seed, start, stop)
            participation.extend(fractions)
            permuted_left, permuted_right = survivor_engine.correlate_batch(batch)
            survivor_valid = valid_counts[survivor_indices].copy()
            survivor_extreme = extreme_counts[survivor_indices].copy()
            _update_extreme_counts(
                observed_statistics[survivor_indices],
                _fisher_difference_array(permuted_left, permuted_right),
                survivor_valid,
                survivor_extreme,
            )
            valid_counts[survivor_indices] = survivor_valid
            extreme_counts[survivor_indices] = survivor_extreme
            if progress_callback is not None:
                for completed in range(start + 1, stop + 1):
                    progress_callback(completed, final_permutations)

    candidate_by_key: dict[str, dict[str, Any]] = {}
    screen_p: dict[str, float] = {}
    final_p: dict[str, float] = {}
    survivors: set[str] = set()
    survivor_set = set(int(value) for value in survivor_indices)
    for candidate_index, (comparison_index, feature_index) in enumerate(
        zip(comparison_indices, feature_indices, strict=True)
    ):
        axis_id, context_id, complement_indices = comparisons[int(comparison_index)]
        left_n = int(left_n_table[comparison_index, feature_index])
        right_n = int(right_n_table[comparison_index, feature_index])
        support_n = left_n + right_n
        if support_n < 1:
            raise ValueError(
                "L5 support_n must equal the unique finite observations used by both correlations"
            )
        feature_id = feature_ids[int(feature_index)]
        row = {
            "axis_id": axis_id,
            "context_a": context_id,
            "context_b": "complement",
            "complement_indices": complement_indices,
            "feature_id": feature_id,
            "r_a": float(left_r_table[comparison_index, feature_index]),
            "r_b": float(right_r_table[comparison_index, feature_index]),
            "n_a": left_n,
            "n_b": right_n,
            "shared_n": 0,
            "support_n": support_n,
            "statistic": float(observed_statistics[candidate_index]),
            "global_r": float(global_correlations[feature_index]),
            "x": feature_matrix[:, feature_index],
        }
        key = stable_id(
            "L5C",
            {name: row[name] for name in ("axis_id", "context_a", "feature_id")},
        )
        row["candidate_key"] = key
        candidate_by_key[key] = row
        screen_p[key] = float(screen_p_values[candidate_index])
        if candidate_index in survivor_set:
            survivors.add(key)
            final_p[key] = float(
                (1.0 + extreme_counts[candidate_index])
                / (1.0 + valid_counts[candidate_index])
            )
    records: list[TestRecord] = []
    for key, row in sorted(candidate_by_key.items()):
        final = key in survivors
        records.append(TestRecord(
            candidate_key=key,
            test_id=stable_id("TEST", {"lens": "L5", "candidate": key, "question": "correlation_sign_conflict"}),
            family_key=f"L5|{row['axis_id']}|correlation_sign_conflict",
            statistic=float(row["statistic"]),
            alternative="two_sided_abs",
            p_value=final_p[key] if final else 1.0,
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
            "support_n": row["support_n"],
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
        involved = sorted(
            {
                compound_ids[index]
                for index in np.concatenate(
                    (membership[row["context_a"]], row["complement_indices"])
                )
            }
        )
        test = {
            "test_id": record.test_id, "question": "correlation_sign_conflict", "method": "murcko_block_permutation_fisher_z",
            "statistic": float(record.statistic), "p_value": float(record.p_value), "q_value": float(adjusted_record.q_value),
            "null_iterations": int(record.null_iterations),
        }
        subject = f"{row['feature_id']}|{row['context_a']}|complement"
        finding = base_finding(
            lens="L5", endpoint_id=endpoint_id, subject_type="feature", subject_id=subject,
            condition_id=f"{row['context_a']}|complement", effect_direction="mixed",
            effect_size=float(row["statistic"]), effect_unit="fisher_z_difference",
            support_n=int(row["support_n"]), tests=[test],
            falsification_type="murcko_block_permutation",
            falsification_parameters={"membership_fixed": True, "axis_id": row["axis_id"]},
            falsification_rule=f"BH q <= {report_q_max} with opposite correlation signs",
            entities={"context_ids": [row["context_a"]], "feature_ids": [row["feature_id"]], "compound_ids": involved},
            citations=[{"citation_id": stable_id("CIT", {"row_id": evidence_id}), "table_ref": f"l5_evidence.csv#row_id={evidence_id}"}],
        )
        provisional.append(finding)
        for context_id, role, sign, indices in (
            (row["context_a"], "focal", 1.0, membership[row["context_a"]]),
            ("complement", "complement", -1.0, row["complement_indices"]),
        ):
            for index in indices:
                if np.isfinite(row["x"][index]):
                    score_rows.append({
                        "finding_key": finding["finding_key"], "row_id": stable_id("SCOREROW", {"finding": finding["finding_key"], "context": context_id, "compound": compound_ids[index]}),
                        "block_id": blocks[index], "effect": float(sign * row["x"][index] * y[index]),
                        "compound_id": compound_ids[index], "context_id":context_id, "target_id":row["feature_id"], "context_role":role, "feature_value":float(row["x"][index]), "endpoint_value": float(y[index]), "actionability_level": "direction_only",
                    })
    observed_count = len(candidate_positions)
    null_mean = float(np.mean(calibration_counts)) if calibration_counts else 0.0
    enrichment = float(observed_count / null_mean) if null_mean > 0 else None
    calibration = {"iterations": calibration_permutations, "observed": observed_count, "null_mean": null_mean, "enrichment": enrichment, "acceptance_gt_1_5": enrichment is not None and enrichment > 1.5}
    metrics = {
        "universe_count": int(np.count_nonzero(universe_mask)), "screen_candidate_count": len(candidate_positions), "final_candidate_count": len(survivors),
        "finding_count": len(provisional), "participation_rate": float(np.mean(participation)) if participation else 0.0,
        "compound_count": len(compound_ids), "comparison_count": len(comparisons),
        "feature_count": len(feature_ids), "block_count": len(set(blocks)),
        "permutation_batch_size": permutation_batch_size,
        "correlation_engine": "matrix_blas_v1",
    }
    return L5Result(pd.DataFrame(evidence_rows), pd.DataFrame(test_rows), pd.DataFrame(score_rows), assign_finding_ids(provisional), calibration, metrics)
