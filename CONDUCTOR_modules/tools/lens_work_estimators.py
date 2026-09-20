"""Read-only R1 work estimators for the production Lens runners."""

from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from work_contract import WorkEstimate


RATES = {
    "l5": 3_650_000,
    "l1b": 29_800_000,
    "l2a": 7_230_000,
    "l4": 31_700,
    "l2b": 50_858,
    "l7": 6_004,
}
SAFETY_FACTOR = 1.25


def _input(request: dict[str, Any], role: str) -> Path:
    values = [
        Path(item["path"]).resolve()
        for item in request["inputs"]
        if item["role"] == role
    ]
    if len(values) != 1:
        raise ValueError(f"Exactly one {role!r} input is required")
    return values[0]


def _read_csv(path: Path, *, ids: bool = False) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"compound_id": "string"} if ids else None)


def _family_census(tests: pd.DataFrame) -> dict[str, Any]:
    if tests.empty or "family_key" not in tests:
        return {
            "family_count": 0,
            "test_count": 0,
            "max_family_key": None,
            "family_sizes": {},
        }
    sizes = tests.groupby("family_key", sort=True).size().astype(int)
    maximum = int(sizes.max())
    # Stable lexical tie break makes the audit reproducible.
    maximum_key = str(sorted(sizes.loc[sizes.eq(maximum)].index.astype(str))[0])
    return {
        "family_count": int(len(sizes)),
        "test_count": int(sizes.sum()),
        "max_family_key": maximum_key,
        "family_sizes": {str(key): int(value) for key, value in sizes.items()},
    }


def _permutation_census(
    config: dict[str, Any], tests: pd.DataFrame, lens: str
) -> dict[str, Any]:
    census = _family_census(tests)
    alpha = float(config["statistics"].get("report_q_max", 0.05))
    if not 0 < alpha <= 1:
        raise ValueError("statistics.report_q_max must be in (0, 1]")
    k_min = int(((config.get("runtime") or {}).get("budgets") or {}).get("k_min", 10))
    if k_min <= 0:
        raise ValueError("runtime.budgets.k_min must be positive")
    family_size = max(census["family_sizes"].values(), default=0)
    required = max(1, int(math.ceil(family_size / (alpha * k_min)) - 1))
    configured = _permutations(config, lens)
    return {
        **census,
        "report_q_max": alpha,
        "k_min": k_min,
        "configured_final_permutations": configured,
        "required_final_permutations": required,
        "statistical_budget_satisfied": required <= configured,
    }


def _rate(config: dict[str, Any], lens: str) -> int:
    configured = ((config.get("runtime") or {}).get("units_per_second") or {}).get(lens)
    value = int(configured if configured is not None else RATES[lens])
    if value <= 0:
        raise ValueError(f"runtime.units_per_second.{lens} must be positive")
    return value


def _peak(value: int | float) -> int:
    return int(math.ceil(max(0.0, float(value)) * SAFETY_FACTOR))


def _permutations(config: dict[str, Any], lens: str) -> int:
    lens_config = ((config.get("lenses") or {}).get(lens) or {})
    return int(
        lens_config.get(
            "final_permutations", config["statistics"]["final_permutations"]
        )
    )


def estimate_work(
    request: dict[str, Any], config: dict[str, Any], *, workers: int
) -> WorkEstimate:
    operation = str((request.get("parameters") or {}).get("operation", ""))
    if operation == "l1b":
        return _estimate_l1b(request, config)
    if operation == "l2a":
        return _estimate_l2a(request, config)
    if operation == "l2b":
        return _estimate_l2b(request, config)
    if operation == "l4":
        return _estimate_l4(request, config, workers=max(1, int(workers)))
    if operation == "l5":
        return _estimate_l5(request, config)
    if operation == "l7":
        return _estimate_l7(request, config)
    raise ValueError(f"Unsupported work-estimate operation: {operation}")


