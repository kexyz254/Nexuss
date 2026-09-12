"""Strict Nexuss-to-AI collaboration message contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProtocolSender(StrEnum):
    NEXUSS = "nexuss"
    PROVIDER = "provider"


class MessageKind(StrEnum):
    INTENT = "intent"
    CAPABILITY_LEASE = "capability_lease"
    ACTION_PLAN = "action_plan"
    EVIDENCE = "evidence"
    APPROVAL_STATE = "approval_state"
    REPLAN_REQUEST = "replan_request"
    FINAL_RESPONSE = "final_response"
    STOP = "stop"


class CollaborationState(StrEnum):
    OPEN = "open"
    WAITING_FOR_PROVIDER = "waiting_for_provider"
    WAITING_FOR_NEXUSS = "waiting_for_nexuss"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class IntentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    instruction: str = Field(min_length=1, max_length=20_000)
    instruction_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    privacy_classification: str = Field(min_length=1, max_length=40)
    maximum_rounds: int = Field(ge=1, le=20)
    maximum_actions_per_round: int = Field(ge=1, le=12)


class CapabilityLeaseEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_id: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[a-z][a-z0-9_.-]*$",
    )
    risk_tier: str
    approval_policy: str
    approval_channel: str | None = None
    execution_mode: str
    provider_can_request: bool
    provider_can_execute: Literal[False] = False


class CapabilityLeasePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    lease_id: UUID
    expires_at: datetime
    capabilities: tuple[CapabilityLeaseEntry, ...]


class RequestedActionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action_key: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_-]*$",
    )
    capability_id: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[a-z][a-z0-9_.-]*$",
    )
    arguments: dict[str, object] = Field(default_factory=dict)
    rationale: str = Field(min_length=1, max_length=2_000)
    expected_evidence: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()


class ActionPlanPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: str = Field(min_length=1, max_length=8_000)
    user_facing_response: str = Field(min_length=1, max_length=50_000)
    requested_actions: tuple[RequestedActionPayload, ...] = ()
    done: bool = False


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action_key: str
    capability_id: str
    status: str
    source: str
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_id: UUID | None = None
    summary: str = Field(min_length=1, max_length=8_000)


class EvidencePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[EvidenceItem, ...]
    all_items_verified: bool
    approval_required: bool = False
    approval_id: UUID | None = None


class ApprovalStatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    approval_id: UUID
    action_key: str
    state: str
    approval_channel: str
    exact_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    execution_occurred: bool = False


class FinalResponsePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    response: str = Field(min_length=1, max_length=50_000)
    verified_claims_only: bool
    unresolved_items: tuple[str, ...] = ()


class StopPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reason_code: str = Field(min_length=1, max_length=120)
    explanation: str = Field(min_length=1, max_length=4_000)


class ProtocolMessage(BaseModel):
    """One immutable, sequence-bound protocol turn."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_version: Literal["ncp/1.0"] = "ncp/1.0"
    message_id: UUID
    session_id: UUID
    request_id: UUID
    sender: ProtocolSender
    kind: MessageKind
    sequence: int = Field(ge=1)
    reply_to_message_id: UUID | None = None

    provider_id: str | None = None
    model: str | None = None

    issued_at: datetime
    expires_at: datetime
    nonce: UUID

    payload: dict[str, object]
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_message_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    message_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CollaborationSession(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: UUID
    request_id: UUID
    user_session_id: UUID
    provider_id: str
    model: str
    state: CollaborationState
    next_sequence: int = Field(ge=1)
    maximum_rounds: int = Field(ge=1, le=20)
    completed_rounds: int = Field(ge=0, le=20)
    last_message_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
