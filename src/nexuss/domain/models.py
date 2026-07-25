"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

CapabilityId = Annotated[str, Field(pattern=r"^[a-z0-9_.-]+$")]


class Channel(StrEnum):
    VOICE = "voice"
    TEXT = "text"


class AssuranceLevel(StrEnum):
    BASIC = "basic"
    STRONG = "strong"


class IntentKind(StrEnum):
    DAILY_BRIEFING = "daily_briefing"
    SYSTEM_HEALTH = "system_health"
    LOCAL_WORKSPACE_STATUS = "local_workspace_status"
    PREPARE_WORKSPACE = "prepare_workspace"
    PLAY_MEDIA = "play_media"
    ATS_READ = "ats_read"
    ATS_WRITE = "ats_write"
    FINANCIAL_TRANSFER = "financial_transfer"
    SOCIAL_PUBLISH = "social_publish"
    UNKNOWN = "unknown"


class RiskTier(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PolicyOutcome(StrEnum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


class TaskState(StrEnum):
    RECEIVED = "received"
    AWAITING_APPROVAL = "awaiting_approval"
    DENIED = "denied"
    COMPLETED = "completed"
    FAILED = "failed"


class StepStatus(StrEnum):
    VERIFIED = "verified"
    SKIPPED = "skipped"
    FAILED = "failed"


class TaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    channel: Channel
    utterance: str = Field(min_length=1, max_length=10_000)
    user_session_id: UUID
    target_devices: list[str] = Field(default_factory=list)
    requested_at: datetime
    client_context: dict[str, object] = Field(default_factory=dict)


class IdentitySession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    authenticated: bool
    assurance_level: AssuranceLevel = AssuranceLevel.BASIC


class Intent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: IntentKind
    normalized_text: str
    confidence: float = Field(ge=0.0, le=1.0)
    entities: dict[str, str] = Field(default_factory=dict)


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: UUID
    order: int = Field(ge=1)
    capability_id: CapabilityId
    risk_tier: RiskTier
    expected_evidence: list[str] = Field(min_length=1)


class TaskPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: UUID
    task_id: UUID
    intent: Intent
    steps: list[PlanStep] = Field(min_length=1)


class PolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: UUID
    capability_id: CapabilityId
    outcome: PolicyOutcome
    reason_code: str
    explanation: str


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    observed_at: datetime
    attributes: dict[str, object]


class CapabilityResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: UUID
    capability_id: CapabilityId
    status: StepStatus
    evidence: list[EvidenceRecord]
    error_code: str | None = None


class ActionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receipt_id: UUID
    task_id: UUID
    request_id: UUID
    state: TaskState
    intent: Intent
    plan_id: UUID
    policy_decisions: list[PolicyDecision]
    results: list[CapabilityResult]
    created_at: datetime
    verified: bool


class TaskView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    request_id: UUID
    state: TaskState
    intent: Intent
    plan: TaskPlan
    policy_decisions: list[PolicyDecision]
    results: list[CapabilityResult]
    created_at: datetime
    updated_at: datetime
