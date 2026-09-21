from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from nexuss.work.models import WorkStatus
from nexuss.work.service import WorkCommandService
from nexuss.work.store import SQLiteWorkStore


def test_project_task_and_resume_state_are_persistent(tmp_path) -> None:
    store = SQLiteWorkStore(tmp_path / "work.sqlite3")
    session_id = uuid4()
    conversation_id = uuid4()
    project = store.create_project(
        user_session_id=session_id,
        title="Nexuss",
    )
    item = store.create_item(
        user_session_id=session_id,
        conversation_id=conversation_id,
        project_id=project.project_id,
        title="Build work engine",
        resume_context="Continue from the verified P6.18 base.",
        dependency_ids=(uuid4(),),
    )

    reloaded = SQLiteWorkStore(tmp_path / "work.sqlite3")
    items = reloaded.list_items(session_id)

    assert items[0].work_item_id == item.work_item_id
    assert items[0].resume_context.startswith("Continue")
    assert len(items[0].dependency_ids) == 1

    completed = reloaded.update_status(
        user_session_id=session_id,
        work_item_id=item.work_item_id,
        status=WorkStatus.COMPLETED,
    )
    assert completed.status is WorkStatus.COMPLETED


def test_due_deadline_is_claimed_once(tmp_path) -> None:
    store = SQLiteWorkStore(tmp_path / "work.sqlite3")
    session_id = uuid4()
    item = store.create_item(
        user_session_id=session_id,
        conversation_id=uuid4(),
        title="Deadline",
        due_at=datetime.now(UTC) - timedelta(minutes=1),
    )

    first = store.claim_due_deadlines(datetime.now(UTC))
    second = store.claim_due_deadlines(datetime.now(UTC))

    assert [entry.work_item_id for entry in first] == [item.work_item_id]
    assert second == ()


def test_natural_work_commands_manage_project_queue(tmp_path) -> None:
    service = WorkCommandService(
        SQLiteWorkStore(tmp_path / "work.sqlite3")
    )
    session_id = uuid4()
    conversation_id = uuid4()

    created = service.handle(
        "Create project called Launch",
        conversation_id=conversation_id,
        user_session_id=session_id,
    )
    added = service.handle(
        "Add task publish release notes due in 2 hours to project Launch",
        conversation_id=conversation_id,
        user_session_id=session_id,
    )
    listed = service.handle(
        "Show my work queue",
        conversation_id=conversation_id,
        user_session_id=session_id,
    )

    assert created is not None and "Launch" in created.text
    assert added is not None and "publish release notes" in added.text
    assert listed is not None and "publish release notes" in listed.text
