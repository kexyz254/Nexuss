"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Typed contracts for the P6.7A trusted mobile communication fabric.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MobileSource(StrEnum):
    PHONE = "phone"
    SMS = "sms"
    WHATSAPP = "whatsapp"
    INSTAGRAM = "instagram"
    FACEBOOK_LITE = "facebook_lite"
    OTHER = "other"


class MobileSignalKind(StrEnum):
    MESSAGE_RECEIVED = "message_received"
    MESSAGE_SENT = "message_sent"
    MISSED_CALL = "missed_call"
    INCOMING_CALL = "incoming_call"
    OUTGOING_CALL = "outgoing_call"
    APP_NOTIFICATION = "app_notification"
    SHARED_CONTENT = "shared_content"


class MobileActionKind(StrEnum):
    DIAL_HANDOFF = "dial_handoff"
    SMS_COMPOSE = "sms_compose"
    NOTIFICATION_REPLY = "notification_reply"
    OPEN_CONVERSATION = "open_conversation"


class MobileActionState(StrEnum):
    PREPARED = "prepared"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    DISPATCHED = "dispatched"
    VERIFIED = "verified"
    FAILED = "failed"


class MobileDecisionKind(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class MobileSignal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    event_id: UUID = Field(default_factory=uuid4)
    source: MobileSource
    package_name: str = Field(min_length=1, max_length=180)
    kind: MobileSignalKind
    occurred_at: datetime
    sender_label: str | None = Field(default=None, max_length=200)
    conversation_label: str | None = Field(default=None, max_length=240)
    text: str | None = Field(default=None, max_length=4_000)
    notification_key: str | None = Field(default=None, max_length=500)
    reply_supported: bool = False
    sensitive: bool = False
    metadata: dict[str, str | int | bool | float | None] = Field(default_factory=dict)
    content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("occurred_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        return value.astimezone(UTC)


class MobileSignalBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    batch_id: UUID = Field(default_factory=uuid4)
    sequence: int = Field(ge=1)
    device_time: datetime
    batch_nonce: str = Field(min_length=32, max_length=128)
    signals: tuple[MobileSignal, ...] = Field(min_length=1, max_length=100)

    @field_validator("device_time")
    @classmethod
    def device_time_timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("device_time must be timezone-aware")
        return value.astimezone(UTC)


class MobileSignalIngestResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    batch_id: UUID
    accepted: int = Field(ge=0)
    duplicates: int = Field(ge=0)
    rejected: int = Field(ge=0)
    latest_cursor: int = Field(ge=0)
    device_id: UUID
    external_write_performed: bool = False
    credentials_exposed: bool = False


class MobileFeedItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cursor: int = Field(ge=1)
    device_id: UUID
    signal: MobileSignal
    observed_at: datetime


class MobileFeedSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[MobileFeedItem, ...]
    latest_cursor: int = Field(ge=0)
    total_available: int = Field(ge=0)
    sources: tuple[MobileSource, ...]
    read_only: bool = True
    external_write_performed: bool = False


class MobileAttentionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    total_signals: int = Field(ge=0)
    unread_like_messages: int = Field(ge=0)
    missed_calls: int = Field(ge=0)
    reply_capable_notifications: int = Field(ge=0)
    source_counts: dict[MobileSource, int]
    latest_items: tuple[MobileFeedItem, ...]
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    read_only: bool = True


class MobileCapabilityStatus(StrEnum):
    ACTIVE = "active"
    CONDITIONAL = "conditional"
    BLOCKED = "blocked"


class MobileCapabilityEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_id: str = Field(pattern=r"^mobile\.[a-z0-9_.-]+$")
    title: str
    status: MobileCapabilityStatus
    approval_required: bool
    limitation: str | None = None


class MobileCapabilityMatrix(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    device_trust_model: str
    read_sources: tuple[MobileSource, ...]
    capabilities: tuple[MobileCapabilityEntry, ...]
    accessibility_automation_enabled: bool = False
    private_app_database_access: bool = False
    call_audio_recording: bool = False
    external_write_authority_added: bool = False


class MobileActionPrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    request_id: UUID = Field(default_factory=uuid4)
    device_id: UUID
    kind: MobileActionKind
    source: MobileSource
    target_label: str = Field(min_length=1, max_length=240)
    destination: str | None = Field(default=None, max_length=320)
    body: str | None = Field(default=None, max_length=4_000)
    notification_key: str | None = Field(default=None, max_length=500)
    expires_in_seconds: int = Field(default=300, ge=30, le=900)

    @model_validator(mode="after")
    def action_shape_valid(self) -> MobileActionPrepareRequest:
        if self.kind is MobileActionKind.DIAL_HANDOFF and not self.destination:
            raise ValueError("dial_handoff requires destination")
        if (
            self.kind is MobileActionKind.SMS_COMPOSE
            and (not self.destination or not self.body)
        ):
            raise ValueError("sms_compose requires destination and body")
        if (
            self.kind is MobileActionKind.NOTIFICATION_REPLY
            and (not self.notification_key or not self.body)
        ):
            raise ValueError(
                "notification_reply requires notification_key and body"
            )
        if self.kind is MobileActionKind.OPEN_CONVERSATION and not self.notification_key:
            raise ValueError("open_conversation requires notification_key")
        return self


class MobileActionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: UUID
    request_id: UUID
    device_id: UUID
    kind: MobileActionKind
    source: MobileSource
    target_label: str
    destination: str | None
    body: str | None
    notification_key: str | None
    exact_preview: str
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_token: str = Field(min_length=32, max_length=256)
    state: MobileActionState
    created_at: datetime
    expires_at: datetime
    approval_required: bool = True
    biometric_confirmation_required: bool = True
    direct_send: bool = False


class MobileActionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    approval_token: str = Field(min_length=32, max_length=256)
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: MobileDecisionKind
    biometric_verified: bool
    decided_at: datetime

    @field_validator("decided_at")
    @classmethod
    def decided_at_timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("decided_at must be timezone-aware")
        return value.astimezone(UTC)


class MobileActionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    action_id: UUID
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    executed: bool
    external_write_performed: bool
    verification_scope: str = Field(min_length=1, max_length=120)
    result_code: str = Field(min_length=1, max_length=120)
    provider_reference: str | None = Field(default=None, max_length=500)
    observed_at: datetime
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("observed_at")
    @classmethod
    def observed_at_timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        return value.astimezone(UTC)


class MobileActionView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal: MobileActionProposal
    state: MobileActionState
    decision: MobileDecisionKind | None = None
    decided_at: datetime | None = None
    evidence: MobileActionEvidence | None = None
    external_write_performed: bool = False
    verified: bool = False


MobileSourceFilter = Annotated[MobileSource | None, Field(default=None)]
