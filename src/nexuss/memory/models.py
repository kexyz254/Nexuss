"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Typed contracts for the Nexuss P5.3 memory plane.

Trust and volatility are first-class fields, not conventions. The recall layer
weights by them, the policy layer reads them, and nothing downstream needs to
guess where a claim came from or how fast it goes stale.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SourceTrust(StrEnum):
    """Ordered trust tiers.

    USER_ASSERTED outranks CURATED_DOC outranks PUBLIC_WEB. The invariant the
    rest of the system relies on: a PUBLIC_WEB claim may be recalled as data
    and may never occupy an instruction position in a plan.
    """

    USER_ASSERTED = "user_asserted"
    CURATED_DOC = "curated_doc"
    PUBLIC_WEB = "public_web"


class Volatility(StrEnum):
    """How fast a claim goes stale. Governs confidence decay at recall time."""

    STABLE = "stable"
    SEASONAL = "seasonal"
    VOLATILE = "volatile"


class MemoryClaim(BaseModel):
    """One remembered statement with full provenance."""

    model_config = ConfigDict(extra="forbid")

    claim_id: UUID
    topic: str = Field(min_length=1, max_length=200)
    statement: str = Field(min_length=1, max_length=2_000)
    source_ref: str = Field(min_length=1, max_length=500)
    source_trust: SourceTrust
    confidence: float = Field(ge=0.0, le=1.0)
    volatility: Volatility
    observed_at: datetime
    superseded_by: UUID | None = None
    episode_id: UUID | None = None


class Episode(BaseModel):
    """What happened: the durable form of a completed task."""

    model_config = ConfigDict(extra="forbid")

    episode_id: UUID
    session_id: UUID
    task_id: UUID
    utterance: str = Field(min_length=1, max_length=10_000)
    intent: str = Field(min_length=1, max_length=100)
    capability_id: str = Field(min_length=1, max_length=100)
    outcome: str = Field(min_length=1, max_length=100)
    occurred_at: datetime


class RecallMatch(BaseModel):
    """A recalled claim with its composite score.

    A recall that strips provenance is a bug: statement, source and confidence
    always travel together.
    """

    model_config = ConfigDict(extra="forbid")

    claim: MemoryClaim
    score: float = Field(ge=0.0)
    decayed_confidence: float = Field(ge=0.0, le=1.0)
