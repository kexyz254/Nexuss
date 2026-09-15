from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from nexuss.conversation.models import MessageRole
from nexuss.conversation.store import SQLiteConversationStore


def _create(
    store: SQLiteConversationStore,
    session_id,
    title: str,
):
    return store.create(
        conversation_id=uuid4(),
        user_session_id=session_id,
        title=title,
        provider_id="deepseek",
        model="deepseek-v4-pro",
        continuation_token=uuid4().hex + uuid4().hex,
    )


def test_multi_chat_list_rename_and_delete(
    tmp_path: Path,
) -> None:
    store = SQLiteConversationStore(
        tmp_path / "multi-chat.sqlite3"
    )
    owner = uuid4()
    other = uuid4()

    first = _create(store, owner, "First chat")
    second = _create(store, owner, "Second chat")
    outsider = _create(store, other, "Other session")

    store.append_message(
        conversation_id=first.conversation_id,
        role=MessageRole.USER,
        text="Bring this chat to the top.",
    )

    listed = store.list_for_session(owner)

    assert [
        item.conversation_id
        for item in listed
    ] == [
        first.conversation_id,
        second.conversation_id,
    ]

    assert outsider.conversation_id not in {
        item.conversation_id
        for item in listed
    }

    renamed = store.rename(
        second.conversation_id,
        title="  Planning   workspace  ",
    )

    assert renamed is not None
    assert renamed.title == "Planning workspace"

    store.append_message(
        conversation_id=second.conversation_id,
        role=MessageRole.USER,
        text="This message should be cascade-deleted.",
    )

    assert store.messages(second.conversation_id)

    assert store.delete(second.conversation_id) is True
    assert store.get(second.conversation_id) is None
    assert store.messages(second.conversation_id) == ()
    assert store.delete(second.conversation_id) is False
