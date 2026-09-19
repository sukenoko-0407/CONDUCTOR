"""Shared R1 work-estimate and progress contracts.

This module deliberately depends only on the Python standard library so it can
be imported from every isolated Lens environment and from ``cs-runtime``.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class WorkEstimate:
    unit_count: int
    family_size: int
    peak_memory_bytes: int
    estimated_seconds: float
    detail: dict[str, int]

    def __post_init__(self) -> None:
        for name in ("unit_count", "family_size", "peak_memory_bytes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if (
            isinstance(self.estimated_seconds, bool)
            or not isinstance(self.estimated_seconds, (int, float))
            or not math.isfinite(float(self.estimated_seconds))
            or self.estimated_seconds < 0
        ):
            raise ValueError("estimated_seconds must be a finite non-negative number")
        if not isinstance(self.detail, dict):
            raise ValueError("detail must be an object")
        for key, value in self.detail.items():
            if not isinstance(key, str):
                raise ValueError("detail keys must be strings")
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"detail[{key!r}] must be a non-negative integer")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "WorkEstimate":
        expected = {
            "unit_count",
            "family_size",
            "peak_memory_bytes",
            "estimated_seconds",
            "detail",
        }
        if set(value) != expected:
            raise ValueError(
                f"WorkEstimate fields must be exactly {sorted(expected)}; "
                f"received {sorted(value)}"
            )
        detail = value["detail"]
        if not isinstance(detail, Mapping):
            raise ValueError("WorkEstimate.detail must be an object")
        return cls(
            unit_count=_strict_int(value["unit_count"], "unit_count"),
            family_size=_strict_int(value["family_size"], "family_size"),
            peak_memory_bytes=_strict_int(
                value["peak_memory_bytes"], "peak_memory_bytes"
            ),
            estimated_seconds=_strict_float(
                value["estimated_seconds"], "estimated_seconds"
            ),
            detail={str(key): _strict_int(item, f"detail[{key!r}]") for key, item in detail.items()},
        )


def _strict_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _strict_float(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    return float(value)


class ProgressReporter:
    """Rate-limited atomic writer for the R1 progress side channel."""

    def __init__(
        self,
        path: Path | None,
        total_units: int,
        *,
        min_seconds: float = 5.0,
        min_fraction: float = 0.01,
    ) -> None:
        if total_units < 0:
            raise ValueError("total_units must be non-negative")
        if min_seconds < 0 or not 0 <= min_fraction <= 1:
            raise ValueError("Invalid progress throttling configuration")
        self.path = path.resolve() if path is not None else None
        self.total_units = int(total_units)
        self.min_seconds = float(min_seconds)
        self.min_completed = max(1, math.ceil(total_units * min_fraction))
        self.started_at = time.monotonic()
        self.last_written_at = self.started_at
        self.last_completed = 0

    @classmethod
    def from_environment(
        cls,
        total_units: int,
        *,
        min_seconds: float = 5.0,
        min_fraction: float = 0.01,
    ) -> "ProgressReporter":
        raw = os.environ.get("CONDUCTOR_PROGRESS_PATH", "").strip()
        return cls(
            Path(raw) if raw else None,
            total_units,
            min_seconds=min_seconds,
            min_fraction=min_fraction,
        )

    def update(self, completed_units: int, *, force: bool = False) -> None:
        completed = max(0, min(int(completed_units), self.total_units))
        now = time.monotonic()
        enough_time = now - self.last_written_at >= self.min_seconds
        enough_work = completed - self.last_completed >= self.min_completed
        if not force and not (enough_time and enough_work):
            return
        if self.path is not None:
            _atomic_json(
                self.path,
                {
                    "completed_units": completed,
                    "total_units": self.total_units,
                    "elapsed_seconds": max(0.0, now - self.started_at),
                },
            )
        self.last_written_at = now
        self.last_completed = completed

    def finish(self) -> None:
        self.update(self.total_units, force=True)


def _atomic_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise
