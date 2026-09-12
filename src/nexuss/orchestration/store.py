"""SQLite-backed canonical storage for orchestration plans."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from uuid import UUID

from nexuss.orchestration.models import UniversalActionPlanResponse


def _default_database_path() -> Path:
    configured = os.environ.get("NEXUSS_ORCHESTRATION_DB", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()

    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / "Nexuss" / "orchestration.sqlite3"

    return Path.home() / ".nexuss" / "orchestration.sqlite3"


class SQLiteOrchestrationStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = (path or _default_database_path()).resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

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

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS action_plans (
                    request_id TEXT PRIMARY KEY,
                    receipt_id TEXT NOT NULL UNIQUE,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def save(self, response: UniversalActionPlanResponse) -> None:
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO action_plans (
                        request_id,
                        receipt_id,
                        response_json,
                        created_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        str(response.receipt.request_id),
                        str(response.receipt.receipt_id),
                        response.model_dump_json(),
                        response.receipt.created_at.isoformat(),
                    ),
                )
                connection.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            raise RuntimeError(
                "An orchestration plan already exists for this request."
            ) from exc

    def get_by_request(
        self,
        request_id: UUID,
    ) -> UniversalActionPlanResponse | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT response_json FROM action_plans WHERE request_id = ?",
                (str(request_id),),
            ).fetchone()
        if row is None:
            return None
        return UniversalActionPlanResponse.model_validate_json(row[0])

    def get_by_receipt(
        self,
        receipt_id: UUID,
    ) -> UniversalActionPlanResponse | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT response_json FROM action_plans WHERE receipt_id = ?",
                (str(receipt_id),),
            ).fetchone()
        if row is None:
            return None
        return UniversalActionPlanResponse.model_validate_json(row[0])
