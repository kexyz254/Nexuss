from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from nexuss.conversation.models import (
    ConversationRoute,
    MessageRole,
)
from nexuss.conversation.router import (
    ConversationRouterService,
    ConversationRoutingError,
)
from nexuss.conversation.store import SQLiteConversationStore
from nexuss.engineering.models import ModelProposal


def proposer(payload: dict[str, object]):
    return lambda _request: ModelProposal(
        summary="Conversation route.",
        tool_requests=(),
        done=True,
        completion_message=json.dumps(payload),
    )


def test_chat_replies_directly_without_menu() -> None:
    service = ConversationRouterService(
        provider_id="deepseek",
        model="deepseek-v4-pro",
        proposer=proposer(
            {
                "route": "chat",
                "response": "Today is Saturday.",
                "action_instruction": None,
                "clarification_question": None,
                "capability_hint": None,
                "confidence": 0.99,
            }
        ),
    )

    result = service.route(
        user_text="What day is today?",
        conversation_context="",
        pending_action=None,
        pending_capability_hint=None,
    )

    assert result.route is ConversationRoute.CHAT
    assert result.action_instruction is None


def test_ready_action_returns_exact_instruction() -> None:
    service = ConversationRouterService(
        provider_id="deepseek",
        model="deepseek-v4-pro",
        proposer=proposer(
            {
                "route": "action",
                "response": "I will route that through Nexuss.",
                "action_instruction": "List my GitHub repositories.",
                "clarification_question": None,
                "capability_hint": "github.repositories.list",
                "confidence": 0.98,
            }
        ),
    )

    result = service.route(
        user_text="Check my GitHub repositories.",
        conversation_context="",
        pending_action=None,
        pending_capability_hint=None,
    )

    assert result.route is ConversationRoute.ACTION
    assert result.action_instruction == (
        "List my GitHub repositories."
    )


def test_action_clarification_is_one_question() -> None:
    service = ConversationRouterService(
        provider_id="deepseek",
        model="deepseek-v4-pro",
        proposer=proposer(
            {
                "route": "clarification",
                "response": "Which repository should I inspect?",
                "action_instruction": None,
                "clarification_question": (
                    "Which repository should I inspect?"
                ),
                "capability_hint": "github.repository.inspect",
                "confidence": 0.95,
            }
        ),
    )

    result = service.route(
        user_text="Inspect the repository.",
        conversation_context="",
        pending_action=None,
        pending_capability_hint=None,
    )

    assert result.route is ConversationRoute.CLARIFICATION
    assert "Which repository" in (
        result.clarification_question or ""
    )


def test_invalid_chat_action_mix_is_rejected() -> None:
    service = ConversationRouterService(
        provider_id="deepseek",
        model="deepseek-v4-pro",
        proposer=proposer(
            {
                "route": "chat",
                "response": "Hello.",
                "action_instruction": "Launch Notepad.",
                "clarification_question": None,
                "capability_hint": None,
                "confidence": 0.5,
            }
        ),
    )

    with pytest.raises(
        ConversationRoutingError,
        match="cannot include action fields",
    ):
        service.route(
            user_text="Hello",
            conversation_context="",
            pending_action=None,
            pending_capability_hint=None,
        )


def test_conversation_persists_across_store_instances(
    tmp_path: Path,
) -> None:
    database = tmp_path / "conversations.sqlite3"
    conversation_id = uuid4()
    user_session_id = uuid4()

    first = SQLiteConversationStore(database)
    first.create(
        conversation_id=conversation_id,
        user_session_id=user_session_id,
        title="New conversation",
        provider_id="deepseek",
        model="deepseek-v4-pro",
        continuation_token="x" * 64,
    )
    first.append_message(
        conversation_id=conversation_id,
        role=MessageRole.USER,
        text="Remember this turn.",
    )

    second = SQLiteConversationStore(database)
    history = second.messages(conversation_id)

    assert len(history) == 1
    assert history[0].text == "Remember this turn."



def test_router_uses_engineering_transport_completion_message() -> None:
    inner = {
        "route": "chat",
        "response": "Hello from the persisted conversation.",
        "action_instruction": None,
        "clarification_question": None,
        "capability_hint": None,
        "confidence": 1.0,
    }

    service = ConversationRouterService(
        provider_id="deepseek",
        model="deepseek-v4-pro",
        proposer=lambda _request: ModelProposal(
            summary="conversation route",
            tool_requests=(),
            done=True,
            completion_message=json.dumps(inner),
        ),
    )

    result = service.route(
        user_text="Hello",
        conversation_context="",
        pending_action=None,
        pending_capability_hint=None,
    )

    assert result.route is ConversationRoute.CHAT
    assert result.response.startswith("Hello")


def test_failed_classification_does_not_require_persistence(
    tmp_path: Path,
) -> None:
    database = tmp_path / "atomic-turn.sqlite3"
    conversation_id = uuid4()
    user_session_id = uuid4()
    store = SQLiteConversationStore(database)
    store.create(
        conversation_id=conversation_id,
        user_session_id=user_session_id,
        title="New conversation",
        provider_id="deepseek",
        model="deepseek-v4-pro",
        continuation_token="y" * 64,
    )

    assert store.messages(conversation_id) == ()
