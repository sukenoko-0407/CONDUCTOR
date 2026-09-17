"""Production series-internal L2b permutation tests."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd

from conductor_stat_core import (
    TestRecord,
    benjamini_hochberg,
    derive_seed,
    empirical_p_value,
    stable_id,
)


SUPPORTED_CLASSES = ("terminal_substitution", "ring_system_replacement")


@dataclass(frozen=True)
class _Observation:
    series_key: str
    transform_class: str
    fragment_id: str
    fragment_smiles: str
    compound_ids: tuple[str, ...]
    values: tuple[float, ...]


@dataclass(frozen=True)
class L2BResult:
    evidence: pd.DataFrame
    tests: pd.DataFrame
    score_observations: pd.DataFrame
    findings: tuple[dict[str, Any], ...]
    calibration: dict[str, Any]
    metrics: dict[str, Any]


def _endpoint_values(endpoints: pd.DataFrame, endpoint_id: str) -> dict[str, float]:
    required = {"compound_id", "endpoint_id", "oriented_value"}
    missing = required - set(endpoints.columns)
    if missing:
        raise ValueError(f"Endpoint table is missing columns: {sorted(missing)}")
    selected = endpoints.loc[endpoints["endpoint_id"].astype(str).eq(endpoint_id)].copy()
    selected["oriented_value"] = pd.to_numeric(selected["oriented_value"], errors="coerce")
    selected = selected.loc[np.isfinite(selected["oriented_value"])]
    if selected["compound_id"].astype(str).duplicated().any():
        raise ValueError("Endpoint table contains duplicate compound_id/endpoint_id rows")
    return dict(zip(selected["compound_id"].astype(str), selected["oriented_value"].astype(float), strict=True))


def _prepare_series(
    observations: pd.DataFrame,
    endpoint_values: dict[str, float],
) -> dict[str, list[_Observation]]:
    required = {
        "series_key",
        "transform_class",
        "fragment_id",
        "fragment_smiles",
        "compound_ids_json",
    }
    missing = required - set(observations.columns)
    if missing:
        raise ValueError(f"Fragment observations are missing columns: {sorted(missing)}")
    grouped: dict[str, list[_Observation]] = defaultdict(list)
    series_class: dict[str, str] = {}
    for row in observations.sort_values(["series_key", "fragment_id"]).itertuples(index=False):
        transform_class = str(row.transform_class)
        if transform_class not in SUPPORTED_CLASSES:
            continue
        series_key = str(row.series_key)
        previous = series_class.setdefault(series_key, transform_class)
        if previous != transform_class:
            raise ValueError(f"Series mixes transform classes: {series_key}")
        raw_ids = json.loads(str(row.compound_ids_json))
        if not isinstance(raw_ids, list) or not all(isinstance(value, str) for value in raw_ids):
            raise ValueError(f"Invalid compound_ids_json in series {series_key}")
        compound_ids = tuple(sorted(identifier for identifier in set(raw_ids) if identifier in endpoint_values))
        values = tuple(endpoint_values[identifier] for identifier in compound_ids)
        if values:
            grouped[series_key].append(
                _Observation(
                    series_key,
                    transform_class,
                    str(row.fragment_id),
                    str(row.fragment_smiles),
                    compound_ids,
                    values,
                )
            )
    result: dict[str, list[_Observation]] = {}
    for series_key, items in sorted(grouped.items()):
        by_fragment: dict[str, list[_Observation]] = defaultdict(list)
        for item in items:
            by_fragment[item.fragment_id].append(item)
        collapsed: list[_Observation] = []
        for fragment_id, duplicate_items in sorted(by_fragment.items()):
            compound_ids = tuple(sorted({identifier for item in duplicate_items for identifier in item.compound_ids}))
            values = tuple(endpoint_values[identifier] for identifier in compound_ids)
            first = duplicate_items[0]
            collapsed.append(
                _Observation(series_key, first.transform_class, fragment_id, first.fragment_smiles, compound_ids, values)
            )
        if len(collapsed) >= 2 and sum(len(item.values) for item in collapsed) >= 2:
            seen: set[str] = set()
            for item in collapsed:
                overlap = seen.intersection(item.compound_ids)
                if overlap:
                    raise ValueError(f"A compound maps to multiple fragments in series {series_key}: {sorted(overlap)}")
                seen.update(item.compound_ids)
            result[series_key] = collapsed
    return result


def _contributions(
    series: dict[str, list[_Observation]],
    *,
    run_seed: int | None = None,
    iteration: int | None = None,
) -> dict[tuple[str, str], list[tuple[str, float]]]:
    result: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
    for series_key, observations in sorted(series.items()):
        flat = np.asarray([value for observation in observations for value in observation.values], dtype=float)
        if run_seed is not None and iteration is not None:
            rng = np.random.default_rng(derive_seed(run_seed, series_key, iteration))
            flat = flat[rng.permutation(flat.size)]
        means: list[float] = []
        offset = 0
        for observation in observations:
            width = len(observation.values)
            means.append(float(np.mean(flat[offset : offset + width])))
            offset += width
        series_mean = float(np.mean(means))
        for observation, mean in zip(observations, means, strict=True):
            result[(observation.transform_class, observation.fragment_id)].append((series_key, mean - series_mean))
    return result


def _t_statistic(values: Iterable[float]) -> float:
    array = np.asarray(list(values), dtype=float)
    if array.size < 2:
        raise ValueError("Consistent-effect statistic requires at least two series")
    standard_deviation = float(np.std(array, ddof=1))
    if not math.isfinite(standard_deviation) or standard_deviation == 0.0:
        return 0.0
    return float(np.mean(array) / (standard_deviation / math.sqrt(array.size)))


def _variance_statistic(values: Iterable[float]) -> float:
    array = np.asarray(list(values), dtype=float)
    if array.size < 3:
        raise ValueError("Series-variance statistic requires at least three series")
    value = float(np.var(array, ddof=1))
    return value if math.isfinite(value) else 0.0


def _question_id(transform_class: str, fragment_id: str, question: str) -> str:
    return stable_id(
        "TEST",
        {
            "schema_version": "0.2.1",
            "lens": "L2b",
            "class": transform_class,
            "fragment_id": fragment_id,
            "question": question,
            "method": "series_block_permutation",
            "family_key": f"L2b|{transform_class}|{question}",
        },
    )


def _calibration_summary(
    observed: dict[tuple[str, str], list[tuple[str, float]]],
    screen_null: dict[tuple[str, str, str], list[float]],
    iterations: int,
    thresholds: Iterable[float],
) -> dict[str, Any]:
    result: dict[str, Any] = {"iterations": iterations, "thresholds": {}}
    for threshold in sorted(set(float(value) for value in thresholds)):
        class_rows: dict[str, Any] = {}
        combined_observed = 0
        combined_null = np.zeros(iterations, dtype=float)
        for transform_class in SUPPORTED_CLASSES:
            candidates = [
                key
                for key, residuals in observed.items()
                if key[0] == transform_class and len(residuals) >= 3
            ]
            observed_count = sum(
                abs(_t_statistic(value for _, value in observed[key])) >= threshold for key in candidates
            )
            null_counts = np.zeros(iterations, dtype=float)
            for key in candidates:
                values = screen_null[(key[0], key[1], "consistent_effect")][:iterations]
                null_counts += np.asarray([abs(value) >= threshold for value in values], dtype=float)
            null_mean = float(np.mean(null_counts)) if iterations else 0.0
            enrichment = float(observed_count / null_mean) if null_mean > 0 else None
            class_rows[transform_class] = {
                "observed": int(observed_count),
                "null_mean": null_mean,
                "enrichment": enrichment,
            }
            combined_observed += observed_count
            combined_null += null_counts
        combined_mean = float(np.mean(combined_null)) if iterations else 0.0
        combined_enrichment = float(combined_observed / combined_mean) if combined_mean > 0 else None
        result["thresholds"][str(threshold)] = {
            "observed": int(combined_observed),
            "null_mean": combined_mean,
            "enrichment": combined_enrichment,
            "by_class": class_rows,
        }
    finite = [
        row["enrichment"]
        for row in result["thresholds"].values()
        if row["enrichment"] is not None
    ]
    result["minimum_finite_enrichment"] = min(finite) if finite else None
    result["acceptance_gt_1_5"] = bool(finite and min(finite) > 1.5)
    return result


def run_l2b(
    observations: pd.DataFrame,
    endpoints: pd.DataFrame,
    endpoint_id: str,
    *,
    run_seed: int,
    screen_permutations: int = 100,
    final_permutations: int = 1000,
    screen_p_max: float = 0.05,
    report_q_max: float = 0.05,
    calibration_permutations: int = 20,
    enrichment_thresholds: Iterable[float] = (2.0, 3.0, 4.0),
) -> L2BResult:
    if not 1 <= screen_permutations <= final_permutations:
        raise ValueError("Permutation counts must satisfy 1 <= screen <= final")
    if calibration_permutations < 1 or calibration_permutations > screen_permutations:
        raise ValueError("calibration_permutations must be within the screen stage")
    endpoint_values = _endpoint_values(endpoints, endpoint_id)
    series = _prepare_series(observations, endpoint_values)
    observed = _contributions(series)
    eligible = {
        key: values
        for key, values in observed.items()
        if key[0] in SUPPORTED_CLASSES and len(values) >= 2
    }
    questions: dict[tuple[str, str, str], dict[str, Any]] = {}
    for (transform_class, fragment_id), residuals in sorted(eligible.items()):
        values = [value for _, value in residuals]
        questions[(transform_class, fragment_id, "consistent_effect")] = {
            "statistic": _t_statistic(values),
            "alternative": "two_sided_abs",
            "series_count": len(values),
        }
        if len(values) >= 3:
            questions[(transform_class, fragment_id, "series_variance")] = {
                "statistic": _variance_statistic(values),
                "alternative": "upper",
                "series_count": len(values),
            }
    null_statistics: dict[tuple[str, str, str], list[float]] = {key: [] for key in questions}
    for iteration in range(screen_permutations):
        permuted = _contributions(series, run_seed=run_seed, iteration=iteration)
        for key in questions:
            residuals = [value for _, value in permuted[(key[0], key[1])]]
            statistic = _t_statistic(residuals) if key[2] == "consistent_effect" else _variance_statistic(residuals)
            null_statistics[key].append(statistic)
    screen_p: dict[tuple[str, str, str], float] = {}
    survivors: set[tuple[str, str, str]] = set()
    for key, question in questions.items():
        if key[2] == "consistent_effect" and question["statistic"] == 0.0 and np.std([value for _, value in eligible[(key[0], key[1])]], ddof=1) == 0:
            p_value = 1.0
        else:
            p_value = empirical_p_value(question["statistic"], null_statistics[key], question["alternative"])
        screen_p[key] = p_value
        if p_value <= screen_p_max:
            survivors.add(key)
    for iteration in range(screen_permutations, final_permutations):
        if not survivors:
            break
        permuted = _contributions(series, run_seed=run_seed, iteration=iteration)
        for key in survivors:
            residuals = [value for _, value in permuted[(key[0], key[1])]]
            statistic = _t_statistic(residuals) if key[2] == "consistent_effect" else _variance_statistic(residuals)
            null_statistics[key].append(statistic)

    raw_records: list[TestRecord] = []
    test_keys: list[tuple[str, str, str]] = []
    for key, question in sorted(questions.items()):
        is_final = key in survivors
        p_value = (
            empirical_p_value(question["statistic"], null_statistics[key], question["alternative"])
            if is_final
            else 1.0
        )
        transform_class, fragment_id, question_name = key
        test_id = _question_id(transform_class, fragment_id, question_name)
        raw_records.append(
            TestRecord(
                candidate_key=f"{transform_class}|{fragment_id}|{question_name}",
                test_id=test_id,
                family_key=f"L2b|{transform_class}|{question_name}",
                statistic=float(question["statistic"]),
                alternative=question["alternative"],
                p_value=p_value,
                null_iterations=final_permutations if is_final else screen_permutations,
                participation=1.0,
                status="final" if is_final else "screened_out",
            )
        )
        test_keys.append(key)
    adjusted = benjamini_hochberg(raw_records)

    observation_lookup = {
        (str(row.transform_class), str(row.fragment_id)): row
        for row in observations.sort_values("row_id").itertuples(index=False)
        if str(row.transform_class) in SUPPORTED_CLASSES
    }
    evidence_rows: list[dict[str, Any]] = []
    evidence_by_fragment: dict[tuple[str, str], dict[str, Any]] = {}
    for key, residuals in sorted(eligible.items()):
        transform_class, fragment_id = key
        values = np.asarray([value for _, value in residuals], dtype=float)
        series_keys = sorted(series_key for series_key, _ in residuals)
        relevant = [
            observation
            for series_key in series_keys
            for observation in series[series_key]
            if observation.fragment_id == fragment_id
        ]
        compound_ids = sorted({identifier for observation in relevant for identifier in observation.compound_ids})
        fragment_smiles = relevant[0].fragment_smiles if relevant else str(observation_lookup[key].fragment_smiles)
        row_id = stable_id("L2B", {"class": transform_class, "fragment_id": fragment_id, "endpoint_id": endpoint_id})
        row = {
            "row_id": row_id,
            "transform_class": transform_class,
            "fragment_id": fragment_id,
            "fragment_smiles": fragment_smiles,
            "series_count": len(values),
            "residual_mean": float(np.mean(values)),
            "residual_sd": float(np.std(values, ddof=1)),
            "residual_variance": float(np.var(values, ddof=1)),
            "series_keys_json": json.dumps(series_keys, separators=(",", ":")),
            "compound_ids_json": json.dumps(compound_ids, separators=(",", ":")),
        }
        evidence_rows.append(row)
        evidence_by_fragment[key] = row
    evidence_columns = [
        "row_id", "transform_class", "fragment_id", "fragment_smiles", "series_count",
        "residual_mean", "residual_sd", "residual_variance", "series_keys_json", "compound_ids_json",
    ]
    evidence = pd.DataFrame(evidence_rows, columns=evidence_columns)

    test_rows: list[dict[str, Any]] = []
    significant_by_fragment: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for key, record, adjusted_record in zip(test_keys, raw_records, adjusted, strict=True):
        evidence_row = evidence_by_fragment[(key[0], key[1])]
        row = {
            "row_id": stable_id("ROW", {"test_id": record.test_id}),
            "evidence_row_id": evidence_row["row_id"],
            "fragment_id": key[1],
            "transform_class": key[0],
            "question": key[2],
            "test_id": record.test_id,
            "family_key": record.family_key,
            "statistic": record.statistic,
            "screen_p_value": screen_p[key],
            "p_value": record.p_value,
            "q_value": adjusted_record.q_value,
            "null_iterations": record.null_iterations,
            "status": record.status,
        }
        test_rows.append(row)
        if record.status == "final" and adjusted_record.q_value is not None and adjusted_record.q_value <= report_q_max:
            significant_by_fragment[(key[0], key[1])].append(row)
    tests = pd.DataFrame(test_rows)

    provisional_findings: list[dict[str, Any]] = []
    score_rows: list[dict[str, Any]] = []
    for key, selected_tests in sorted(significant_by_fragment.items()):
        evidence_row = evidence_by_fragment[key]
        questions_in_finding = sorted(row["question"] for row in selected_tests)
        finding_key = stable_id(
            "FND",
            {
                "schema_version": "0.2.1",
                "lens": "L2b",
                "endpoint_ids": [endpoint_id],
                "subject": evidence_row["fragment_id"],
                "condition": None,
                "direction": "positive" if evidence_row["residual_mean"] > 0 else "negative" if evidence_row["residual_mean"] < 0 else "mixed",
                "test_questions": questions_in_finding,
            },
        )
        compound_ids = json.loads(evidence_row["compound_ids_json"])
        consistent_selected = "consistent_effect" in questions_in_finding
        effect_size = evidence_row["residual_mean"] if consistent_selected else evidence_row["residual_variance"]
        effect_unit = "oriented_endpoint" if consistent_selected else "oriented_endpoint_variance"
        finding = {
            "finding_id": "",
            "finding_key": finding_key,
            "lens": "L2b",
            "endpoint_ids": [endpoint_id],
            "claim": {
                "subject_type": "fragment",
                "subject_id": evidence_row["fragment_id"],
                "condition_id": None,
                "condition_depth": 1,
                "effect_direction": "positive" if evidence_row["residual_mean"] > 0 else "negative" if evidence_row["residual_mean"] < 0 else "mixed",
                "effect_size": float(effect_size),
                "effect_unit": effect_unit,
                "support_n": int(evidence_row["series_count"]),
            },
            "tests": [
                {
                    "test_id": row["test_id"],
                    "question": row["question"],
                    "method": "series_block_permutation",
                    "statistic": float(row["statistic"]),
                    "p_value": float(row["p_value"]),
                    "q_value": float(row["q_value"]),
                    "null_iterations": int(row["null_iterations"]),
                }
                for row in sorted(selected_tests, key=lambda item: item["question"])
            ],
            "falsification": {
                "type": "label_permutation",
                "parameters": {"block": "series_key", "screen_permutations": screen_permutations, "final_permutations": final_permutations},
                "decision_rule": f"question-specific BH q <= {report_q_max}",
            },
            "triviality": {
                "confounders_tested": [],
                "raw_effect_size": float(effect_size),
                "adjusted_effect_size": float(effect_size),
                "verdict": "not_assessed",
            },
            "translation": {"status": "not_required"},
            "entities": {
                "context_ids": [],
                "scaffold_ids": [],
                "transformation_ids": [],
                "fragment_ids": [evidence_row["fragment_id"]],
                "compound_ids": compound_ids,
                "feature_ids": [],
            },
            "citations": [
                {
                    "citation_id": stable_id("CIT", {"row_id": evidence_row["row_id"]}),
                    "table_ref": f"l2b_evidence.csv#row_id={evidence_row['row_id']}",
                }
            ],
            "scores": {
                "statistical_strength": None,
                "robustness": None,
                "non_triviality": None,
                "actionability": None,
                "frontier_relevance": None,
                "composite": None,
                "rank": None,
            },
            "state": {"pipeline": "candidate", "deep_dive": "not_dived"},
            "labels": [],
            "merged_into": None,
            "narrative": None,
        }
        provisional_findings.append(finding)
        for series_key, residual in eligible[key]:
            matching = [item for item in series[series_key] if item.fragment_id == evidence_row["fragment_id"]]
            if not matching:
                continue
            observation = matching[0]
            score_rows.append(
                {
                    "finding_key": finding_key,
                    "row_id": stable_id("SCOREROW", {"finding": finding_key, "series": series_key}),
                    "block_id": series_key,
                    "effect": float(residual),
                    "compound_id": observation.compound_ids[0],
                    "context_id": series_key,
                    "target_id": evidence_row["fragment_id"],
                    "subject_compound_ids_json": json.dumps(list(observation.compound_ids), separators=(",", ":")),
                    "series_fragments_compound_ids_json": json.dumps([list(item.compound_ids) for item in series[series_key]], separators=(",", ":")),
                    "series_fragments_endpoint_values_json": json.dumps([list(item.values) for item in series[series_key]], separators=(",", ":")),
                    "endpoint_value": float(np.mean(observation.values)),
                    "actionability_level": "direction_only",
                }
            )
    provisional_findings.sort(key=lambda item: item["finding_key"])
    for index, finding in enumerate(provisional_findings, start=1):
        finding["finding_id"] = f"F{index:06d}"

    calibration = _calibration_summary(observed, null_statistics, calibration_permutations, enrichment_thresholds)
    total_observations = len(observations.loc[observations["transform_class"].isin(SUPPORTED_CLASSES)])
    participating_observations = sum(len(items) for items in series.values())
    metrics = {
        "series_count": len(series),
        "fragment_count": len(eligible),
        "test_count": len(tests),
        "final_candidate_count": int(tests["status"].eq("final").sum()) if not tests.empty else 0,
        "finding_count": len(provisional_findings),
        "participation_rate": participating_observations / total_observations if total_observations else 0.0,
        "calibration_acceptance": calibration["acceptance_gt_1_5"],
    }
    return L2BResult(evidence, tests, pd.DataFrame(score_rows), tuple(provisional_findings), calibration, metrics)
