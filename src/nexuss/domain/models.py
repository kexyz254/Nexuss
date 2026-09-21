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
    ASSISTANT_IDENTITY = "assistant_identity"
    ASSISTANT_CAPABILITIES = "assistant_capabilities"
    ASSISTANT_HELP = "assistant_help"
    DAILY_BRIEFING = "daily_briefing"
    SYSTEM_HEALTH = "system_health"
    SYSTEM_UPDATE_STATUS = "system_update_status"
    SYSTEM_UPDATE_APPLY = "system_update_apply"
    LOCAL_WORKSPACE_STATUS = "local_workspace_status"
    CREATE_NOTE = "create_note"
    LAUNCH_NOTEPAD = "launch_notepad"
    WEB_RESEARCH = "web_research"
    YOUTUBE_SEARCH = "youtube_search"
    PHONE_OPEN_YOUTUBE = "phone_open_youtube"
    PAIR_PHONE = "pair_phone"
    LIST_PAIRED_DEVICES = "list_paired_devices"
    UNPAIR_PHONE = "unpair_phone"
    MEMORY_REMEMBER = "memory_remember"
    MEMORY_RECALL = "memory_recall"
    MEMORY_FORGET = "memory_forget"
    IDENTITY_RECALL = "identity_recall"
    USER_IDENTITY_CLAIM = "user_identity_claim"
    CONSTITUTION_OVERRIDE = "constitution_override"
    OPEN_WEB_SEARCH = "open_web_search"
    PREPARE_WORKSPACE = "prepare_workspace"
    PLAY_MEDIA = "play_media"
    ATS_READ = "ats_read"
    ATS_WRITE = "ats_write"
    FINANCIAL_TRANSFER = "financial_transfer"
    SOCIAL_PUBLISH = "social_publish"
    SMALL_TALK = "small_talk"
    DATETIME_QUERY = "datetime_query"
    OPEN_QUESTION = "open_question"
    GITHUB_CONNECTION_STATUS = "github_connection_status"
    GITHUB_REPOSITORIES = "github_repositories"
    GITHUB_CREATE_REPOSITORY = "github_create_repository"
    ENGINEERING_BUILD_ARTIFACT = "engineering_build_artifact"
    ENGINEERING_VERIFY_ACCEPTANCE = "engineering_verify_acceptance"
    ENGINEERING_REPAIR_FAILED_BUILD = "engineering_repair_failed_build"
    UNKNOWN = "unknown"


class RiskTier(StrEnum):
    INFORMATIONAL = "informational"
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
    PLANNED = "planned"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    DENIED = "denied"
    FAILED = "failed"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"


class StepStatus(StrEnum):
    VERIFIED = "verified"
    SKIPPED = "skipped"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CONSUMED = "consumed"


class ApprovalDecisionKind(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class ApprovalChannel(StrEnum):
    DESKTOP = "desktop"
    PHONE = "phone"


class CapabilityStatus(StrEnum):
    ACTIVE = "active"
    SIMULATED = "simulated"
    PROHIBITED = "prohibited"


class ApprovalPolicy(StrEnum):
    NONE = "none"
    EXPLICIT = "explicit"
    PROHIBITED = "prohibited"


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
    parameters: dict[str, object] = Field(default_factory=dict)
    reversible: bool = False


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


class ActionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    sequence: int = Field(ge=1)
    state: TaskState
    event_type: str
    occurred_at: datetime
    detail: str


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: UUID
    task_id: UUID
    capability_id: CapabilityId
    status: ApprovalStatus
    action_title: str
    action_summary: str
    exact_preview: str
    destination_label: str
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_token: str | None = Field(default=None, min_length=32, max_length=256)
    session_id: UUID
    expires_at: datetime
    risk_tier: RiskTier
    reversible: bool
    approval_channel: ApprovalChannel = ApprovalChannel.DESKTOP


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: UUID
    approval_token: str = Field(min_length=32, max_length=256)
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: ApprovalDecisionKind


class RollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: str = Field(pattern=r"^undo$")


class CapabilityManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_id: CapabilityId
    version: str
    title: str
    description: str
    risk_tier: RiskTier
    approval_policy: ApprovalPolicy
    reversible: bool
    execution_mode: str
    status: CapabilityStatus
    approval_channel: ApprovalChannel = ApprovalChannel.DESKTOP


class ActionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receipt_id: UUID
    receipt_version: int = Field(ge=1)
    task_id: UUID
    request_id: UUID
    state: TaskState
    intent: Intent
    plan_id: UUID
    policy_decisions: list[PolicyDecision]
    results: list[CapabilityResult]
    events: list[ActionEvent]
    created_at: datetime
    updated_at: datetime
    verified: bool
    reversible: bool


class TaskView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    request_id: UUID
    user_session_id: UUID
    state: TaskState
    intent: Intent
    plan: TaskPlan
    policy_decisions: list[PolicyDecision]
    results: list[CapabilityResult]
    events: list[ActionEvent]
    approval: ApprovalRequest | None = None
    created_at: datetime
    updated_at: datetime
