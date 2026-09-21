"""SQLite persistence for local proactive schedules and alerts."""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from nexuss.proactive.models import AlertRecord, ScheduleRecord, ScheduleStatus


def default_proactive_database() -> Path:
    configured = os.getenv("NEXUSS_PROACTIVE_DB", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    repository = os.getenv("NEXUSS_REPOSITORY_ROOT", "").strip()
    if repository:
        return (Path(repository) / ".nexuss-runtime" / "proactive.sqlite3").resolve()
    local = os.getenv("LOCALAPPDATA", "").strip()
    if local:
        return (Path(local) / "Nexuss" / "proactive.sqlite3").resolve()
    return (Path.home() / ".nexuss" / "proactive.sqlite3").resolve()


class ProactiveStoreError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class SQLiteProactiveStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = (path or default_proactive_database()).resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=10.0)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialise(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schedules (
                    schedule_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    user_session_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    next_run_at TEXT NOT NULL,
                    interval_seconds INTEGER,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_schedules_due
                    ON schedules(status, next_run_at);

                CREATE TABLE IF NOT EXISTS alerts (
                    alert_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    user_session_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    fired_at TEXT NOT NULL,
                    acknowledged_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_alerts_session
                    ON alerts(user_session_id, acknowledged_at, fired_at);
                """
            )

    @staticmethod
    def _schedule(row: tuple[object, ...]) -> ScheduleRecord:
        return ScheduleRecord(
            schedule_id=UUID(str(row[0])), conversation_id=UUID(str(row[1])),
            user_session_id=UUID(str(row[2])), title=str(row[3]), prompt=str(row[4]),
            next_run_at=datetime.fromisoformat(str(row[5])),
            interval_seconds=int(str(row[6])) if row[6] is not None else None,
            status=ScheduleStatus(str(row[7])),
            created_at=datetime.fromisoformat(str(row[8])),
            updated_at=datetime.fromisoformat(str(row[9])),
        )

    @staticmethod
    def _alert(row: tuple[object, ...]) -> AlertRecord:
        return AlertRecord(
            alert_id=UUID(str(row[0])), conversation_id=UUID(str(row[1])),
            user_session_id=UUID(str(row[2])), source_type=str(row[3]),
            source_id=UUID(str(row[4])), title=str(row[5]), detail=str(row[6]),
            fired_at=datetime.fromisoformat(str(row[7])),
            acknowledged_at=(datetime.fromisoformat(str(row[8])) if row[8] else None),
        )

    def create_schedule(
        self,
        *,
        conversation_id: UUID,
        user_session_id: UUID,
        title: str,
        prompt: str,
        next_run_at: datetime,
        interval_seconds: int | None = None,
    ) -> ScheduleRecord:
        if interval_seconds is not None and interval_seconds < 60:
            raise ProactiveStoreError(
                "PROACTIVE_INTERVAL_TOO_SHORT",
                "Recurring local schedules must be at least one minute apart.",
            )
        now = datetime.now(UTC)
        record = ScheduleRecord(
            schedule_id=uuid4(), conversation_id=conversation_id,
            user_session_id=user_session_id, title=" ".join(title.split()),
            prompt=prompt.strip(), next_run_at=next_run_at,
            interval_seconds=interval_seconds, created_at=now, updated_at=now,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO schedules (
                    schedule_id, conversation_id, user_session_id, title, prompt,
                    next_run_at, interval_seconds, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(record.schedule_id), str(conversation_id), str(user_session_id),
                    record.title, record.prompt, record.next_run_at.isoformat(),
                    record.interval_seconds, record.status.value,
                    record.created_at.isoformat(), record.updated_at.isoformat(),
                ),
            )
        return record

    def list_schedules(self, user_session_id: UUID) -> tuple[ScheduleRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT schedule_id, conversation_id, user_session_id, title, prompt,
                       next_run_at, interval_seconds, status, created_at, updated_at
                FROM schedules WHERE user_session_id = ?
                ORDER BY next_run_at ASC
                """,
                (str(user_session_id),),
            ).fetchall()
        return tuple(self._schedule(row) for row in rows)

    def claim_due(self, now: datetime) -> tuple[ScheduleRecord, ...]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT schedule_id, conversation_id, user_session_id, title, prompt,
                       next_run_at, interval_seconds, status, created_at, updated_at
                FROM schedules
                WHERE status = 'active' AND next_run_at <= ?
                ORDER BY next_run_at ASC
                """,
                (now.isoformat(),),
            ).fetchall()
            schedules = [self._schedule(row) for row in rows]
            for schedule in schedules:
                if schedule.interval_seconds is None:
                    connection.execute(
                        "UPDATE schedules SET status = 'completed', updated_at = ? "
                        "WHERE schedule_id = ?",
                        (now.isoformat(), str(schedule.schedule_id)),
                    )
                else:
                    next_run = schedule.next_run_at
                    step = timedelta(seconds=schedule.interval_seconds)
                    while next_run <= now:
                        next_run += step
                    connection.execute(
                        "UPDATE schedules SET next_run_at = ?, updated_at = ? "
                        "WHERE schedule_id = ?",
                        (next_run.isoformat(), now.isoformat(), str(schedule.schedule_id)),
                    )
            connection.commit()
        return tuple(schedules)

    def create_alert(
        self,
        *,
        conversation_id: UUID,
        user_session_id: UUID,
        source_type: str,
        source_id: UUID,
        title: str,
        detail: str,
        fired_at: datetime | None = None,
    ) -> AlertRecord:
        record = AlertRecord(
            alert_id=uuid4(), conversation_id=conversation_id,
            user_session_id=user_session_id, source_type=source_type,
            source_id=source_id, title=title, detail=detail,
            fired_at=fired_at or datetime.now(UTC),
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO alerts (
                    alert_id, conversation_id, user_session_id, source_type,
                    source_id, title, detail, fired_at, acknowledged_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    str(record.alert_id), str(conversation_id), str(user_session_id),
                    source_type, str(source_id), title, detail, record.fired_at.isoformat(),
                ),
            )
        return record

    def unacknowledged_alerts(self, user_session_id: UUID) -> tuple[AlertRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT alert_id, conversation_id, user_session_id, source_type,
                       source_id, title, detail, fired_at, acknowledged_at
                FROM alerts
                WHERE user_session_id = ? AND acknowledged_at IS NULL
                ORDER BY fired_at ASC
                LIMIT 50
                """,
                (str(user_session_id),),
            ).fetchall()
        return tuple(self._alert(row) for row in rows)

    def acknowledge(self, alert_id: UUID, user_session_id: UUID) -> bool:
        now = datetime.now(UTC)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE alerts SET acknowledged_at = ?
                WHERE alert_id = ? AND user_session_id = ? AND acknowledged_at IS NULL
                """,
                (now.isoformat(), str(alert_id), str(user_session_id)),
            )
        return cursor.rowcount == 1
