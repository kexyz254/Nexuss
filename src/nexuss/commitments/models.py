"""Typed contracts for unified commitment intelligence."""
from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nexuss.connectors.google_workspace.models import CalendarEventSummary


class CommitmentSource(StrEnum):
    GMAIL = "gmail"
    CALENDAR = "calendar"
    MOBILE = "mobile"

class CommitmentKind(StrEnum):
    REQUEST = "request"
    PROMISE = "promise"
    RESPONSE_NEEDED = "response_needed"

class CommitmentPriority(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

class CommitmentStatus(StrEnum):
    OPEN = "open"
    OVERDUE = "overdue"
    SCHEDULED = "scheduled"

class CommitmentEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source: CommitmentSource
    source_id: str
    counterparty: str | None = None
    excerpt: str = Field(max_length=800)
    observed_at: datetime
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

class CommitmentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    commitment_id: UUID = Field(default_factory=uuid4)
    kind: CommitmentKind
    summary: str = Field(min_length=1, max_length=500)
    counterparty: str | None = Field(default=None, max_length=240)
    due_at: datetime | None = None
    priority: CommitmentPriority
    status: CommitmentStatus
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: tuple[CommitmentEvidence, ...]
    response_needed: bool = False
    source_count: int = Field(ge=1)
    external_write_performed: bool = False

class CalendarConflict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    first_event_id: str
    second_event_id: str
    first_title: str
    second_title: str
    overlap_start: datetime
    overlap_end: datetime
    minutes: int = Field(ge=1)

class FocusBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    commitment_id: UUID
    title: str
    start: datetime
    end: datetime
    rationale: str

class PrepareDayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    planning_date: date
    timezone: str = "Africa/Nairobi"
    include_mobile: bool = True
    gmail_days_back: int = Field(default=14, ge=1, le=30)

class WorkdayBrief(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    planning_date: date
    timezone: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    connected_google_account: str | None
    source_status: dict[str, bool]
    commitments: tuple[CommitmentRecord, ...]
    calendar_events: tuple[CalendarEventSummary, ...]
    conflicts: tuple[CalendarConflict, ...]
    focus_blocks: tuple[FocusBlock, ...]
    urgent_count: int = Field(ge=0)
    overdue_count: int = Field(ge=0)
    responses_needed: int = Field(ge=0)
    external_write_performed: bool = False
    phone_approval_requested: bool = False
    credentials_exposed: bool = False

class CommitmentHealth(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: str = "ready"
    mode: str = "p68a_unified_commitment_intelligence"
    google_workspace_connected: bool
    trusted_mobile_feed_available: bool
    external_writes_enabled: bool = False
    external_actions_require_approval: bool = True
    credentials_exposed: bool = False

    @field_validator("status")
    @classmethod
    def status_ready(cls, value: str) -> str:
        if value != "ready":
            raise ValueError("commitment health must be ready")
        return value
