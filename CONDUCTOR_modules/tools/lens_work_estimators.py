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


def _family_size(tests: pd.DataFrame) -> int:
    if tests.empty or "family_key" not in tests:
        return 0
    return int(tests.groupby("family_key", sort=True).size().max())


def _rate(config: dict[str, Any], lens: str) -> int:
    configured = ((config.get("runtime") or {}).get("units_per_second") or {}).get(lens)
    value = int(configured if configured is not None else RATES[lens])
    if value <= 0:
        raise ValueError(f"runtime.units_per_second.{lens} must be positive")
    return value


def _peak(value: int | float) -> int:
    return int(math.ceil(max(0.0, float(value)) * SAFETY_FACTOR))


def _permutations(config: dict[str, Any]) -> int:
    return int(config["statistics"]["final_permutations"])


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
    b1 = _permutations(config) + 1
    units = b1 * member_work
    memory = 8 * (
        spaces * n * n
        + member_work * neighbor_k
        + 2 * member_work
        + 2 * n
        + 2 * maximum * maximum
    )
    return WorkEstimate(
        units,
        _family_size(result.tests),
        _peak(memory),
        units / _rate(config, "l1b") * SAFETY_FACTOR,
        {
            "compound_count": n,
            "space_count": spaces,
            "member_work_count": member_work,
            "neighbor_k": neighbor_k,
            "max_context_members": maximum,
            "permutations": _permutations(config),
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
    b1 = _permutations(config) + 1
    units = b1 * pair_count
    memory = 8 * (
        int(metrics["finite_endpoint_count"])
        + 6 * pair_count
        + int(metrics["series_member_count"])
        + 3 * question_count
    )
    return WorkEstimate(
        units,
        _family_size(result.tests),
        _peak(memory),
        units / _rate(config, "l2a") * SAFETY_FACTOR,
        {
            "pair_count": pair_count,
            "transformation_count": int(metrics["eligible_transformation_count"]),
            "class_count": int(metrics["class_count"]),
            "series_member_count": int(metrics["series_member_count"]),
            "test_count": question_count,
            "permutations": _permutations(config),
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
    b1 = _permutations(config) + 1
    units = b1 * observations_work
    memory = 8 * (12 * len(observations) + 8 * observations_work + tests * (b1 + 10))
    return WorkEstimate(
        units,
        _family_size(result.tests),
        _peak(memory),
        units / _rate(config, "l2b") * SAFETY_FACTOR,
        {
            "observation_count": observations_work,
            "series_count": int(result.metrics["series_count"]),
            "test_count": tests,
            "permutations": _permutations(config),
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
    b1 = _permutations(config) + 1
    units = b1 * comparisons * features
    memory = 8 * (
        4 * n * features
        + comparisons * n
        + 8 * comparisons * features
        + 2 * features
        + 2 * blocks
    )
    return WorkEstimate(
        units,
        _family_size(result.tests),
        _peak(memory),
        units / _rate(config, "l5") * SAFETY_FACTOR,
        {
            "compound_count": n,
            "comparison_count": comparisons,
            "feature_count": features,
            "block_count": blocks,
            "permutations": _permutations(config),
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
    b1 = _permutations(config) + 1
    units = b1 * candidates * 2
    memory = 8 * (12 * len(observations) + candidates * 2 * (b1 + 8))
    return WorkEstimate(
        units,
        _family_size(result.tests),
        _peak(memory),
        units / _rate(config, "l7") * SAFETY_FACTOR,
        {
            "candidate_count": candidates,
            "question_count": 2,
            "test_count": tests,
            "permutations": _permutations(config),
        },
    )
