from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal


@dataclass(frozen=True)
class EndpointSpec:
    endpoint_id: str
    role: Literal["primary", "secondary"]
    kind: Literal["measured", "derived"]
    source_column: str | None
    transform: Literal["none", "neg_log10", "log10"]
    higher_is_better: bool
    unit: str
    dependencies: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.endpoint_id:
            raise ValueError("endpoint_id must not be empty")
        if self.kind == "measured" and not self.source_column:
            raise ValueError("Measured endpoints require source_column")
        if self.kind == "derived" and not self.dependencies:
            raise ValueError("Derived endpoints require dependencies")


Alternative = Literal["two_sided_abs", "upper", "lower"]


@dataclass(frozen=True)
class TestRecord:
    candidate_key: str
    test_id: str
    family_key: str
    statistic: float
    alternative: Alternative
    p_value: float
    q_value: float | None = None
    null_iterations: int = 0
    participation: float | None = None
    status: str = "tested"

    def with_q(self, q_value: float | None) -> "TestRecord":
        return replace(self, q_value=q_value)
