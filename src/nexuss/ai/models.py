"""Provider-neutral AI planning contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from nexuss.cognitive.models import CognitiveMode


class AIProviderProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[a-z][a-z0-9_.-]*$",
    )
    display_name: str = Field(min_length=1, max_length=120)
    adapter_kind: str = Field(min_length=1, max_length=80)
    supported_modes: tuple[CognitiveMode, ...]
    supports_structured_output: bool
    supports_action_planning: bool
    supports_vision: bool = False
    supports_long_context: bool = False
    local_processing: bool = False
    enabled: bool = False
    priority: int = Field(default=100, ge=0, le=10_000)


class RequestedAction(BaseModel):
    """An AI-requested action with no execution authority."""

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
    expected_evidence: tuple[str, ...] = Field(default_factory=tuple)
    depends_on: tuple[str, ...] = Field(default_factory=tuple)


class ProviderActionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: str
    model: str
    mode: CognitiveMode
    summary: str = Field(min_length=1, max_length=8_000)
    response: str = Field(min_length=1, max_length=50_000)
    requested_actions: tuple[RequestedAction, ...] = ()

    provider_generated_plan_only: Literal[True] = True
    execution_authorized: Literal[False] = False
    nexuss_retains_final_authority: Literal[True] = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
