"""Natural-language schedule commands."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from nexuss.proactive.store import SQLiteProactiveStore

_REMIND_IN = re.compile(
    r"^remind\s+me\s+in\s+(\d+)\s+(minute|hour|day|week)s?\s+(?:to\s+)?(.+?)[.!]?$",
    re.IGNORECASE,
)
_REMIND_EVERY = re.compile(
    r"^remind\s+me\s+every\s+(\d+)\s+(minute|hour|day|week)s?\s+(?:to\s+)?(.+?)[.!]?$",
    re.IGNORECASE,
)
_LIST = re.compile(r"^(?:show|list)\s+(?:my\s+)?(?:reminders|schedules)[.!]?$", re.IGNORECASE)


@dataclass(frozen=True)
class LocalProactiveResponse:
    text: str
    model: str = "proactive-scheduler"


def _seconds(amount: int, unit: str) -> int:
    return {
        "minute": 60,
        "hour": 3600,
        "day": 86_400,
        "week": 604_800,
    }[unit.casefold()] * amount


class ProactiveCommandService:
    def __init__(self, store: SQLiteProactiveStore | None = None) -> None:
        self.store = store or SQLiteProactiveStore()

    def handle(
        self,
        text: str,
        *,
        conversation_id: UUID,
        user_session_id: UUID,
    ) -> LocalProactiveResponse | None:
        value = " ".join(text.split()).strip()
        if match := _REMIND_EVERY.match(value):
            interval = _seconds(int(match.group(1)), match.group(2))
            prompt = match.group(3).strip(" \"'.")
            record = self.store.create_schedule(
                conversation_id=conversation_id,
                user_session_id=user_session_id,
                title=prompt,
                prompt=prompt,
                next_run_at=datetime.now(UTC) + timedelta(seconds=interval),
                interval_seconds=interval,
            )
            return LocalProactiveResponse(
                f"Scheduled recurring reminder “{record.title}” every "
                f"{record.interval_seconds} seconds."
            )

        if match := _REMIND_IN.match(value):
            delay = _seconds(int(match.group(1)), match.group(2))
            prompt = match.group(3).strip(" \"'.")
            record = self.store.create_schedule(
                conversation_id=conversation_id,
                user_session_id=user_session_id,
                title=prompt,
                prompt=prompt,
                next_run_at=datetime.now(UTC) + timedelta(seconds=delay),
            )
            return LocalProactiveResponse(
                f"Reminder saved for {record.next_run_at.isoformat()}: “{record.title}”."
            )

        if _LIST.match(value):
            schedules = tuple(
                item for item in self.store.list_schedules(user_session_id)
                if item.status.value == "active"
            )
            if not schedules:
                return LocalProactiveResponse("You have no active reminders.")
            lines = [
                f"• {item.title} — next {item.next_run_at.isoformat()}"
                + (f" · every {item.interval_seconds}s" if item.interval_seconds else "")
                for item in schedules
            ]
            return LocalProactiveResponse("Active reminders:\n" + "\n".join(lines))

        return None
