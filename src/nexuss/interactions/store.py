"""Durable storage for canonical interactions."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from uuid import UUID

from nexuss.interactions.models import InteractionResponse


def default_interaction_database() -> Path:
    configured = os.environ.get(
        "NEXUSS_INTERACTION_DB",
        "",
    ).strip()

    if configured:
        return Path(configured).expanduser().resolve()

    local = os.environ.get("LOCALAPPDATA", "").strip()

    if local:
        return Path(local) / "Nexuss" / "interactions.sqlite3"

    return Path.home() / ".nexuss" / "interactions.sqlite3"


class SQLiteInteractionStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = (path or default_interaction_database()).resolve()
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
                CREATE TABLE IF NOT EXISTS interactions (
                    interaction_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL UNIQUE,
                    conversation_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS
                    idx_interactions_conversation
                ON interactions(
                    conversation_id,
                    updated_at DESC
                );
                """
            )

    def save(self, response: InteractionResponse) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO interactions (
                    interaction_id,
                    request_id,
                    conversation_id,
                    state,
                    response_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(request_id) DO UPDATE SET
                    interaction_id = excluded.interaction_id,
                    conversation_id = excluded.conversation_id,
                    state = excluded.state,
                    response_json = excluded.response_json,
                    updated_at = excluded.updated_at
                """,
                (
                    str(response.interaction_id),
                    str(response.request_id),
                    str(response.conversation_id),
                    response.state.value,
                    response.without_presentation().model_dump_json(),
                    response.created_at.isoformat(),
                    response.updated_at.isoformat(),
                ),
            )
            connection.execute("COMMIT")

    def get_by_request(
        self,
        request_id: UUID,
    ) -> InteractionResponse | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT response_json
                FROM interactions
                WHERE request_id = ?
                """,
                (str(request_id),),
            ).fetchone()

        if row is None:
            return None

        return InteractionResponse.model_validate_json(row[0])

    def get(
        self,
        interaction_id: UUID,
    ) -> InteractionResponse | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT response_json
                FROM interactions
                WHERE interaction_id = ?
                """,
                (str(interaction_id),),
            ).fetchone()

        if row is None:
            return None

        return InteractionResponse.model_validate_json(row[0])

    def recent(
        self,
        conversation_id: UUID,
        *,
        limit: int = 12,
    ) -> tuple[InteractionResponse, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT response_json
                FROM interactions
                WHERE conversation_id = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (str(conversation_id), limit),
            ).fetchall()

        return tuple(
            InteractionResponse.model_validate_json(row[0])
            for row in rows
        )
