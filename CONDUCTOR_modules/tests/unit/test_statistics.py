from __future__ import annotations

import math

import numpy as np
import pytest

from conductor_stat_core import (
    TestRecord as _TestRecord,
    benjamini_hochberg,
    block_bootstrap_indices,
    derive_seed,
    empirical_p_value,
    permute_within_blocks,
)


def test_permute_within_blocks_preserves_missing_singleton_and_multisets() -> None:
    values = np.asarray([1.0, 2.0, 3.0, 4.0, 5.0, np.nan])
    blocks = ["A", "A", "B", "B", "C", "A"]
    permuted, participation = permute_within_blocks(
        values, blocks, np.random.default_rng(123)
    )

    assert sorted(permuted[:2]) == [1.0, 2.0]
    assert sorted(permuted[2:4]) == [3.0, 4.0]
    assert permuted[4] == 5.0
    assert math.isnan(permuted[5])
    assert participation == pytest.approx(4 / 5)


def test_permute_rejects_shape_mismatch() -> None:
    with pytest.raises(ValueError, match="equal length"):
        permute_within_blocks([1.0], [], np.random.default_rng(1))


def test_seed_is_deterministic_and_candidate_specific() -> None:
    assert derive_seed(7, "A", 3) == derive_seed(7, "A", 3)
    assert derive_seed(7, "A", 3) != derive_seed(7, "B", 3)
    assert derive_seed(7, "A", 3) != derive_seed(7, "A", 4)


@pytest.mark.parametrize(
    ("alternative", "expected"),
    [
        ("two_sided_abs", 3 / 5),
        ("upper", 2 / 5),
        ("lower", 4 / 5),
    ],
)
def test_empirical_p_value_uses_plus_one_rule(
    alternative: str, expected: float
) -> None:
    assert empirical_p_value(2.0, [-3.0, 0.0, 1.0, 3.0], alternative) == expected


def test_empirical_p_value_requires_a_finite_null() -> None:
    with pytest.raises(ValueError, match="finite null"):
        empirical_p_value(1.0, [np.nan], "upper")


def _record(candidate: str, p: float, family: str = "family") -> _TestRecord:
    return _TestRecord(candidate, f"test-{candidate}", family, 1.0, "upper", p)


def test_bh_known_vector_and_input_order() -> None:
    adjusted = benjamini_hochberg(
        [_record("a", 0.01), _record("b", 0.04), _record("c", 0.03)]
    )
    assert [record.candidate_key for record in adjusted] == ["a", "b", "c"]
    assert [record.q_value for record in adjusted] == pytest.approx([0.03, 0.04, 0.04])


def test_bh_separates_families_and_excludes_nan() -> None:
    records = [_record("a", 0.04, "A"), _record("b", 0.04, "B"), _record("c", math.nan, "A")]
    adjusted = benjamini_hochberg(records)
    assert adjusted[0].q_value == 0.04
    assert adjusted[1].q_value == 0.04
    assert adjusted[2].q_value is None


def test_block_bootstrap_keeps_blocks_together() -> None:
    samples = list(block_bootstrap_indices(["A", "A", "B"], iterations=5, seed=8))
    assert len(samples) == 5
    for sample in samples:
        assert len(sample.indices) in {2, 3, 4}
        for label in set(sample.instance_labels):
            members = [index for index, value in enumerate(sample.instance_labels) if value == label]
            assert len(members) in {1, 2}


def test_block_bootstrap_rejects_empty_blocks() -> None:
    with pytest.raises(ValueError, match="non-null"):
        list(block_bootstrap_indices([None, None], iterations=1, seed=1))
