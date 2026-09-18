from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


TERMINAL_STATES = {"succeeded", "failed", "needs_design_review"}
TRANSITIONS = {
    "pending": {"leased"},
    "retryable": {"leased"},
    "leased": {"running", "retryable", "failed"},
    "running": {"succeeded", "failed", "needs_design_review", "retryable"},
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class RuntimeStateStore:
    """SQLite WAL state store. Callers must serialize writes through one coordinator."""

    def __init__(self, path: Path):
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS nodes(
                    node_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    phase_id TEXT NOT NULL,
                    skill_name TEXT NOT NULL,
                    state TEXT NOT NULL,
                    attempt_id TEXT,
                    lease_token TEXT,
                    lease_expires_at TEXT,
                    input_hashes_json TEXT NOT NULL,
                    config_hash TEXT NOT NULL,
                    code_version TEXT NOT NULL,
                    manifest_path TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS reuse_key
                  ON nodes(node_id, input_hashes_json, config_hash, code_version);
                CREATE TABLE IF NOT EXISTS events(
                    event_id TEXT PRIMARY KEY,
                    node_id TEXT NOT NULL,
                    attempt_id TEXT,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    accepted INTEGER NOT NULL,
                    rejection_reason TEXT,
                    FOREIGN KEY(node_id) REFERENCES nodes(node_id)
                );
                CREATE TABLE IF NOT EXISTS dependencies(
                    node_id TEXT NOT NULL,
                    depends_on TEXT NOT NULL,
                    PRIMARY KEY(node_id, depends_on),
                    FOREIGN KEY(node_id) REFERENCES nodes(node_id),
                    FOREIGN KEY(depends_on) REFERENCES nodes(node_id)
                );
                """
            )
            connection.commit()

    def register_node(
        self,
        *,
        node_id: str,
        run_id: str,
        phase_id: str,
        skill_name: str,
        input_hashes: list[str],
        config_hash: str,
        code_version: str,
    ) -> dict[str, Any]:
        now = _timestamp(_utc_now())
        encoded_hashes = json.dumps(sorted(input_hashes), separators=(",", ":"))
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM nodes WHERE node_id=?", (node_id,)
            ).fetchone()
            if existing:
                same_key = (
                    existing["input_hashes_json"] == encoded_hashes
                    and existing["config_hash"] == config_hash
                    and existing["code_version"] == code_version
                )
                if not same_key:
                    connection.rollback()
                    raise ValueError(f"node_id is already registered with a different reuse key: {node_id}")
                connection.rollback()
                return self._row(existing)
            connection.execute(
                """
                INSERT INTO nodes(
                    node_id,run_id,phase_id,skill_name,state,input_hashes_json,
                    config_hash,code_version,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    node_id,
                    run_id,
                    phase_id,
                    skill_name,
                    "pending",
                    encoded_hashes,
                    config_hash,
                    code_version,
                    now,
                ),
            )
            connection.commit()
        return self.get_node(node_id)

    def lease(self, node_id: str, *, seconds: int = 300) -> dict[str, Any]:
        if seconds <= 0:
            raise ValueError("Lease duration must be positive")
        now = _utc_now()
        attempt_id = f"ATT-{uuid.uuid4().hex[:16]}"
        lease_token = uuid.uuid4().hex
        expires = _timestamp(now + timedelta(seconds=seconds))
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM nodes WHERE node_id=?", (node_id,)).fetchone()
            if row is None:
                connection.rollback()
                raise KeyError(node_id)
            if row["state"] not in {"pending", "retryable"}:
                connection.rollback()
                raise ValueError(f"Node cannot be leased from state {row['state']}")
            connection.execute(
                """
                UPDATE nodes SET state='leased',attempt_id=?,lease_token=?,
                    lease_expires_at=?,updated_at=? WHERE node_id=?
                """,
                (attempt_id, lease_token, expires, _timestamp(now), node_id),
            )
            connection.commit()
        return self.get_node(node_id)

    def apply_event(self, event: dict[str, Any]) -> bool:
        node_id = str(event["node_id"])
        event_type = str(event["event_type"])
        desired = {
            "started": "running",
            "succeeded": "succeeded",
            "failed": "failed",
            "needs_design_review": "needs_design_review",
            "retryable": "retryable",
            "leased": None,
            "heartbeat": None,
        }.get(event_type)
        if event_type not in {"leased", "started", "succeeded", "failed", "needs_design_review", "retryable", "heartbeat"}:
            raise ValueError(f"Unsupported event_type: {event_type}")
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute("SELECT accepted FROM events WHERE event_id=?", (event["event_id"],)).fetchone()
            if previous is not None:
                connection.rollback()
                return bool(previous["accepted"])
            row = connection.execute("SELECT * FROM nodes WHERE node_id=?", (node_id,)).fetchone()
            if row is None:
                connection.rollback()
                raise KeyError(node_id)
            rejection: str | None = None
            if row["attempt_id"] != event.get("attempt_id"):
                rejection = "attempt_id_mismatch"
            elif row["lease_token"] != event.get("lease_token"):
                rejection = "lease_token_mismatch"
            elif desired is not None and desired not in TRANSITIONS.get(row["state"], set()):
                rejection = f"invalid_transition:{row['state']}->{desired}"
            accepted = rejection is None
            connection.execute(
                """
                INSERT INTO events(event_id,node_id,attempt_id,event_type,payload_json,
                    occurred_at,accepted,rejection_reason) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    event["event_id"],
                    node_id,
                    event.get("attempt_id"),
                    event_type,
                    json.dumps(event.get("payload", {}), sort_keys=True, separators=(",", ":")),
                    event["occurred_at"],
                    int(accepted),
                    rejection,
                ),
            )
            if accepted and desired is not None:
                manifest_path = event.get("payload", {}).get("manifest_path")
                connection.execute(
                    """
                    UPDATE nodes SET state=?,manifest_path=COALESCE(?,manifest_path),updated_at=?
                    WHERE node_id=?
                    """,
                    (desired, manifest_path, event["occurred_at"], node_id),
                )
            connection.commit()
        return accepted

    def register_dependencies(self, node_id: str, dependencies: list[str]) -> None:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM nodes WHERE node_id=?", (node_id,)).fetchone() is None:
                connection.rollback()
                raise KeyError(node_id)
            for dependency in sorted(set(dependencies)):
                if dependency == node_id:
                    connection.rollback()
                    raise ValueError("A node cannot depend on itself")
                if connection.execute("SELECT 1 FROM nodes WHERE node_id=?", (dependency,)).fetchone() is None:
                    connection.rollback()
                    raise KeyError(dependency)
                connection.execute("INSERT OR IGNORE INTO dependencies(node_id,depends_on) VALUES(?,?)", (node_id, dependency))
            connection.commit()

    def ready_nodes(self, run_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT n.* FROM nodes n
                WHERE n.run_id=? AND n.state IN ('pending','retryable')
                  AND NOT EXISTS (
                    SELECT 1 FROM dependencies d JOIN nodes parent ON parent.node_id=d.depends_on
                    WHERE d.node_id=n.node_id AND parent.state!='succeeded'
                  )
                ORDER BY n.phase_id,n.node_id
                """,
                (run_id,),
            ).fetchall()
        return [self._row(row) for row in rows]

    def list_nodes(self, run_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT * FROM nodes WHERE run_id=? ORDER BY phase_id,node_id", (run_id,)).fetchall()
        return [self._row(row) for row in rows]

    def event_count(self, node_id: str, event_types: tuple[str, ...]) -> int:
        placeholders = ",".join("?" for _ in event_types)
        with closing(self._connect()) as connection:
            row = connection.execute(
                f"SELECT COUNT(*) AS count FROM events WHERE node_id=? AND accepted=1 AND event_type IN ({placeholders})",
                (node_id, *event_types),
            ).fetchone()
        return int(row["count"])

    def expire_leases(self, *, now: datetime | None = None) -> list[str]:
        current = _timestamp(now or _utc_now())
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT node_id FROM nodes
                WHERE state IN ('leased','running') AND lease_expires_at < ?
                ORDER BY node_id
                """,
                (current,),
            ).fetchall()
            node_ids = [str(row["node_id"]) for row in rows]
            if node_ids:
                connection.executemany(
                    """
                    UPDATE nodes SET state='retryable',lease_token=NULL,
                        lease_expires_at=NULL,updated_at=? WHERE node_id=?
                    """,
                    [(current, node_id) for node_id in node_ids],
                )
            connection.commit()
        return node_ids

    def requeue_failed_node(
        self,
        node_id: str,
        *,
        expected_skill_name: str,
        operator: str,
        reason: str,
    ) -> dict[str, Any]:
        """Audit and requeue one failed node after an explicit implementation fix.

        This is deliberately narrower than a general state editor: succeeded,
        needs-design-review, running, leased, pending, and already-retryable
        nodes cannot be changed through this method.
        """

        if not operator.strip():
            raise ValueError("Administrative requeue requires an operator")
        if not reason.strip():
            raise ValueError("Administrative requeue requires a reason")
        occurred_at = _timestamp(_utc_now())
        event_id = f"ADMIN-REQUEUE-{uuid.uuid4().hex}"
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM nodes WHERE node_id=?", (node_id,)
            ).fetchone()
            if row is None:
                connection.rollback()
                raise KeyError(node_id)
            if row["skill_name"] != expected_skill_name:
                connection.rollback()
                raise ValueError(
                    "Administrative requeue skill mismatch: "
                    f"expected {expected_skill_name!r}, found {row['skill_name']!r}"
                )
            if row["state"] != "failed":
                connection.rollback()
                raise ValueError(
                    "Administrative requeue is allowed only from failed; "
                    f"found {row['state']!r}"
                )
            payload = {
                "operator": operator.strip(),
                "reason": reason.strip(),
                "previous_state": "failed",
                "previous_attempt_id": row["attempt_id"],
                "code_version": row["code_version"],
            }
            connection.execute(
                """
                INSERT INTO events(
                    event_id,node_id,attempt_id,event_type,payload_json,
                    occurred_at,accepted,rejection_reason
                ) VALUES(?,?,?,?,?,?,1,NULL)
                """,
                (
                    event_id,
                    node_id,
                    row["attempt_id"],
                    "administrative_requeue",
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                    occurred_at,
                ),
            )
            connection.execute(
                """
                UPDATE nodes SET state='retryable',attempt_id=NULL,lease_token=NULL,
                    lease_expires_at=NULL,manifest_path=NULL,updated_at=?
                WHERE node_id=?
                """,
                (occurred_at, node_id),
            )
            connection.commit()
        return {
            "event_id": event_id,
            "node_id": node_id,
            "state": "retryable",
            **payload,
        }

    def reusable_manifest(
        self,
        *,
        node_id: str,
        input_hashes: list[str],
        config_hash: str,
        code_version: str,
    ) -> str | None:
        encoded_hashes = json.dumps(sorted(input_hashes), separators=(",", ":"))
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT manifest_path FROM nodes WHERE node_id=? AND state='succeeded'
                  AND input_hashes_json=? AND config_hash=? AND code_version=?
                """,
                (node_id, encoded_hashes, config_hash, code_version),
            ).fetchone()
        return None if row is None else row["manifest_path"]

    def get_node(self, node_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM nodes WHERE node_id=?", (node_id,)).fetchone()
        if row is None:
            raise KeyError(node_id)
        return self._row(row)

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["input_hashes"] = json.loads(result.pop("input_hashes_json"))
        return result
