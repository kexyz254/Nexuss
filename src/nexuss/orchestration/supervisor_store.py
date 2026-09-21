"""SQLite persistence and hash-chained event ledger for Agent Supervisor."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from nexuss.orchestration.supervisor_models import (
    EventSeverity,
    SupervisorAgent,
    SupervisorEvent,
    SupervisorTaskProjection,
)

_ZERO_HASH = "0" * 64


def default_supervisor_database() -> Path:
    configured = os.environ.get("NEXUSS_SUPERVISOR_DB", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()

    local = os.environ.get("LOCALAPPDATA", "").strip()
    base = Path(local) if local else Path.home() / ".nexuss"
    return base / "Nexuss" / "supervisor.sqlite3"


def _event_hash_payload(
    *,
    sequence: int,
    event_id: UUID,
    event_type: str,
    severity: EventSeverity,
    source_agent_id: str,
    task_id: UUID | None,
    detail: str,
    occurred_at: datetime,
    previous_hash: str,
) -> bytes:
    payload = {
        "sequence": sequence,
        "event_id": str(event_id),
        "event_type": event_type,
        "severity": severity.value,
        "source_agent_id": source_agent_id,
        "task_id": str(task_id) if task_id is not None else None,
        "detail": detail,
        "occurred_at": occurred_at.isoformat(),
        "previous_hash": previous_hash,
    }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


class SQLiteSupervisorStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = (path or default_supervisor_database()).resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    @property
    def path(self) -> Path:
        return self._path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._path,
            timeout=10.0,
            isolation_level=None,
        )
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialise(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS supervisor_agents (
                    agent_id TEXT PRIMARY KEY,
                    agent_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    heartbeat_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS supervisor_events (
                    sequence INTEGER PRIMARY KEY,
                    event_id TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    source_agent_id TEXT NOT NULL,
                    task_id TEXT,
                    detail TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL UNIQUE,
                    event_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS supervisor_task_projection (
                    task_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    projection_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_supervisor_events_time
                ON supervisor_events(occurred_at DESC);

                CREATE INDEX IF NOT EXISTS idx_supervisor_events_task
                ON supervisor_events(task_id, sequence DESC);
                """
            )

    def save_agent(self, agent: SupervisorAgent) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO supervisor_agents (
                    agent_id,
                    agent_json,
                    status,
                    heartbeat_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    agent_json = excluded.agent_json,
                    status = excluded.status,
                    heartbeat_at = excluded.heartbeat_at,
                    updated_at = excluded.updated_at
                """,
                (
                    agent.agent_id,
                    agent.model_dump_json(),
                    agent.status.value,
                    agent.heartbeat_at.isoformat(),
                    agent.updated_at.isoformat(),
                ),
            )
            connection.execute("COMMIT")

    def get_agent(self, agent_id: str) -> SupervisorAgent | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT agent_json
                FROM supervisor_agents
                WHERE agent_id = ?
                """,
                (agent_id,),
            ).fetchone()

        if row is None:
            return None
        return SupervisorAgent.model_validate_json(row[0])

    def list_agents(self) -> tuple[SupervisorAgent, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT agent_json
                FROM supervisor_agents
                ORDER BY agent_id ASC
                """
            ).fetchall()

        return tuple(
            SupervisorAgent.model_validate_json(row[0])
            for row in rows
        )

    def save_task_projection(
        self,
        projection: SupervisorTaskProjection,
    ) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO supervisor_task_projection (
                    task_id,
                    state,
                    projection_json,
                    updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    state = excluded.state,
                    projection_json = excluded.projection_json,
                    updated_at = excluded.updated_at
                """,
                (
                    str(projection.task_id),
                    projection.state,
                    projection.model_dump_json(),
                    projection.updated_at.isoformat(),
                ),
            )
            connection.execute("COMMIT")

    def get_task_projection(
        self,
        task_id: UUID,
    ) -> SupervisorTaskProjection | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT projection_json
                FROM supervisor_task_projection
                WHERE task_id = ?
                """,
                (str(task_id),),
            ).fetchone()

        if row is None:
            return None
        return SupervisorTaskProjection.model_validate_json(row[0])

    def append_event(
        self,
        *,
        event_type: str,
        source_agent_id: str,
        detail: str,
        severity: EventSeverity = EventSeverity.INFO,
        task_id: UUID | None = None,
        occurred_at: datetime | None = None,
    ) -> SupervisorEvent:
        timestamp = occurred_at or datetime.now(UTC)
        event_id = uuid4()

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT sequence, event_hash
                FROM supervisor_events
                ORDER BY sequence DESC
                LIMIT 1
                """
            ).fetchone()

            sequence = 1 if row is None else int(row[0]) + 1
            previous_hash = _ZERO_HASH if row is None else str(row[1])
            event_hash = hashlib.sha256(
                _event_hash_payload(
                    sequence=sequence,
                    event_id=event_id,
                    event_type=event_type,
                    severity=severity,
                    source_agent_id=source_agent_id,
                    task_id=task_id,
                    detail=detail,
                    occurred_at=timestamp,
                    previous_hash=previous_hash,
                )
            ).hexdigest()

            event = SupervisorEvent(
                sequence=sequence,
                event_id=event_id,
                event_type=event_type,
                severity=severity,
                source_agent_id=source_agent_id,
                task_id=task_id,
                detail=detail,
                occurred_at=timestamp,
                previous_hash=previous_hash,
                event_hash=event_hash,
            )

            connection.execute(
                """
                INSERT INTO supervisor_events (
                    sequence,
                    event_id,
                    event_type,
                    severity,
                    source_agent_id,
                    task_id,
                    detail,
                    occurred_at,
                    previous_hash,
                    event_hash,
                    event_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.sequence,
                    str(event.event_id),
                    event.event_type,
                    event.severity.value,
                    event.source_agent_id,
                    str(event.task_id) if event.task_id else None,
                    event.detail,
                    event.occurred_at.isoformat(),
                    event.previous_hash,
                    event.event_hash,
                    event.model_dump_json(),
                ),
            )
            connection.execute("COMMIT")

        return event

    def recent_events(self, *, limit: int = 25) -> tuple[SupervisorEvent, ...]:
        bounded = max(1, min(int(limit), 200))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_json
                FROM supervisor_events
                ORDER BY sequence DESC
                LIMIT ?
                """,
                (bounded,),
            ).fetchall()

        return tuple(
            SupervisorEvent.model_validate_json(row[0])
            for row in rows
        )

    def verify_event_chain(self) -> bool:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_json
                FROM supervisor_events
                ORDER BY sequence ASC
                """
            ).fetchall()

        previous_hash = _ZERO_HASH

        for expected_sequence, row in enumerate(rows, start=1):
            event = SupervisorEvent.model_validate_json(row[0])

            if event.sequence != expected_sequence:
                return False
            if event.previous_hash != previous_hash:
                return False

            expected_hash = hashlib.sha256(
                _event_hash_payload(
                    sequence=event.sequence,
                    event_id=event.event_id,
                    event_type=event.event_type,
                    severity=event.severity,
                    source_agent_id=event.source_agent_id,
                    task_id=event.task_id,
                    detail=event.detail,
                    occurred_at=event.occurred_at,
                    previous_hash=event.previous_hash,
                )
            ).hexdigest()

            if expected_hash != event.event_hash:
                return False

            previous_hash = event.event_hash

        return True