def _estimate_l1b(request: dict[str, Any], config: dict[str, Any]) -> WorkEstimate:
    from conductor_lens_l1b import run_l1b

    registry = json.loads(_input(request, "feature_spaces").read_text(encoding="utf-8"))
    lens = config["lenses"]["l1b"]
    contexts = config["contexts"]
    result = run_l1b(
        _read_csv(_input(request, "compounds"), ids=True),
        _read_csv(_input(request, "endpoint_table"), ids=True),
        _read_csv(_input(request, "context_catalog")),
        _read_csv(_input(request, "context_membership"), ids=True),
        registry["spaces"],
        request["endpoint_id"],
        run_seed=int(request["random_seed"]),
        neighbor_k=int(contexts["neighbor_k"]),
        min_endpoint_n=int(contexts["min_endpoint_n"]),
        lambda_min=float(lens["lambda_min"]),
        screen_permutations=1,
        final_permutations=1,
        screen_p_max=1.0,
        report_q_max=1.0,
        calibration_permutations=1,
    )
    metrics = result.metrics
    n = int(metrics["compound_count"])
    spaces = int(metrics["space_count"])
    member_work = int(metrics["member_work_count"])
    neighbor_k = int(contexts["neighbor_k"])
    maximum = int(metrics["max_context_members"])
    b1 = _permutations(config, "l1b") + 1
    units = b1 * member_work
    memory = 8 * (
        spaces * n * n
        + member_work * neighbor_k
        + 2 * member_work
        + 2 * n
        + 2 * maximum * maximum
    )
    census = _permutation_census(config, result.tests, "l1b")
    return WorkEstimate(
        units,
        max(census["family_sizes"].values(), default=0),
        _peak(memory),
        units / _rate(config, "l1b") * SAFETY_FACTOR,
        {
            **census,
            "compound_count": n,
            "space_count": spaces,
            "member_work_count": member_work,
            "neighbor_k": neighbor_k,
            "max_context_members": maximum,
            "permutations": _permutations(config, "l1b"),
        },
    )


def _database_pairs(path: Path) -> pd.DataFrame:
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
        return pd.read_sql_query(
            'SELECT pair_id,"class",compound_from,compound_to,constant_key,'
            "variable_from,variable_to,transformation_id FROM pairs ORDER BY pair_id",
            connection,
        )


def _estimate_l2a(request: dict[str, Any], config: dict[str, Any]) -> WorkEstimate:
    from conductor_lens_l2 import run_l2a

    lens = config["lenses"]["l2a"]
    result = run_l2a(
        _database_pairs(_input(request, "mmp_database")),
        _read_csv(_input(request, "endpoint_table"), ids=True),
        _read_csv(_input(request, "context_catalog")),
        _read_csv(_input(request, "context_membership"), ids=True),
        request["endpoint_id"],
        run_seed=int(request["random_seed"]),
        min_transform_pairs=int(lens["min_transform_pairs"]),
        min_pairs_in=int(lens["min_pairs_in"]),
        min_pairs_out=int(lens["min_pairs_out"]),
        neutral_abs_delta_max=float(config["measurement"]["neutral_abs_delta_max"]),
        tolerance_variance_max=float(config["measurement"]["tolerance_variance_max"]),
        screen_permutations=1,
        final_permutations=1,
        screen_p_max=1.0,
        report_q_max=1.0,
    )
    metrics = result.metrics
    pair_count = int(metrics["eligible_pair_count"])
    question_count = int(metrics["test_count"])
    b1 = _permutations(config, "l2a") + 1
    units = b1 * pair_count
    memory = 8 * (
        int(metrics["finite_endpoint_count"])
        + 6 * pair_count
        + int(metrics["series_member_count"])
        + 3 * question_count
    )
    census = _permutation_census(config, result.tests, "l2a")
    return WorkEstimate(
        units,
        max(census["family_sizes"].values(), default=0),
        _peak(memory),
        units / _rate(config, "l2a") * SAFETY_FACTOR,
        {
            **census,
            "pair_count": pair_count,
            "transformation_count": int(metrics["eligible_transformation_count"]),
            "class_count": int(metrics["class_count"]),
            "series_member_count": int(metrics["series_member_count"]),
            "test_count": question_count,
            "permutations": _permutations(config, "l2a"),
        },
    )


