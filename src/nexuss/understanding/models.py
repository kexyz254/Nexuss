"""Copyright © kexyz254peter.
Nexuss AI - Confidential and Proprietary.
Unauthorized copying, redistribution or disclosure is prohibited.

Validated contracts for intent understanding, clarification, and dispatch.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class IntentDomain(StrEnum):
    ASSISTANT = "assistant"
    GITHUB_WORKSPACE = "github_workspace"
    LOCAL_WORKSPACE = "local_workspace"
    KNOWLEDGE = "knowledge"
    MEDIA = "media"
    NOTES = "notes"
    MEMORY = "memory"
    DEVICE = "device"
    ARCHIVE = "archive"
    SYSTEM = "system"
    DEPLOYMENT = "deployment"
    COMMITMENTS = "commitments"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"


class GoalKind(StrEnum):
    ASSISTANT_CAPABILITIES = "assistant_capabilities"
    ASSISTANT_CONVERSATION = "assistant_conversation"
    SYSTEM_HEALTH = "system_health"
    GITHUB_CAPABILITIES = "github_capabilities"
    GITHUB_ACCOUNT_IDENTITY = "github_account_identity"
    GITHUB_REPOSITORY_INVENTORY = "github_repository_inventory"
    GITHUB_REPOSITORY_INSPECT = "github_repository_inspect"
    GITHUB_REPOSITORY_ANALYZE = "github_repository_analyze"
    GITHUB_IMPORTANT_FILES = "github_important_files"
    GITHUB_BUILD_PLAN = "github_build_plan"
    GITHUB_BUILD_EXECUTE = "github_build_execute"
    GITHUB_COMMITS_LIST = "github_commits_list"
    GITHUB_PULL_REQUESTS_LIST = "github_pull_requests_list"
    GITHUB_ISSUES_LIST = "github_issues_list"
    GITHUB_ACTIONS_INSPECT = "github_actions_inspect"
    GITHUB_PREPARE_CHANGE = "github_prepare_change"
    GITHUB_PUSH_DIRECT_MAIN = "github_push_direct_main"
    GITHUB_APPROVAL_BYPASS = "github_approval_bypass"
    GITHUB_DELETE_REPOSITORY = "github_delete_repository"
    LOCAL_WORKSPACE_STATUS = "local_workspace_status"
    KNOWLEDGE_RESEARCH = "knowledge_research"
    MEDIA_DISCOVER = "media_discover"
    NOTE_CREATE = "note_create"
    MEMORY_ACTION = "memory_action"
    DEVICE_ACTION = "device_action"
    ARCHIVE_PUBLISH = "archive_publish"
    DEPLOYMENT_PLAN = "deployment_plan"
    DEPLOYMENT_EXECUTE = "deployment_execute"
    GOOGLE_WORKSPACE_STATUS = "google_workspace_status"
    COMMITMENT_PREPARE_DAY = "commitment_prepare_day"
    COMMITMENT_LIST = "commitment_list"
    COMMUNICATION_NEEDS_REPLY = "communication_needs_reply"
    CALENDAR_CONFLICTS = "calendar_conflicts"
    COMMUNICATION_EXTERNAL_WRITE = "communication_external_write"
    AMBIGUOUS_REFERENCE = "ambiguous_reference"
    AMBIGUOUS_SCOPE = "ambiguous_scope"
    UNKNOWN = "unknown"


class OperationKind(StrEnum):
    INFORM = "inform"
    READ = "read"
    PLAN = "plan"
    EXECUTE = "execute"
    WRITE = "write"
    DESTRUCTIVE = "destructive"


class ResolutionStatus(StrEnum):
    COMPLETED = "completed"
    READY = "ready"
    CLARIFICATION_REQUIRED = "clarification_required"
    BLOCKED = "blocked"
    PASS_THROUGH = "pass_through"
    CANCELLED = "cancelled"


class DispatchKind(StrEnum):
    NONE = "none"
    LEGACY_TASK = "legacy_task"
    GITHUB_READ_ONLY = "github_read_only"
    COMMITMENT_READ_ONLY = "commitment_read_only"


class ClarificationKind(StrEnum):
    YES_NO = "yes_no"
    SINGLE_SELECT = "single_select"


class GoalEntities(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    owner: str | None = None
    repository: str | None = None
    repository_full_name: str | None = None
    ref: str | None = None
    issue_number: int | None = Field(default=None, ge=1)
    pull_request_number: int | None = Field(default=None, ge=1)
    file_path: str | None = None
    query: str | None = None
    selected_object: str | None = None

    @model_validator(mode="after")
    def full_name_consistent(self) -> GoalEntities:
        if self.repository_full_name:
            owner, separator, repository = self.repository_full_name.partition("/")
            if not separator or not owner or not repository:
                raise ValueError("repository_full_name must be owner/repository")
            if self.owner and self.owner.casefold() != owner.casefold():
                raise ValueError("owner conflicts with repository_full_name")
            if self.repository and self.repository.casefold() != repository.casefold():
                raise ValueError("repository conflicts with repository_full_name")
        return self


class GoalConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    read_only: bool = False
    plan_only: bool = False
    allow_modification: bool = True
    allow_code_execution: bool = True
    allow_external_writes: bool = True
    allow_network_access: bool = True
    require_tests_pass: bool = False
    require_phone_approval: bool | None = None
    direct_default_branch_write_requested: bool = False
    approval_bypass_requested: bool = False
    force_push_requested: bool = False
    preserve_privacy: bool = True


class ClarificationOption(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    option_id: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=180)
    value: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=300)


class ClarificationQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    clarification_id: UUID = Field(default_factory=uuid4)
    kind: ClarificationKind
    question: str = Field(min_length=1, max_length=300)
    options: tuple[ClarificationOption, ...]
    field_name: str = Field(min_length=1, max_length=80)
    expires_at: datetime
    attempts_remaining: int = Field(default=3, ge=1, le=5)

    @model_validator(mode="after")
    def option_shape_valid(self) -> ClarificationQuestion:
        if self.kind is ClarificationKind.YES_NO:
            values = {item.value.casefold() for item in self.options}
            if values != {"yes", "no"}:
                raise ValueError("yes/no clarification must contain yes and no")
        if self.kind is ClarificationKind.SINGLE_SELECT and len(self.options) < 2:
            raise ValueError("single-select clarification requires at least two options")
        return self


class GoalInterpretation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    interpretation_id: UUID = Field(default_factory=uuid4)
    original_utterance: str
    normalized_utterance: str
    domain: IntentDomain
    goal: GoalKind
    operation: OperationKind
    confidence: float = Field(ge=0.0, le=1.0)
    entities: GoalEntities = Field(default_factory=GoalEntities)
    constraints: GoalConstraints = Field(default_factory=GoalConstraints)
    missing_fields: tuple[str, ...] = ()
    constraint_conflicts: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    rationale: tuple[str, ...] = ()
    context_used: bool = False
    grants_authority: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("original_utterance", "normalized_utterance")
    @classmethod
    def nonempty_utterance(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("utterance must not be empty")
        return normalized


class UnderstandingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: UUID = Field(default_factory=uuid4)
    utterance: str
    channel: Literal["text", "voice"] = "text"
    client_context: dict[str, object] = Field(default_factory=dict)
    execute_safe_reads: bool = True

    @field_validator("utterance")
    @classmethod
    def utterance_valid(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized or len(normalized) > 4_000:
            raise ValueError("utterance must contain 1-4000 normalized characters")
        return normalized


class ClarificationAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    option_id: str = Field(min_length=1, max_length=120)


class GoalExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: str
    assistant_message: str
    data: dict[str, object] = Field(default_factory=dict)
    receipt_ids: tuple[UUID, ...] = ()
    evidence_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    github_write_performed: bool = False
    phone_approval_required: bool = False
    credentials_exposed: bool = False


class UnderstandingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: UUID
    session_id: UUID
    status: ResolutionStatus
    interpretation: GoalInterpretation
    dispatch: DispatchKind = DispatchKind.NONE
    assistant_message: str
    clarification: ClarificationQuestion | None = None
    execution: GoalExecutionResult | None = None
    resolved_utterance: str | None = None
    no_action_performed: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def state_contract_valid(self) -> UnderstandingResponse:
        if (
            self.status is ResolutionStatus.CLARIFICATION_REQUIRED
            and self.clarification is None
        ):
            raise ValueError("clarification_required response needs a question")
        if self.status is ResolutionStatus.COMPLETED and self.execution is None:
            raise ValueError("completed response needs execution evidence")
        if self.execution and self.execution.github_write_performed:
            raise ValueError("P6.6B understanding cannot perform GitHub writes")
        return self
