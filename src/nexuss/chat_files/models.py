"""Validated chat-file and artifact contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ExtractionStatus(StrEnum):
    EXTRACTED = "extracted"
    STORED_ONLY = "stored_only"
    FAILED = "failed"


class AttachmentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    attachment_id: UUID
    conversation_id: UUID
    user_session_id: UUID
    name: str = Field(min_length=1, max_length=240)
    media_type: str = Field(min_length=1, max_length=160)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extraction_status: ExtractionStatus
    extracted_chars: int = Field(ge=0)
    created_at: datetime


class ArtifactKind(StrEnum):
    PACKAGE = "package"
    TEXT = "text"


class ArtifactRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: UUID
    conversation_id: UUID
    user_session_id: UUID
    kind: ArtifactKind
    name: str = Field(min_length=1, max_length=240)
    media_type: str = Field(min_length=1, max_length=160)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime


class PackageAttachmentsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attachment_ids: tuple[UUID, ...] = Field(min_length=1, max_length=10)
    name: str = Field(default="nexuss-files.zip", min_length=1, max_length=120)


class CreateTextArtifactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=500_000)
    media_type: str = Field(default="text/markdown", min_length=1, max_length=160)
