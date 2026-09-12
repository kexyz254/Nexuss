"""Validated cognitive proposal models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CognitiveMode(StrEnum):
    ANSWER = "answer"
    ANALYZE = "analyze"
    PLAN = "plan"
    WRITE = "write"
    REWRITE = "rewrite"
    DESIGN = "design"
    CODE = "code"
    DEBUG = "debug"
    REVIEW = "review"
    RESEARCH_SYNTHESIS = "research_synthesis"
    CREATE = "create"
    BUILD_PROPOSAL = "build_proposal"


class CognitiveProposal(BaseModel):
    """A provider-generated proposal with no execution authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    mode: CognitiveMode

    summary: str = Field(min_length=1, max_length=8_000)
    response: str = Field(min_length=1, max_length=50_000)

    steps: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    recommended_actions: tuple[str, ...] = ()
    requested_capabilities: tuple[str, ...] = ()

    requires_execution: Literal[False] = False
    requires_approval: Literal[False] = False

    provider_generated_proposal_only: Literal[True] = True
    nexuss_retains_final_authority: Literal[True] = True

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )
