from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from nexuss.conversation.models import (
    ConversationRecord,
    ConversationRoute,
    MessageRole,
    StoredConversationMessage,
)
from nexuss.interactions.journal import build_session_markdown
from nexuss.interactions.models import (
    InteractionEvent,
    InteractionKind,
    InteractionResponse,
    InteractionState,
)
from nexuss.interactions.store import SQLiteInteractionStore


def conversation_fixture() -> ConversationRecord:
    now = datetime.now(UTC)
    return ConversationRecord(
        conversation_id=uuid4(),
        user_session_id=uuid4(),
        title="Build Nexuss",
        provider_id="deepseek",
        model="deepseek-v4-pro",
        created_at=now,
        updated_at=now,
    )


def message_fixture(
    conversation_id,
    *,
    role: MessageRole,
    text: str,
    route: ConversationRoute | None = None,
) -> StoredConversationMessage:
    return StoredConversationMessage(
        message_id=uuid4(),
        conversation_id=conversation_id,
        role=role,
        text=text,
        route=route,
        provider_id=(
            "deepseek"
            if role is MessageRole.ASSISTANT
            else None
        ),
        model=(
            "deepseek-v4-pro"
            if role is MessageRole.ASSISTANT
            else None
        ),
        created_at=datetime.now(UTC),
    )


def test_session_journal_is_deterministic() -> None:
    conversation = conversation_fixture()
    messages = (
        message_fixture(
            conversation.conversation_id,
            role=MessageRole.USER,
            text="Design a unified interaction runtime.",
        ),
        message_fixture(
            conversation.conversation_id,
            role=MessageRole.ASSISTANT,
            text="I will keep chat and action state separate.",
            route=ConversationRoute.CHAT,
        ),
    )

    first_markdown, first_hash = build_session_markdown(
        conversation,
        messages,
    )
    second_markdown, second_hash = build_session_markdown(
        conversation,
        messages,
    )

    assert first_markdown == second_markdown
    assert first_hash == second_hash
    assert "Design a unified interaction runtime." in first_markdown
    assert len(first_hash) == 64


def test_interaction_store_roundtrip(tmp_path: Path) -> None:
    conversation = conversation_fixture()
    user_message = message_fixture(
        conversation.conversation_id,
        role=MessageRole.USER,
        text="Hello.",
    )
    assistant_message = message_fixture(
        conversation.conversation_id,
        role=MessageRole.ASSISTANT,
        text="Hello!",
        route=ConversationRoute.CHAT,
    )
    now = datetime.now(UTC)
    response = InteractionResponse(
        interaction_id=uuid4(),
        request_id=uuid4(),
        conversation_id=conversation.conversation_id,
        kind=InteractionKind.CHAT,
        state=InteractionState.RESPONDED,
        display_text="Hello!",
        provider_id="deepseek",
        model="deepseek-v4-pro",
        conversation=conversation,
        user_message=user_message,
        assistant_message=assistant_message,
        events=(
            InteractionEvent(
                sequence=1,
                event_type="interaction_received",
                state="received",
                detail="Received.",
                occurred_at=now,
            ),
        ),
        created_at=now,
        updated_at=now,
    )
    store = SQLiteInteractionStore(
        tmp_path / "interactions.sqlite3"
    )
    store.save(response)

    loaded = store.get(response.interaction_id)
    by_request = store.get_by_request(response.request_id)
    recent = store.recent(conversation.conversation_id)

    assert loaded == response
    assert by_request == response
    assert recent == (response,)
    assert loaded.internal_rewrite_shown_as_user is False
    assert loaded.menu_required is False
