"""Codespaces contracts for the P6.5D lifecycle connector."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class CodespaceState(StrEnum):
    PREPARED = "prepared"
    CREATING = "creating"
    AVAILABLE = "available"
    STOPPED = "stopped"
    DELETING = "deleting"
    DELETED = "deleted"
    FAILED = "failed"


class CodespaceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: UUID = Field(default_factory=uuid4)
    owner_login: str
    repository_name: str
    ref: str
    machine: str
    idle_timeout_minutes: int = Field(default=30, ge=5, le=240)
    retention_period_minutes: int = Field(default=60, ge=15, le=10_080)
    devcontainer_path: str | None = None
    prepared_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CodespaceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    codespace_name: str
    repository_full_name: str
    state: CodespaceState
    machine: str
    web_url: str
    billable_owner: str
    created_at: datetime
    last_used_at: datetime | None = None
    credentials_exposed: bool = False
