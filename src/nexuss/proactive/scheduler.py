"""Bounded local scheduler for reminders and work-deadline alerts."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import Event, Lock, Thread
from uuid import UUID

from nexuss.conversation.models import ConversationRoute, MessageRole
from nexuss.conversation.store import SQLiteConversationStore
from nexuss.proactive.store import SQLiteProactiveStore
from nexuss.work.store import SQLiteWorkStore


class ProactiveScheduler:
    def __init__(
        self,
        *,
        proactive_store: SQLiteProactiveStore | None = None,
        work_store: SQLiteWorkStore | None = None,
        conversation_store: SQLiteConversationStore | None = None,
        poll_seconds: float = 5.0,
    ) -> None:
        self._proactive = proactive_store or SQLiteProactiveStore()
        self._work = work_store or SQLiteWorkStore()
        self._conversations = conversation_store or SQLiteConversationStore()
        self._poll_seconds = max(1.0, poll_seconds)
        self._stop = Event()
        self._lock = Lock()
        self._thread: Thread | None = None

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = Thread(
                target=self._loop,
                name="nexuss-proactive-scheduler",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)

    def _loop(self) -> None:
        while not self._stop.wait(self._poll_seconds):
            self.run_once()

    def run_once(self, now: datetime | None = None) -> int:
        observed = now or datetime.now(UTC)
        emitted = 0

        for schedule in self._proactive.claim_due(observed):
            detail = f"Reminder: {schedule.prompt}"
            if self._emit(
                conversation_id=schedule.conversation_id,
                user_session_id=schedule.user_session_id,
                source_type="schedule",
                source_id=schedule.schedule_id,
                title=schedule.title,
                detail=detail,
                fired_at=observed,
            ):
                emitted += 1

        for item in self._work.claim_due_deadlines(observed):
            if item.conversation_id is None:
                continue
            detail = f"Work deadline reached: {item.title}"
            if self._emit(
                conversation_id=item.conversation_id,
                user_session_id=item.user_session_id,
                source_type="work_deadline",
                source_id=item.work_item_id,
                title=item.title,
                detail=detail,
                fired_at=observed,
            ):
                emitted += 1

        return emitted

    def _emit(
        self,
        *,
        conversation_id: UUID,
        user_session_id: UUID,
        source_type: str,
        source_id: UUID,
        title: str,
        detail: str,
        fired_at: datetime,
    ) -> bool:
        conversation = self._conversations.get(conversation_id)
        if (
            conversation is None
            or conversation.user_session_id != user_session_id
        ):
            return False

        self._proactive.create_alert(
            conversation_id=conversation_id,
            user_session_id=user_session_id,
            source_type=source_type,
            source_id=source_id,
            title=title,
            detail=detail,
            fired_at=fired_at,
        )
        self._conversations.append_message(
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            text=detail,
            route=ConversationRoute.CHAT,
            provider_id="nexuss",
            model="proactive-scheduler",
        )
        return True
