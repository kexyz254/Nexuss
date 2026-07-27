"""Validated contracts for contextual, grounded intelligence."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class IntelligenceMode(StrEnum):
    LOCAL_ONLY = "local_only"
    EXTERNAL_ALLOWED = "external_allowed"


class ProviderKind(StrEnum):
    LOCAL = "local"
    EXTERNAL = "external"


class ContentSensitivity(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"
    RESTRICTED = "restricted"


class AnswerStyle(StrEnum):
    DIRECT = "direct"
    BEGINNER = "beginner"
    DETAILED = "detailed"
    SUMMARY = "summary"
    COMPARISON = "comparison"
    PROFESSIONAL_BRIEF = "professional_brief"


class SourceKind(StrEnum):
    SYSTEM_VERIFIED = "system_verified"
    CURATED_DOCUMENT = "curated_document"
    PUBLIC_WEB = "public_web"
    USER_ASSERTED = "user_asserted"


class EvidenceSource(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: str
    title: str
    kind: SourceKind
    url: HttpUrl | None = None
    publisher: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    live: bool = False

    @field_validator("source_id", "title")
    @classmethod
    def nonempty(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("must not be empty")
        return normalized


class EvidenceChunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: str
    source: EvidenceSource
    text: str
    retrieval_score: float = Field(default=0.0, ge=0.0, le=1.0)
    rank_score: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("chunk_id", "text")
    @classmethod
    def chunk_nonempty(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("must not be empty")
        return normalized


class ConversationTurn(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Literal["user", "assistant"]
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    topic: str | None = None
    answer_sections: tuple[str, ...] = ()


class ContextResolution(BaseModel):
    model_config = ConfigDict(frozen=True)

    original_query: str
    resolved_query: str
    current_topic: str | None = None
    referenced_section: str | None = None
    used_prior_context: bool = False
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class IntelligenceRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    query: str
    style: AnswerStyle = AnswerStyle.DIRECT
    mode: IntelligenceMode = IntelligenceMode.LOCAL_ONLY
    sensitivity: ContentSensitivity = ContentSensitivity.PUBLIC
    external_processing_approved: bool = False
    requires_live_sources: bool = False
    max_sources: int = Field(default=8, ge=1, le=20)
    max_evidence_chars: int = Field(default=18_000, ge=1_000, le=80_000)

    @field_validator("query")
    @classmethod
    def query_valid(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized or len(normalized) > 4_000:
            raise ValueError("query must contain 1-4000 normalized characters")
        return normalized


class DraftClaim(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    citation_ids: tuple[str, ...]
    confidence: float = Field(ge=0.0, le=1.0)


class DraftAnswer(BaseModel):
    model_config = ConfigDict(frozen=True)

    answer: str
    claims: tuple[DraftClaim, ...]
    limitations: tuple[str, ...] = ()
    suggested_sections: tuple[str, ...] = ()


class VerifiedClaim(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    citation_ids: tuple[str, ...]
    confidence: float = Field(ge=0.0, le=1.0)
    support_score: float = Field(ge=0.0, le=1.0)


class IntelligenceAnswer(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: UUID
    session_id: UUID
    answer: str
    claims: tuple[VerifiedClaim, ...]
    sources: tuple[EvidenceSource, ...]
    limitations: tuple[str, ...]
    provider_id: str
    provider_kind: ProviderKind
    intelligence_mode: IntelligenceMode
    context: ContextResolution
    grounded: bool
    verified: bool
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ProviderHealth(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider_id: str
    kind: ProviderKind
    available: bool
    configured: bool
    detail: str
