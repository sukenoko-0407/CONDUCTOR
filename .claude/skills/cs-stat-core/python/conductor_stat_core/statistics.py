from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray

from .models import Alternative, TestRecord


def _is_missing_label(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(np.isnan(value))
    except (TypeError, ValueError):
        return False


def permute_within_blocks(
    values: ArrayLike,
    block_labels: Sequence[Any],
    rng: np.random.Generator,
) -> tuple[NDArray[np.float64], float]:
    """Permute finite values inside non-null blocks with at least two values."""

    source = np.asarray(values, dtype=float)
    if source.ndim != 1:
        raise ValueError("values must be one-dimensional")
    if len(block_labels) != source.size:
        raise ValueError("values and block_labels must have equal length")

    output = source.copy()
    finite = np.isfinite(source)
    groups: dict[Any, list[int]] = defaultdict(list)
    for index, (is_finite, label) in enumerate(zip(finite, block_labels, strict=True)):
        if is_finite and not _is_missing_label(label):
            groups[label].append(index)

    eligible = 0
    for indices in groups.values():
        if len(indices) <= 1:
            continue
        positions = np.asarray(indices, dtype=int)
        output[positions] = source[rng.permutation(positions)]
        eligible += len(indices)

    denominator = int(finite.sum())
    participation = eligible / denominator if denominator else 0.0
    return output, participation


def derive_seed(run_seed: int, candidate_key: str, iteration: int) -> int:
    if run_seed < 0 or iteration < 0:
        raise ValueError("run_seed and iteration must be non-negative")
    payload = f"{run_seed}|{candidate_key}|{iteration}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big", signed=False)


def empirical_p_value(
    observed: float,
    null_statistics: ArrayLike,
    alternative: Alternative,
) -> float:
    if not math.isfinite(observed):
        raise ValueError("observed statistic must be finite")
    null = np.asarray(null_statistics, dtype=float)
    null = null[np.isfinite(null)]
    if null.size == 0:
        raise ValueError("At least one finite null statistic is required")
    if alternative == "two_sided_abs":
        extreme = int(np.count_nonzero(np.abs(null) >= abs(observed)))
    elif alternative == "upper":
        extreme = int(np.count_nonzero(null >= observed))
    elif alternative == "lower":
        extreme = int(np.count_nonzero(null <= observed))
    else:
        raise ValueError(f"Unknown alternative: {alternative}")
    return (1.0 + extreme) / (1.0 + null.size)


def benjamini_hochberg(records: Sequence[TestRecord]) -> list[TestRecord]:
    """Apply BH independently per family while preserving input order."""

    by_family: dict[str, list[tuple[int, TestRecord]]] = defaultdict(list)
    output = list(records)
    for index, record in enumerate(records):
        if math.isfinite(record.p_value):
            if record.p_value < 0.0 or record.p_value > 1.0:
                raise ValueError(f"p-value outside [0,1]: {record.p_value}")
            by_family[record.family_key].append((index, record))
        else:
            output[index] = record.with_q(None)

    for family_records in by_family.values():
        ordered = sorted(
            family_records,
            key=lambda item: (item[1].p_value, item[1].candidate_key, item[1].test_id),
        )
        count = len(ordered)
        adjusted = [0.0] * count
        running = 1.0
        for reverse_index in range(count - 1, -1, -1):
            rank = reverse_index + 1
            value = min(1.0, ordered[reverse_index][1].p_value * count / rank)
            running = min(running, value)
            adjusted[reverse_index] = max(0.0, running)
        for (original_index, record), q_value in zip(ordered, adjusted, strict=True):
            output[original_index] = record.with_q(q_value)
    return output


@dataclass(frozen=True)
class BootstrapSample:
    indices: NDArray[np.int64]
    instance_labels: tuple[str, ...]


def block_bootstrap_indices(
    block_labels: Sequence[str | None],
    iterations: int,
    seed: int,
) -> Iterator[BootstrapSample]:
    if iterations <= 0:
        raise ValueError("iterations must be positive")
    if seed < 0:
        raise ValueError("seed must be non-negative")
    grouped: dict[str, list[int]] = defaultdict(list)
    for index, label in enumerate(block_labels):
        if label is not None:
            grouped[str(label)].append(index)
    block_ids = sorted(grouped)
    if not block_ids:
        raise ValueError("At least one non-null bootstrap block is required")
    rng = np.random.default_rng(seed)
    for iteration in range(iterations):
        sampled = rng.choice(block_ids, size=len(block_ids), replace=True)
        indices: list[int] = []
        labels: list[str] = []
        for instance, block_id in enumerate(sampled):
            members = grouped[str(block_id)]
            indices.extend(members)
            labels.extend(f"{block_id}#{iteration}:{instance}" for _ in members)
        yield BootstrapSample(np.asarray(indices, dtype=np.int64), tuple(labels))