def _estimate_l2b(request: dict[str, Any], config: dict[str, Any]) -> WorkEstimate:
    from conductor_lens_l2 import run_l2b

    observations = _read_csv(_input(request, "fragment_observations"), ids=True)
    lens = config["lenses"]["l2b"]
    result = run_l2b(
        observations,
        _read_csv(_input(request, "endpoint_table"), ids=True),
        request["endpoint_id"],
        run_seed=int(request["random_seed"]),
        screen_permutations=1,
        final_permutations=1,
        screen_p_max=1.0,
        report_q_max=1.0,
        calibration_permutations=1,
        enrichment_thresholds=lens["enrichment_thresholds"],
    )
    observations_work = int(result.metrics["observation_work_count"])
    tests = int(result.metrics["test_count"])
    b1 = _permutations(config, "l2b") + 1
    units = b1 * observations_work
    memory = 8 * (12 * len(observations) + 8 * observations_work + tests * (b1 + 10))
    census = _permutation_census(config, result.tests, "l2b")
    return WorkEstimate(
        units,
        max(census["family_sizes"].values(), default=0),
        _peak(memory),
        units / _rate(config, "l2b") * SAFETY_FACTOR,
        {
            **census,
            "observation_count": observations_work,
            "series_count": int(result.metrics["series_count"]),
            "test_count": tests,
            "permutations": _permutations(config, "l2b"),
        },
    )


def _space_cost_class(root: Path, space: dict[str, Any]) -> str:
    declared = str(space.get("cost_class", "")).strip()
    if declared:
        return declared
    capability = json.loads(
        (root / ".claude" / "skills" / str(space["skill_name"]) / "capability.json").read_text(
            encoding="utf-8"
        )
    )
    return str((capability.get("cost") or {}).get("class", ""))


def _estimate_l4(
    request: dict[str, Any], config: dict[str, Any], *, workers: int
) -> WorkEstimate:
    from conductor_lens_l4 import (
        L4ScaleGuardError,
        generate_l4_candidates,
        select_l4_candidates,
    )

    database = _input(request, "mmp_database")
    with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
        fragmentations = pd.read_sql_query(
            'SELECT fragmentation_id,compound_id,"class",constant_key,'
            "variable_smiles,status FROM fragmentations ORDER BY fragmentation_id",
            connection,
        )
        transformations = pd.read_sql_query(
            'SELECT transformation_id,"class",variable_from,variable_to,'
            "pair_count FROM transformations ORDER BY transformation_id",
            connection,
        )
    root = Path(__file__).resolve().parents[2]
    registry = json.loads(_input(request, "feature_spaces").read_text(encoding="utf-8"))
    spaces = [item for item in registry["spaces"] if int(item["tier"]) <= 2]
    raw = generate_l4_candidates(
        _read_csv(_input(request, "compounds"), ids=True),
        fragmentations,
        transformations,
    )
    lens = config["lenses"]["l4"]
    selection_arguments = {
        "candidate_cap": int(lens.get("candidate_cap", 100)),
        "description_space_count": len(spaces),
        "max_candidate_description_rows": int(
            lens.get("max_candidate_description_rows", 900)
        ),
        "description_cost_classes": [_space_cost_class(root, space) for space in spaces],
        "max_candidate_description_cost_units": int(
            lens.get("max_candidate_description_cost_units", 10000)
        ),
    }
    try:
        _, plan = select_l4_candidates(raw, **selection_arguments)
    except L4ScaleGuardError as exc:
        plan = exc.plan
    candidate_count = int(plan.selected_candidate_count)
    space_count = int(plan.description_space_count)
    endpoints = _read_csv(_input(request, "endpoint_table"), ids=True)
    endpoint_rows = endpoints.loc[
        endpoints["endpoint_id"].astype(str).eq(str(request["endpoint_id"]))
    ]
    observation_count = int(
        np.isfinite(pd.to_numeric(endpoint_rows["oriented_value"], errors="coerce")).sum()
    )
    feature_counts: list[int] = []
    for space in spaces:
        metadata_path = Path(space["distance_metadata_path"])
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        feature_counts.append(len(metadata.get("feature_columns", [])))
    maximum_features = max(feature_counts, default=0)
    units = candidate_count * space_count
    description_cost = int(plan.planned_description_cost_units)
    memory = 8 * (
        candidate_count * observation_count * maximum_features
        + candidate_count * maximum_features
        + observation_count * maximum_features
    )
    seconds = (
        units / _rate(config, "l4")
        + description_cost * 0.00804 / workers
    ) * SAFETY_FACTOR
    return WorkEstimate(
        units,
        candidate_count,
        _peak(memory),
        seconds,
        {
            "candidate_count": candidate_count,
            "space_count": space_count,
            "observation_count": observation_count,
            "max_feature_count": maximum_features,
            "description_cost_units": description_cost,
            "available_workers": workers,
        },
    )


