from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from nexuss.conversation.models import MessageRole
from nexuss.conversation.store import SQLiteConversationStore
from nexuss.proactive.scheduler import ProactiveScheduler
from nexuss.proactive.service import ProactiveCommandService
from nexuss.proactive.store import SQLiteProactiveStore
from nexuss.work.store import SQLiteWorkStore


def _conversation(store, conversation_id, session_id) -> None:
    store.create(
        conversation_id=conversation_id,
        user_session_id=session_id,
        title="Alerts",
        provider_id="auto",
        model="test",
        continuation_token="a" * 64,
    )


def test_scheduler_fires_reminder_into_conversation(tmp_path) -> None:
    conversations = SQLiteConversationStore(tmp_path / "conversation.sqlite3")
    proactive = SQLiteProactiveStore(tmp_path / "proactive.sqlite3")
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    session_id = uuid4()
    conversation_id = uuid4()
    _conversation(conversations, conversation_id, session_id)

    now = datetime.now(UTC)
    proactive.create_schedule(
        conversation_id=conversation_id,
        user_session_id=session_id,
        title="Check TAS",
        prompt="Check TAS health",
        next_run_at=now - timedelta(seconds=1),
    )

    scheduler = ProactiveScheduler(
        proactive_store=proactive,
        work_store=work,
        conversation_store=conversations,
        poll_seconds=1,
    )

    assert scheduler.run_once(now) == 1
    alerts = proactive.unacknowledged_alerts(session_id)
    messages = conversations.messages(conversation_id)

    assert len(alerts) == 1
    assert alerts[0].detail == "Reminder: Check TAS health"
    assert messages[-1].role is MessageRole.ASSISTANT
    assert "Check TAS health" in messages[-1].text


def test_scheduler_emits_due_work_deadline(tmp_path) -> None:
    conversations = SQLiteConversationStore(tmp_path / "conversation.sqlite3")
    proactive = SQLiteProactiveStore(tmp_path / "proactive.sqlite3")
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    session_id = uuid4()
    conversation_id = uuid4()
    _conversation(conversations, conversation_id, session_id)

    now = datetime.now(UTC)
    item = work.create_item(
        user_session_id=session_id,
        conversation_id=conversation_id,
        title="Ship release",
        due_at=now - timedelta(seconds=1),
    )

    scheduler = ProactiveScheduler(
        proactive_store=proactive,
        work_store=work,
        conversation_store=conversations,
    )
    assert scheduler.run_once(now) == 1
    alert = proactive.unacknowledged_alerts(session_id)[0]
    assert alert.source_id == item.work_item_id
    assert alert.source_type == "work_deadline"


def test_natural_recurring_reminder_is_persisted(tmp_path) -> None:
    service = ProactiveCommandService(
        SQLiteProactiveStore(tmp_path / "proactive.sqlite3")
    )
    session_id = uuid4()
    conversation_id = uuid4()

    response = service.handle(
        "Remind me every 2 hours to review market intelligence",
        conversation_id=conversation_id,
        user_session_id=session_id,
    )
    schedules = service.store.list_schedules(session_id)

    assert response is not None
    assert len(schedules) == 1
    assert schedules[0].interval_seconds == 7200
