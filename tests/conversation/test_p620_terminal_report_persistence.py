from __future__ import annotations

from uuid import uuid4

from nexuss.conversation.models import (
    ConversationRoute,
    MessageRole,
)
from nexuss.conversation.store import SQLiteConversationStore


def test_terminal_report_replaces_provisional_assistant_text(tmp_path) -> None:
    store = SQLiteConversationStore(tmp_path / "conversation.sqlite3")
    conversation_id = uuid4()
    session_id = uuid4()

    store.create(
        conversation_id=conversation_id,
        user_session_id=session_id,
        title="Lifecycle",
        provider_id="auto",
        model="test",
        continuation_token="a" * 64,
    )
    _, assistant, _ = store.append_turn(
        conversation_id=conversation_id,
        user_text="Check for Nexuss updates.",
        assistant_text="I will check for Nexuss updates now.",
        route=ConversationRoute.ACTION,
        provider_id="nexuss",
        model="test",
        pending_action=None,
        pending_capability_hint=None,
    )

    updated = store.update_message_text(
        conversation_id=conversation_id,
        message_id=assistant.message_id,
        text="Nexuss is up to date. No update is required.",
    )

    assert updated.role is MessageRole.ASSISTANT
    assert "up to date" in updated.text
    messages = store.messages(conversation_id)
    assert messages[-1].text == updated.text
