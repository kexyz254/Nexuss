from __future__ import annotations

from uuid import uuid4

from nexuss.conversation.models import ConversationRoute
from nexuss.conversation.store import SQLiteConversationStore


def test_conversation_messages_persist_attachment_ids(tmp_path) -> None:
    store = SQLiteConversationStore(tmp_path / "conversation.sqlite3")
    conversation_id = uuid4()
    session_id = uuid4()
    attachment_id = uuid4()

    store.create(
        conversation_id=conversation_id,
        user_session_id=session_id,
        title="File chat",
        provider_id="auto",
        model="test",
        continuation_token="a" * 64,
    )
    store.append_turn(
        conversation_id=conversation_id,
        user_text="Summarize this file.",
        assistant_text="Summary",
        route=ConversationRoute.CHAT,
        provider_id="test",
        model="test",
        pending_action=None,
        pending_capability_hint=None,
        attachment_ids=(attachment_id,),
    )

    messages = store.messages(conversation_id)
    assert messages[0].attachment_ids == (attachment_id,)
    assert messages[1].attachment_ids == ()
