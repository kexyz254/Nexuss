"""Validated universal orchestration planning models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from nexuss.ai.models import AIProviderProfile, ProviderActionPlan
from nexuss.capabilities.models import MappedRequestedAction
from nexuss.cognitive.models import CognitiveMode


class UniversalActionPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    user_session_id: UUID
    instruction: str = Field(min_length=1, max_length=20_000)
    mode: CognitiveMode = CognitiveMode.PLAN
    provider_id: str = Field(default="auto", min_length=1, max_length=80)
    external_processing_approved: bool = False
    maximum_actions: int = Field(default=8, ge=1, le=12)


class ActionPlanEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: AIProviderProfile
    plan: ProviderActionPlan
    mapped_actions: tuple[MappedRequestedAction, ...]
    action_count: int
    verified_existing_count: int
    simulated_count: int
    prohibited_count: int
    unknown_count: int
    all_actions_mapped: bool
    execution_authorized: Literal[False] = False
    capabilities_executed: int = 0
    approval_requested: Literal[False] = False


class OrchestrationLifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int
    state: str
    event_type: str
    occurred_at: datetime
    detail: str


class ActionPlanReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    receipt_id: UUID
    receipt_type: Literal["universal_action_plan"]
    request_id: UUID
    provider_id: str
    model: str
    mode: str
    request_sha256: str
    capability_catalog_sha256: str
    plan_sha256: str
    provider_invoked: Literal[True] = True
    provider_selected: Literal[True] = True
    plan_validated: Literal[True] = True
    capability_mapping_completed: Literal[True] = True
    execution_authorized: Literal[False] = False
    capabilities_executed: int = 0
    approval_requested: Literal[False] = False
    files_modified: Literal[False] = False
    external_writes: Literal[False] = False
    hidden_reasoning_stored: Literal[False] = False
    nexuss_retains_final_authority: Literal[True] = True
    events: tuple[OrchestrationLifecycleEvent, ...]
    created_at: datetime


class UniversalActionPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    envelope: ActionPlanEnvelope
    receipt: ActionPlanReceipt
