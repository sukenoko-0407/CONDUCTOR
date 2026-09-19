from __future__ import annotations

import json
from pathlib import Path

import pytest

from work_contract import ProgressReporter, WorkEstimate


def test_work_estimate_round_trip_and_rejects_extra_fields() -> None:
    estimate = WorkEstimate(
        unit_count=1001,
        family_size=52,
        peak_memory_bytes=4096,
        estimated_seconds=0.25,
        detail={"permutations": 1000},
    )
    assert WorkEstimate.from_dict(estimate.to_dict()) == estimate
    with pytest.raises(ValueError, match="exactly"):
        WorkEstimate.from_dict({**estimate.to_dict(), "unexpected": 1})


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("unit_count", -1),
        ("family_size", -1),
        ("peak_memory_bytes", -1),
        ("estimated_seconds", -0.1),
    ),
)
def test_work_estimate_rejects_negative_values(field: str, value: int | float) -> None:
    values = {
        "unit_count": 1,
        "family_size": 1,
        "peak_memory_bytes": 1,
        "estimated_seconds": 1.0,
        "detail": {},
    }
    values[field] = value
    with pytest.raises(ValueError):
        WorkEstimate(**values)


def test_progress_reporter_requires_time_and_fraction_then_forces_final(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticks = iter((0.0, 1.0, 6.0, 7.0))
    monkeypatch.setattr("work_contract.time.monotonic", lambda: next(ticks))
    path = tmp_path / "progress.json"
    reporter = ProgressReporter(path, 100, min_seconds=5, min_fraction=0.10)
    reporter.update(20)
    assert not path.exists()
    reporter.update(20)
    assert json.loads(path.read_text(encoding="utf-8"))["completed_units"] == 20
    reporter.finish()
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "completed_units": 100,
        "total_units": 100,
        "elapsed_seconds": 7.0,
    }
