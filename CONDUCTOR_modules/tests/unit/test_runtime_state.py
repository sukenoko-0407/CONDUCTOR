from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from conductor_runtime import RuntimeStateStore


def _event(node: dict, event_id: str, event_type: str, *, token: str | None = None) -> dict:
    return {
        "event_id": event_id,
        "node_id": node["node_id"],
        "attempt_id": node["attempt_id"],
        "lease_token": token if token is not None else node["lease_token"],
        "event_type": event_type,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "payload": {"manifest_path": "artifact_manifest.json"} if event_type == "succeeded" else {},
    }


def test_runtime_accepts_current_attempt_and_isolates_late_event(tmp_path: Path) -> None:
    store = RuntimeStateStore(tmp_path / "state" / "runtime.sqlite")
    store.register_node(
        node_id="NODE-1",
        run_id="RUN-1",
        phase_id="P01",
        skill_name="cs-runtime",
        input_hashes=["a" * 64],
        config_hash="b" * 64,
        code_version="0.2.1",
    )
    leased = store.lease("NODE-1")
    assert store.apply_event(_event(leased, "EV-1", "started"))
    assert not store.apply_event(_event(leased, "EV-LATE", "succeeded", token="wrong"))
    assert store.get_node("NODE-1")["state"] == "running"
    assert store.apply_event(_event(leased, "EV-2", "succeeded"))
    assert store.get_node("NODE-1")["state"] == "succeeded"
    assert store.reusable_manifest(
        node_id="NODE-1",
        input_hashes=["a" * 64],
        config_hash="b" * 64,
        code_version="0.2.1",
    ) == "artifact_manifest.json"


def test_runtime_expires_lease_to_retryable(tmp_path: Path) -> None:
    store = RuntimeStateStore(tmp_path / "runtime.sqlite")
    store.register_node(
        node_id="NODE-2",
        run_id="RUN-1",
        phase_id="P02",
        skill_name="cs-stat-core",
        input_hashes=[],
        config_hash="b" * 64,
        code_version="0.2.1",
    )
    store.lease("NODE-2", seconds=1)
    expired = store.expire_leases(now=datetime.now(timezone.utc) + timedelta(seconds=2))
    assert expired == ["NODE-2"]
    assert store.get_node("NODE-2")["state"] == "retryable"


def test_runtime_administrative_requeue_is_limited_to_one_failed_skill(tmp_path: Path) -> None:
    store = RuntimeStateStore(tmp_path / "runtime.sqlite")
    store.register_node(
        node_id="P03-L7", run_id="RUN-1", phase_id="P03",
        skill_name="cs-lens-l7", input_hashes=[], config_hash="b" * 64,
        code_version="0.2.1",
    )
    leased = store.lease("P03-L7")
    assert store.apply_event(_event(leased, "EV-START", "started"))
    assert store.apply_event(_event(leased, "EV-FAIL", "failed"))
    result = store.requeue_failed_node(
        "P03-L7", expected_skill_name="cs-lens-l7", operator="tester",
        reason="Pixi asset fallback fixed and verified",
    )
    assert result["state"] == "retryable"
    assert store.get_node("P03-L7")["attempt_id"] is None
    with pytest.raises(ValueError, match="only from failed"):
        store.requeue_failed_node(
            "P03-L7", expected_skill_name="cs-lens-l7", operator="tester",
            reason="must not requeue twice",
        )
