"""CONDUCTOR 0.2.1 runtime package with dependency-light state access."""

from __future__ import annotations

from typing import Any

from .state import RuntimeStateStore


__all__ = [
    "NodePlan",
    "PipelineCoordinator",
    "PipelinePlan",
    "RuntimeStateStore",
    "prepare_phase1",
]
__version__ = "0.2.1"


def __getattr__(name: str) -> Any:
    if name == "prepare_phase1":
        from .phase1 import prepare_phase1

        return prepare_phase1
    if name in {"NodePlan", "PipelineCoordinator", "PipelinePlan"}:
        from .dag import NodePlan, PipelineCoordinator, PipelinePlan

        return {
            "NodePlan": NodePlan,
            "PipelineCoordinator": PipelineCoordinator,
            "PipelinePlan": PipelinePlan,
        }[name]
    raise AttributeError(name)
