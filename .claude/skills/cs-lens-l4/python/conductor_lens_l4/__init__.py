"""CONDUCTOR 0.2.1 L4 reachable-region lens."""

from .l4 import (
    DESCRIPTION_COST_WEIGHTS,
    L4GenerationResult,
    L4Result,
    L4ScaleGuardError,
    L4ScalePlan,
    assemble_fragments,
    candidate_distance_matrix,
    generate_l4_candidates,
    select_l4_candidates,
    run_l4,
    score_l4_candidates,
)

__all__ = [
    "DESCRIPTION_COST_WEIGHTS",
    "L4GenerationResult",
    "L4Result",
    "L4ScaleGuardError",
    "L4ScalePlan",
    "assemble_fragments",
    "candidate_distance_matrix",
    "generate_l4_candidates",
    "select_l4_candidates",
    "run_l4",
    "score_l4_candidates",
]
__version__ = "0.2.1"