def _estimate_l5(request: dict[str, Any], config: dict[str, Any]) -> WorkEstimate:
    from conductor_lens_l5 import run_l5

    registry = json.loads(_input(request, "feature_spaces").read_text(encoding="utf-8"))
    result = run_l5(
        _read_csv(_input(request, "compounds"), ids=True),
        _read_csv(_input(request, "endpoint_table"), ids=True),
        _read_csv(_input(request, "context_catalog")),
        _read_csv(_input(request, "context_membership"), ids=True),
        registry["spaces"],
        request["endpoint_id"],
        run_seed=int(request["random_seed"]),
        min_endpoint_n=int(config["contexts"]["min_endpoint_n"]),
        min_abs_r=float(config["lenses"]["l5"]["min_abs_r"]),
        screen_permutations=1,
        final_permutations=1,
        screen_p_max=1.0,
        report_q_max=1.0,
        calibration_permutations=1,
    )
    metrics = result.metrics
    n = int(metrics["compound_count"])
    comparisons = int(metrics["comparison_count"])
    features = int(metrics["feature_count"])
    blocks = int(metrics["block_count"])
    final_permutations = _permutations(config, "l5")
    b1 = final_permutations + 1
    units = b1 * comparisons * features
    candidates = int(metrics["screen_candidate_count"])
    batch_size = int(config["lenses"]["l5"].get("permutation_batch_size", 64))
    memory = 8 * (
        4 * n * features
        + 2 * comparisons * n
        + 12 * comparisons * features
        + 4 * candidates * n
        + 12 * candidates * batch_size
        + 2 * features
        + 2 * blocks
    )
    census = _permutation_census(config, result.tests, "l5")
    return WorkEstimate(
        units,
        max(census["family_sizes"].values(), default=0),
        _peak(memory),
        units / _rate(config, "l5") * SAFETY_FACTOR,
        {
            **census,
            "compound_count": n,
            "comparison_count": comparisons,
            "feature_count": features,
            "candidate_count": candidates,
            "block_count": blocks,
            "permutations": final_permutations,
            "permutation_batch_size": batch_size,
            "correlation_engine": "matrix_blas_v1",
        },
    )


def _estimate_l7(request: dict[str, Any], config: dict[str, Any]) -> WorkEstimate:
    from conductor_lens_l7 import run_l7

    observations = _read_csv(_input(request, "fragment_observations"), ids=True)
    result = run_l7(
        observations,
        _read_csv(_input(request, "endpoint_table"), ids=True),
        request["endpoint_id"],
        run_seed=int(request["random_seed"]),
        min_common_r_groups=int(config["lenses"]["l7"]["min_common_r_groups"]),
        min_abs_spearman_rho=float(config["lenses"]["l7"]["min_abs_spearman_rho"]),
        screen_permutations=1,
        final_permutations=1,
        screen_p_max=1.0,
        report_q_max=1.0,
    )
    candidates = int(result.metrics["series_pair_count"])
    tests = int(result.metrics["test_count"])
    b1 = _permutations(config, "l7") + 1
    units = b1 * candidates * 2
    memory = 8 * (12 * len(observations) + candidates * 2 * (b1 + 8))
    census = _permutation_census(config, result.tests, "l7")
    return WorkEstimate(
        units,
        max(census["family_sizes"].values(), default=0),
        _peak(memory),
        units / _rate(config, "l7") * SAFETY_FACTOR,
        {
            **census,
            "candidate_count": candidates,
            "question_count": 2,
            "test_count": tests,
            "permutations": _permutations(config, "l7"),
        },
    )
