"""SQLite storage for collaboration sessions and hash-chained turns."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from uuid import UUID

from nexuss.collaboration.models import (
    CollaborationSession,
    ProtocolMessage,
)


def default_collaboration_db() -> Path:
    configured = os.environ.get(
        "NEXUSS_COLLABORATION_DB",
        "",
    ).strip()
    if configured:
        return Path(configured).expanduser().resolve()

    local = os.environ.get("LOCALAPPDATA", "").strip()
    base = Path(local) if local else Path.home() / ".nexuss"
    return base / "Nexuss" / "collaboration.sqlite3"


class SQLiteCollaborationStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = (path or default_collaboration_db()).resolve()
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
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialise(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS collaboration_sessions (
                    session_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL UNIQUE,
                    session_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS collaboration_messages (
                    message_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    nonce TEXT NOT NULL UNIQUE,
                    message_sha256 TEXT NOT NULL UNIQUE,
                    message_json TEXT NOT NULL,
                    issued_at TEXT NOT NULL,
                    UNIQUE(session_id, sequence),
                    FOREIGN KEY(session_id)
                        REFERENCES collaboration_sessions(session_id)
                );
                """
            )

    def save_session(self, session: CollaborationSession) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO collaboration_sessions (
                    session_id,
                    request_id,
                    session_json,
                    state,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    session_json = excluded.session_json,
                    state = excluded.state,
                    updated_at = excluded.updated_at
                """,
                (
                    str(session.session_id),
                    str(session.request_id),
                    session.model_dump_json(),
                    session.state.value,
                    session.updated_at.isoformat(),
                ),
            )
            connection.execute("COMMIT")

    def append_message(self, message: ProtocolMessage) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO collaboration_messages (
                    message_id,
                    session_id,
                    sequence,
                    nonce,
                    message_sha256,
                    message_json,
                    issued_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(message.message_id),
                    str(message.session_id),
                    message.sequence,
                    str(message.nonce),
                    message.message_sha256,
                    message.model_dump_json(),
                    message.issued_at.isoformat(),
                ),
            )
            connection.execute("COMMIT")

    def get_session(
        self,
        session_id: UUID,
    ) -> CollaborationSession | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT session_json
                FROM collaboration_sessions
                WHERE session_id = ?
                """,
                (str(session_id),),
            ).fetchone()

        if row is None:
            return None
        return CollaborationSession.model_validate_json(row[0])

    def get_by_request(
        self,
        request_id: UUID,
    ) -> CollaborationSession | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT session_json
                FROM collaboration_sessions
                WHERE request_id = ?
                """,
                (str(request_id),),
            ).fetchone()

        if row is None:
            return None
        return CollaborationSession.model_validate_json(row[0])

    def messages(
        self,
        session_id: UUID,
    ) -> tuple[ProtocolMessage, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT message_json
                FROM collaboration_messages
                WHERE session_id = ?
                ORDER BY sequence ASC
                """,
                (str(session_id),),
            ).fetchall()

        return tuple(
            ProtocolMessage.model_validate_json(row[0])
            for row in rows
        )
