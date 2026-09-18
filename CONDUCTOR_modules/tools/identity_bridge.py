"""Deterministic identity bridge from CONDUCTOR 0.2.1 to 0.1.x Skills.

The retained Description Skills validate their execution identity against the
0.1.x patterns.  Runtime identities are intentionally more expressive, so the
adapter must never pass them through verbatim.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


PHASE_PATTERN = re.compile(r"^P([0-9]{2})$")
LEGACY_ROUND_PATTERN = re.compile(r"^RND[0-9]{4}$")
LEGACY_NODE_PATTERN = re.compile(r"^N[0-9]{6}$")
LEGACY_ATTEMPT_PATTERN = re.compile(r"^ATT[0-9]{4}$")


def _numeric_hash(prefix: str, width: int, payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    number = int.from_bytes(hashlib.sha256(encoded).digest(), "big") % (10**width)
    return f"{prefix}{number:0{width}d}"


def bridge_legacy_identity(
    identity: dict[str, Any],
    *,
    capability_id: str,
    skill_name: str,
    discriminator: str | None = None,
) -> dict[str, str]:
    """Map a 0.2.1 identity to the strict, deterministic 0.1.x patterns."""

    required = ("project", "run_id", "phase_id", "node_id", "attempt_id")
    missing = [key for key in required if not str(identity.get(key, "")).strip()]
    if missing:
        raise ValueError(f"Identity bridge is missing fields: {missing}")
    phase = str(identity["phase_id"])
    phase_match = PHASE_PATTERN.fullmatch(phase)
    if phase_match is None:
        raise ValueError(f"0.2.1 phase_id does not match ^P[0-9]{{2}}$: {phase!r}")

    scope = {
        "project": str(identity["project"]),
        "run_id": str(identity["run_id"]),
        "phase_id": phase,
        "node_id": str(identity["node_id"]),
        "attempt_id": str(identity["attempt_id"]),
        "capability_id": str(capability_id),
        "skill_name": str(skill_name),
        "discriminator": discriminator,
    }
    original_node = str(identity["node_id"])
    original_attempt = str(identity["attempt_id"])
    mapped = {
        "project": str(identity["project"]),
        "run_id": str(identity["run_id"]),
        "round_id": f"RND{int(phase_match.group(1)):04d}",
        "node_id": (
            original_node
            if LEGACY_NODE_PATTERN.fullmatch(original_node)
            else _numeric_hash("N", 6, {**scope, "kind": "node"})
        ),
        "attempt_id": (
            original_attempt
            if LEGACY_ATTEMPT_PATTERN.fullmatch(original_attempt)
            else _numeric_hash("ATT", 4, {**scope, "kind": "attempt"})
        ),
        "capability_id": str(capability_id),
        "skill_name": str(skill_name),
    }
    if not LEGACY_ROUND_PATTERN.fullmatch(mapped["round_id"]):
        raise AssertionError("Identity bridge emitted an invalid legacy round_id")
    if not LEGACY_NODE_PATTERN.fullmatch(mapped["node_id"]):
        raise AssertionError("Identity bridge emitted an invalid legacy node_id")
    if not LEGACY_ATTEMPT_PATTERN.fullmatch(mapped["attempt_id"]):
        raise AssertionError("Identity bridge emitted an invalid legacy attempt_id")
    return mapped
