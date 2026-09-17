"""Deterministic statistical and contract primitives for CONDUCTOR 0.2.1."""

from .ids import canonical_json, content_hash, stable_id
from .findings import ENTITY_KEYS, assign_finding_ids, base_finding, finding_key
from .models import EndpointSpec, TestRecord
from .llm import LogicalCallFailure, call_local_jsonl
from .contracts import (
    SchemaValidationError,
    atomic_write_json,
    file_sha256,
    load_resolved_config,
    validate_instance,
)
from .statistics import (
    benjamini_hochberg,
    block_bootstrap_indices,
    derive_seed,
    empirical_p_value,
    permute_within_blocks,
)

__all__ = [
    "EndpointSpec",
    "ENTITY_KEYS",
    "LogicalCallFailure",
    "TestRecord",
    "SchemaValidationError",
    "atomic_write_json",
    "assign_finding_ids",
    "base_finding",
    "benjamini_hochberg",
    "block_bootstrap_indices",
    "canonical_json",
    "call_local_jsonl",
    "content_hash",
    "derive_seed",
    "empirical_p_value",
    "file_sha256",
    "finding_key",
    "load_resolved_config",
    "permute_within_blocks",
    "stable_id",
    "validate_instance",
]

__version__ = "0.2.1"
