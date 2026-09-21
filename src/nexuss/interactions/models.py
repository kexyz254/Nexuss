"""Contracts for one canonical Nexuss interaction."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from nexuss.conversation.models import (
    ConversationRecord,
    StoredConversationMessage,
)
from nexuss.domain.models import ActionReceipt, TaskView


class InteractionKind(StrEnum):
    CHAT = "chat"
    WORKFLOW = "workflow"
    ACTION = "action"
    CLARIFICATION = "clarification"


class InteractionState(StrEnum):
    RECEIVED = "received"
    RESPONDED = "responded"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    DENIED = "denied"


class InteractionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(ge=1)
    event_type: str = Field(min_length=1, max_length=120)
    state: str = Field(min_length=1, max_length=80)
    detail: str = Field(min_length=1, max_length=2_000)
    occurred_at: datetime


class InteractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    conversation_id: UUID
    user_session_id: UUID
    text: str = Field(min_length=1, max_length=20_000)
    provider_id: str = Field(default="auto", min_length=1, max_length=80)
    external_processing_approved: bool = True


# P6.10D EPHEMERAL PRESENTATION HYDRATION
class InteractionPresentation(BaseModel):
    """Non-durable task data required by the existing P5 UI."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task: TaskView
    receipt: ActionReceipt | None = None


class InteractionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    interaction_id: UUID
    request_id: UUID
    conversation_id: UUID
    kind: InteractionKind
    state: InteractionState

    display_text: str = Field(min_length=1, max_length=50_000)
    resolved_instruction: str | None = Field(
        default=None,
        max_length=20_000,
    )
    capability_hint: str | None = Field(default=None, max_length=160)

    provider_id: str
    model: str

    core_task_id: UUID | None = None
    core_task_state: str | None = None
    approval_required: bool = False
    approval_id: UUID | None = None
    receipt_id: UUID | None = None
    evidence_count: int = 0
    presentation: InteractionPresentation | None = None

    conversation: ConversationRecord
    user_message: StoredConversationMessage
    assistant_message: StoredConversationMessage
    events: tuple[InteractionEvent, ...]

    internal_rewrite_shown_as_user: bool = False
    menu_required: bool = False
    nexuss_retains_final_authority: bool = True
    created_at: datetime
    updated_at: datetime

    def without_presentation(self) -> "InteractionResponse":
        """Remove ephemeral approval tokens and task evidence."""

        return self.model_copy(update={"presentation": None})


class SaveConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    user_session_id: UUID
    note_title: str | None = Field(default=None, max_length=160)


class SaveConversationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation_id: UUID
    note_title: str
    transcript_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    core_task_id: UUID
    core_task_state: str
    approval_required: bool
    approval_id: UUID | None = None
    receipt_id: UUID | None = None
    presentation: InteractionPresentation | None = None
    auto_saved_locally: bool = True
    promoted_to_memory: bool = False
    promoted_to_managed_note: bool = False
    nexuss_retains_final_authority: bool = True
