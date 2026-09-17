"""CONDUCTOR 0.2.1 canonical fragmentation engine."""

from .chemistry import core_similarity_mapping
from .database import FragmentDatabaseResult, build_fragment_database
from .fragmentation import (
    FragmentationConfig,
    FragmentationRecord,
    fragment_compound,
    pair_variable_mapping,
)

__all__ = [
    "FragmentDatabaseResult",
    "FragmentationConfig",
    "FragmentationRecord",
    "build_fragment_database",
    "core_similarity_mapping",
    "fragment_compound",
    "pair_variable_mapping",
]
__version__ = "0.2.1"
