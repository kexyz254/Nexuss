from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from nexuss.conversation.store import SQLiteConversationStore


def create_same_conversation(
    store: SQLiteConversationStore,
    *,
    conversation_id: UUID,
    session_id: UUID,
    token: str,
):
    return store.create(
        conversation_id=conversation_id,
        user_session_id=session_id,
        title="New conversation",
        provider_id="deepseek",
        model="deepseek-v4-pro",
        continuation_token=token,
    )


def count_conversations(database: Path, conversation_id: UUID) -> int:
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            """
            SELECT COUNT(*)
            FROM conversations
            WHERE conversation_id = ?
            """,
            (str(conversation_id),),
        ).fetchone()
    assert row is not None
    return int(row[0])


def test_concurrent_identical_creates_are_idempotent(
    tmp_path: Path,
) -> None:
    database = tmp_path / "concurrent-conversations.sqlite3"
    store = SQLiteConversationStore(database)
    conversation_id = uuid4()
    session_id = uuid4()
    token = "a" * 64

    with ThreadPoolExecutor(max_workers=12) as executor:
        records = list(
            executor.map(
                lambda _: create_same_conversation(
                    store,
                    conversation_id=conversation_id,
                    session_id=session_id,
                    token=token,
                ),
                range(24),
            )
        )

    assert {record.conversation_id for record in records} == {
        conversation_id
    }
    assert {record.user_session_id for record in records} == {
        session_id
    }
    assert count_conversations(database, conversation_id) == 1


def test_valid_token_rebinds_without_creating_duplicate(
    tmp_path: Path,
) -> None:
    database = tmp_path / "rebind-conversations.sqlite3"
    store = SQLiteConversationStore(database)
    conversation_id = uuid4()
    first_session = uuid4()
    second_session = uuid4()
    token = "b" * 64

    create_same_conversation(
        store,
        conversation_id=conversation_id,
        session_id=first_session,
        token=token,
    )
    rebound = create_same_conversation(
        store,
        conversation_id=conversation_id,
        session_id=second_session,
        token=token,
    )

    assert rebound.user_session_id == second_session
    assert store.get(conversation_id) == rebound
    assert count_conversations(database, conversation_id) == 1


def test_invalid_token_fails_closed_and_preserves_owner(
    tmp_path: Path,
) -> None:
    database = tmp_path / "protected-conversations.sqlite3"
    store = SQLiteConversationStore(database)
    conversation_id = uuid4()
    first_session = uuid4()
    attempted_session = uuid4()

    original = create_same_conversation(
        store,
        conversation_id=conversation_id,
        session_id=first_session,
        token="c" * 64,
    )

    with pytest.raises(
        PermissionError,
        match="continuation token is invalid",
    ):
        create_same_conversation(
            store,
            conversation_id=conversation_id,
            session_id=attempted_session,
            token="d" * 64,
        )

    preserved = store.get(conversation_id)
    assert preserved is not None
    assert preserved.user_session_id == original.user_session_id
    assert count_conversations(database, conversation_id) == 1
