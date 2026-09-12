'''SQLite storage for bounded autonomy runs.'''

from __future__ import annotations

import sqlite3
from uuid import UUID

from nexuss.orchestration.autonomy_models import AutonomousRunResponse
from nexuss.orchestration.store import SQLiteOrchestrationStore


class SQLiteAutonomyStore:
    def __init__(self, planning_store: SQLiteOrchestrationStore) -> None:
        self._path = planning_store.path
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS autonomy_runs (
                    run_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL UNIQUE,
                    response_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=10.0, isolation_level=None)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def save(self, response: AutonomousRunResponse) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO autonomy_runs (
                    run_id, request_id, response_json, state, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(request_id) DO UPDATE SET
                    run_id=excluded.run_id,
                    response_json=excluded.response_json,
                    state=excluded.state,
                    updated_at=excluded.updated_at
                """,
                (
                    str(response.run_id),
                    str(response.request_id),
                    response.model_dump_json(),
                    response.state.value,
                    response.updated_at.isoformat(),
                ),
            )
            connection.execute("COMMIT")

    def get_by_request(self, request_id: UUID) -> AutonomousRunResponse | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT response_json FROM autonomy_runs WHERE request_id = ?",
                (str(request_id),),
            ).fetchone()
        return None if row is None else AutonomousRunResponse.model_validate_json(row[0])

    def get_by_run(self, run_id: UUID) -> AutonomousRunResponse | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT response_json FROM autonomy_runs WHERE run_id = ?",
                (str(run_id),),
            ).fetchone()
        return None if row is None else AutonomousRunResponse.model_validate_json(row[0])
