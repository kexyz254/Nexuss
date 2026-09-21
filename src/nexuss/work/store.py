"""SQLite-backed persistent project and work queue."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from nexuss.work.models import (
    ProjectRecord,
    ProjectStatus,
    WorkItemRecord,
    WorkPriority,
    WorkStatus,
)


def default_work_database() -> Path:
    configured = os.getenv("NEXUSS_WORK_DB", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    repository = os.getenv("NEXUSS_REPOSITORY_ROOT", "").strip()
    if repository:
        return (Path(repository) / ".nexuss-runtime" / "work.sqlite3").resolve()
    local = os.getenv("LOCALAPPDATA", "").strip()
    if local:
        return (Path(local) / "Nexuss" / "work.sqlite3").resolve()
    return (Path.home() / ".nexuss" / "work.sqlite3").resolve()


class WorkStoreError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class SQLiteWorkStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = (path or default_work_database()).resolve()
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
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    user_session_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_projects_session
                    ON projects(user_session_id, updated_at);

                CREATE TABLE IF NOT EXISTS work_items (
                    work_item_id TEXT PRIMARY KEY,
                    user_session_id TEXT NOT NULL,
                    conversation_id TEXT,
                    project_id TEXT,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    due_at TEXT,
                    dependency_ids TEXT NOT NULL,
                    resume_context TEXT NOT NULL,
                    deadline_alerted_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_work_items_session
                    ON work_items(user_session_id, status, updated_at);
                CREATE INDEX IF NOT EXISTS idx_work_items_due
                    ON work_items(due_at, deadline_alerted_at);
                """
            )

    def create_project(
        self,
        *,
        user_session_id: UUID,
        title: str,
        description: str = "",
    ) -> ProjectRecord:
        normalized = " ".join(title.split()).strip()
        if not normalized:
            raise WorkStoreError("WORK_PROJECT_TITLE_EMPTY", "Project title is required.")
        now = datetime.now(UTC)
        record = ProjectRecord(
            project_id=uuid4(),
            user_session_id=user_session_id,
            title=normalized,
            description=description.strip(),
            created_at=now,
            updated_at=now,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO projects (
                    project_id, user_session_id, title, description, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(record.project_id), str(user_session_id), record.title,
                    record.description, record.status.value,
                    record.created_at.isoformat(), record.updated_at.isoformat(),
                ),
            )
        return record

    @staticmethod
    def _project(row: tuple[object, ...]) -> ProjectRecord:
        return ProjectRecord(
            project_id=UUID(str(row[0])),
            user_session_id=UUID(str(row[1])),
            title=str(row[2]),
            description=str(row[3]),
            status=ProjectStatus(str(row[4])),
            created_at=datetime.fromisoformat(str(row[5])),
            updated_at=datetime.fromisoformat(str(row[6])),
        )

    def list_projects(self, user_session_id: UUID) -> tuple[ProjectRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT project_id, user_session_id, title, description, status,
                       created_at, updated_at
                FROM projects WHERE user_session_id = ?
                ORDER BY updated_at DESC
                """,
                (str(user_session_id),),
            ).fetchall()
        return tuple(self._project(row) for row in rows)

    def find_project(self, user_session_id: UUID, title: str) -> ProjectRecord | None:
        target = " ".join(title.split()).strip().casefold()
        return next(
            (item for item in self.list_projects(user_session_id) if item.title.casefold() == target),
            None,
        )

    def create_item(
        self,
        *,
        user_session_id: UUID,
        title: str,
        conversation_id: UUID | None = None,
        project_id: UUID | None = None,
        description: str = "",
        priority: WorkPriority = WorkPriority.NORMAL,
        due_at: datetime | None = None,
        dependency_ids: tuple[UUID, ...] = (),
        resume_context: str = "",
    ) -> WorkItemRecord:
        normalized = " ".join(title.split()).strip()
        if not normalized:
            raise WorkStoreError("WORK_ITEM_TITLE_EMPTY", "Work item title is required.")
        now = datetime.now(UTC)
        record = WorkItemRecord(
            work_item_id=uuid4(), user_session_id=user_session_id,
            conversation_id=conversation_id, project_id=project_id,
            title=normalized, description=description.strip(), priority=priority,
            due_at=due_at, dependency_ids=dependency_ids,
            resume_context=resume_context.strip(), created_at=now, updated_at=now,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO work_items (
                    work_item_id, user_session_id, conversation_id, project_id,
                    title, description, status, priority, due_at, dependency_ids,
                    resume_context, deadline_alerted_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    str(record.work_item_id), str(user_session_id),
                    str(conversation_id) if conversation_id else None,
                    str(project_id) if project_id else None,
                    record.title, record.description, record.status.value,
                    record.priority.value, due_at.isoformat() if due_at else None,
                    json.dumps([str(item) for item in dependency_ids]),
                    record.resume_context, now.isoformat(), now.isoformat(),
                ),
            )
        return record

    @staticmethod
    def _item(row: tuple[object, ...]) -> WorkItemRecord:
        return WorkItemRecord(
            work_item_id=UUID(str(row[0])),
            user_session_id=UUID(str(row[1])),
            conversation_id=UUID(str(row[2])) if row[2] else None,
            project_id=UUID(str(row[3])) if row[3] else None,
            title=str(row[4]), description=str(row[5]),
            status=WorkStatus(str(row[6])), priority=WorkPriority(str(row[7])),
            due_at=datetime.fromisoformat(str(row[8])) if row[8] else None,
            dependency_ids=tuple(UUID(str(item)) for item in json.loads(str(row[9]))),
            resume_context=str(row[10]),
            created_at=datetime.fromisoformat(str(row[11])),
            updated_at=datetime.fromisoformat(str(row[12])),
        )

    def list_items(
        self,
        user_session_id: UUID,
        *,
        project_id: UUID | None = None,
        include_terminal: bool = True,
    ) -> tuple[WorkItemRecord, ...]:
        query = """
            SELECT work_item_id, user_session_id, conversation_id, project_id,
                   title, description, status, priority, due_at, dependency_ids,
                   resume_context, created_at, updated_at
            FROM work_items WHERE user_session_id = ?
        """
        parameters: list[str] = [str(user_session_id)]
        if project_id is not None:
            query += " AND project_id = ?"
            parameters.append(str(project_id))
        if not include_terminal:
            query += " AND status NOT IN ('completed', 'cancelled')"
        query += " ORDER BY updated_at DESC"
        with self._connect() as connection:
            rows = connection.execute(query, tuple(parameters)).fetchall()
        return tuple(self._item(row) for row in rows)

    def find_item(self, user_session_id: UUID, title: str) -> WorkItemRecord | None:
        target = " ".join(title.split()).strip().casefold()
        return next(
            (item for item in self.list_items(user_session_id) if item.title.casefold() == target),
            None,
        )

    def update_status(
        self,
        *,
        user_session_id: UUID,
        work_item_id: UUID,
        status: WorkStatus,
    ) -> WorkItemRecord:
        now = datetime.now(UTC)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE work_items SET status = ?, updated_at = ?
                WHERE work_item_id = ? AND user_session_id = ?
                """,
                (status.value, now.isoformat(), str(work_item_id), str(user_session_id)),
            )
            if cursor.rowcount != 1:
                raise WorkStoreError("WORK_ITEM_NOT_FOUND", "Work item was not found.")
        item = next(
            item for item in self.list_items(user_session_id)
            if item.work_item_id == work_item_id
        )
        return item

    def claim_due_deadlines(self, now: datetime) -> tuple[WorkItemRecord, ...]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT work_item_id, user_session_id, conversation_id, project_id,
                       title, description, status, priority, due_at, dependency_ids,
                       resume_context, created_at, updated_at
                FROM work_items
                WHERE due_at IS NOT NULL
                  AND due_at <= ?
                  AND deadline_alerted_at IS NULL
                  AND status NOT IN ('completed', 'cancelled')
                """,
                (now.isoformat(),),
            ).fetchall()
            ids = [str(row[0]) for row in rows]
            if ids:
                connection.executemany(
                    "UPDATE work_items SET deadline_alerted_at = ? WHERE work_item_id = ?",
                    [(now.isoformat(), item_id) for item_id in ids],
                )
            connection.commit()
        return tuple(self._item(row) for row in rows)
