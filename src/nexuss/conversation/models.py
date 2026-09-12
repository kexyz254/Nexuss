"""Strict persistent-conversation data contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ConversationRoute(StrEnum):
    CHAT = "chat"
    ACTION = "action"
    CLARIFICATION = "clarification"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class StoredConversationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    message_id: UUID
    conversation_id: UUID
    role: MessageRole
    text: str = Field(min_length=1, max_length=50_000)
    route: ConversationRoute | None = None
    provider_id: str | None = None
    model: str | None = None
    created_at: datetime


class ConversationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation_id: UUID
    user_session_id: UUID
    title: str = Field(min_length=1, max_length=160)
    provider_id: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=200)
    pending_action: str | None = Field(default=None, max_length=20_000)
    pending_capability_hint: str | None = Field(
        default=None,
        max_length=160,
    )
    created_at: datetime
    updated_at: datetime


class CreateConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    user_session_id: UUID
    provider_id: str = Field(default="auto", min_length=1, max_length=80)
    title: str = Field(
        default="New conversation",
        min_length=1,
        max_length=160,
    )
    continuation_token: str = Field(min_length=32, max_length=256)


class ConversationTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    user_session_id: UUID
    text: str = Field(min_length=1, max_length=20_000)
    provider_id: str = Field(default="auto", min_length=1, max_length=80)
    external_processing_approved: bool = True


class RouteClassification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    route: ConversationRoute
    response: str = Field(min_length=1, max_length=50_000)
    action_instruction: str | None = Field(
        default=None,
        max_length=20_000,
    )
    clarification_question: str | None = Field(
        default=None,
        max_length=500,
    )
    capability_hint: str | None = Field(
        default=None,
        max_length=160,
    )
    confidence: float = Field(ge=0.0, le=1.0)


class ConversationTurnResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation: ConversationRecord
    user_message: StoredConversationMessage
    assistant_message: StoredConversationMessage
    route: ConversationRoute
    action_instruction: str | None = None
    clarification_question: str | None = None
    capability_hint: str | None = None
    provider_id: str
    model: str
    persisted: bool = True
    menu_required: bool = False
    tools_executed: int = 0
    nexuss_retains_final_authority: bool = True


class ConversationHistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation: ConversationRecord
    messages: tuple[StoredConversationMessage, ...]
