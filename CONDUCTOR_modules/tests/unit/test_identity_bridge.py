from __future__ import annotations

import re

import pytest

from identity_bridge import bridge_legacy_identity


def test_identity_bridge_is_strict_and_deterministic() -> None:
    identity = {
        "project": "P", "run_id": "RUN", "phase_id": "P03",
        "node_id": "NODE-P03-L4", "attempt_id": "ATT-acde1234",
    }
    first = bridge_legacy_identity(
        identity, capability_id="D015", skill_name="cs-compute-description-mordred-2d"
    )
    second = bridge_legacy_identity(
        identity, capability_id="D015", skill_name="cs-compute-description-mordred-2d"
    )
    assert first == second
    assert first["round_id"] == "RND0003"
    assert re.fullmatch(r"N[0-9]{6}", first["node_id"])
    assert re.fullmatch(r"ATT[0-9]{4}", first["attempt_id"])


def test_identity_bridge_rejects_non_phase_identity() -> None:
    with pytest.raises(ValueError, match="phase_id"):
        bridge_legacy_identity(
            {"project": "P", "run_id": "R", "phase_id": "3", "node_id": "N", "attempt_id": "A"},
            capability_id="D001", skill_name="cs-fixture",
        )
