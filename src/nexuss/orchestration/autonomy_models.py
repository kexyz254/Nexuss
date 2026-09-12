'''Bounded autonomy contracts for Nexuss.'''

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from nexuss.cognitive.models import CognitiveMode


class AutonomyMode(StrEnum):
    READ_ONLY = "read_only"
    SUPERVISED = "supervised"


class AutonomousRunState(StrEnum):
    COMPLETED = "completed"
    AWAITING_APPROVAL = "awaiting_approval"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    FAILED = "failed"


class AutonomousStepState(StrEnum):
    COMPLETED = "completed"
    AWAITING_APPROVAL = "awaiting_approval"
    BLOCKED = "blocked"
    FAILED = "failed"
    PENDING = "pending"


class AutonomousRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    user_session_id: UUID
    instruction: str = Field(min_length=1, max_length=20_000)
    provider_id: str = Field(default="auto", min_length=1, max_length=80)
    provider_mode: CognitiveMode = CognitiveMode.PLAN
    autonomy_mode: AutonomyMode = AutonomyMode.SUPERVISED
    external_processing_approved: bool = False
    maximum_actions: int = Field(default=6, ge=1, le=10)
    maximum_runtime_seconds: int = Field(default=120, ge=10, le=600)


class AutonomousStepRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action_key: str
    capability_id: str
    state: AutonomousStepState
    reason_code: str
    explanation: str
    core_task_id: UUID | None = None
    core_receipt_id: UUID | None = None
    core_task_state: str | None = None
    policy_outcome: str | None = None
    evidence_count: int = 0
    evidence_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    error_code: str | None = None


class AutonomousLifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int
    state: str
    event_type: str
    occurred_at: datetime
    detail: str


class AutonomousRunReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    receipt_id: UUID
    receipt_type: Literal["bounded_autonomy_run"]
    run_id: UUID
    request_id: UUID
    provider_id: str
    model: str
    plan_receipt_id: UUID
    run_sha256: str
    protected_auto_approval_authorized: Literal[False] = False
    protected_actions_executed_without_approval: Literal[False] = False
    external_writes_without_approval: Literal[False] = False
    nexuss_retains_final_authority: Literal[True] = True
    events: tuple[AutonomousLifecycleEvent, ...]
    created_at: datetime


class AutonomousRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID
    request_id: UUID
    user_session_id: UUID
    state: AutonomousRunState
    autonomy_mode: AutonomyMode
    provider_id: str
    provider_display_name: str
    model: str
    summary: str
    response: str
    plan_receipt_id: UUID
    steps: tuple[AutonomousStepRecord, ...]
    completed_count: int
    awaiting_approval_count: int
    blocked_count: int
    failed_count: int
    current_blocker: str | None = None
    automatic_read_execution: Literal[True] = True
    automatic_protected_execution: Literal[False] = False
    automatic_provider_fallback: Literal[False] = False
    created_at: datetime
    updated_at: datetime
    receipt: AutonomousRunReceipt
