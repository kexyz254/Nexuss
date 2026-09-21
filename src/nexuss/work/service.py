"""Natural-language local work command handling."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from nexuss.work.models import WorkStatus
from nexuss.work.store import SQLiteWorkStore, WorkStoreError

_CREATE_PROJECT = re.compile(r"^(?:create|start)\s+(?:a\s+)?project(?:\s+(?:called|named))?\s+(.+?)[.!]?$", re.IGNORECASE)
_ADD_TASK = re.compile(r"^add\s+(?:a\s+)?task\s+(.+?)\s+to\s+project\s+(.+?)[.!]?$", re.IGNORECASE)
_LIST_PROJECTS = re.compile(r"^(?:show|list)\s+(?:my\s+)?projects?[.!]?$", re.IGNORECASE)
_LIST_TASKS = re.compile(r"^(?:show|list)\s+(?:my\s+)?(?:tasks|work(?:\s+queue)?)(?:\s+(?:for|in)\s+project\s+(.+?))?[.!]?$", re.IGNORECASE)
_COMPLETE_TASK = re.compile(r"^(?:complete|finish|done with)\s+task\s+(.+?)[.!]?$", re.IGNORECASE)
_START_TASK = re.compile(r"^(?:start|resume)\s+task\s+(.+?)[.!]?$", re.IGNORECASE)
_DUE = re.compile(r"\s+due\s+in\s+(\d+)\s+(minute|hour|day|week)s?\b", re.IGNORECASE)


@dataclass(frozen=True)
class LocalWorkResponse:
    text: str
    model: str = "persistent-work-engine"


def _future_due(text: str) -> tuple[str, datetime | None]:
    match = _DUE.search(text)
    if match is None:
        return text.strip(), None
    amount = int(match.group(1))
    unit = match.group(2).casefold()
    delta = {
        "minute": timedelta(minutes=amount),
        "hour": timedelta(hours=amount),
        "day": timedelta(days=amount),
        "week": timedelta(weeks=amount),
    }[unit]
    cleaned = (text[:match.start()] + text[match.end():]).strip()
    return cleaned, datetime.now(UTC) + delta


class WorkCommandService:
    def __init__(self, store: SQLiteWorkStore | None = None) -> None:
        self.store = store or SQLiteWorkStore()

    def handle(
        self,
        text: str,
        *,
        conversation_id: UUID,
        user_session_id: UUID,
    ) -> LocalWorkResponse | None:
        value = " ".join(text.split()).strip()
        if match := _CREATE_PROJECT.match(value):
            record = self.store.create_project(
                user_session_id=user_session_id,
                title=match.group(1).strip(" \"'."),
            )
            return LocalWorkResponse(f"Created project “{record.title}”.")

        if match := _ADD_TASK.match(value):
            raw_title, due_at = _future_due(match.group(1))
            project_name = match.group(2).strip(" \"'.")
            project = self.store.find_project(user_session_id, project_name)
            if project is None:
                raise WorkStoreError(
                    "WORK_PROJECT_NOT_FOUND",
                    f"Project “{project_name}” was not found.",
                )
            item = self.store.create_item(
                user_session_id=user_session_id,
                conversation_id=conversation_id,
                project_id=project.project_id,
                title=raw_title.strip(" \"'."),
                due_at=due_at,
            )
            due = f" Due {item.due_at.isoformat()}." if item.due_at else ""
            return LocalWorkResponse(f"Added task “{item.title}” to “{project.title}”.{due}")

        if _LIST_PROJECTS.match(value):
            projects = self.store.list_projects(user_session_id)
            if not projects:
                return LocalWorkResponse("You have no saved projects yet.")
            summary = "\n".join(f"• {item.title} — {item.status.value}" for item in projects)
            return LocalWorkResponse("Projects:\n" + summary)

        if match := _LIST_TASKS.match(value):
            project_id = None
            project_label = ""
            if match.group(1):
                project = self.store.find_project(user_session_id, match.group(1).strip(" \"'."))
                if project is None:
                    raise WorkStoreError("WORK_PROJECT_NOT_FOUND", "That project was not found.")
                project_id = project.project_id
                project_label = f" for “{project.title}”"
            items = self.store.list_items(user_session_id, project_id=project_id, include_terminal=False)
            if not items:
                return LocalWorkResponse(f"No active work items{project_label}.")
            lines = []
            for item in items:
                due = f" · due {item.due_at.isoformat()}" if item.due_at else ""
                lines.append(f"• {item.title} — {item.status.value}{due}")
            return LocalWorkResponse(f"Active work{project_label}:\n" + "\n".join(lines))

        if match := _COMPLETE_TASK.match(value):
            item = self.store.find_item(user_session_id, match.group(1).strip(" \"'."))
            if item is None:
                raise WorkStoreError("WORK_ITEM_NOT_FOUND", "That work item was not found.")
            updated = self.store.update_status(
                user_session_id=user_session_id,
                work_item_id=item.work_item_id,
                status=WorkStatus.COMPLETED,
            )
            return LocalWorkResponse(f"Completed task “{updated.title}”.")

        if match := _START_TASK.match(value):
            item = self.store.find_item(user_session_id, match.group(1).strip(" \"'."))
            if item is None:
                raise WorkStoreError("WORK_ITEM_NOT_FOUND", "That work item was not found.")
            updated = self.store.update_status(
                user_session_id=user_session_id,
                work_item_id=item.work_item_id,
                status=WorkStatus.IN_PROGRESS,
            )
            return LocalWorkResponse(f"Task “{updated.title}” is now in progress.")

        return None
