"""Contracts for the loopback-only Nexuss local-control connector."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LocalControlOperation(StrEnum):
    INSPECT_UPDATE = "inspect_update"
    APPLY_UPDATE = "apply_update"


class LocalControlCommandEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    operation: LocalControlOperation
    branch: str = Field(
        default="feature/p5-knowledge-media-mobile",
        min_length=1,
        max_length=200,
    )
    expected_current_sha: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{40}$",
    )
    expected_target_sha: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{40}$",
    )
    issued_at: datetime
    expires_at: datetime
    nonce: str = Field(min_length=24, max_length=200)


class LocalControlHealth(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str
    mode: str
    repository_root: str
    approved_branch: str
    update_execution_enabled: bool = True


class LocalUpdateStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    branch: str
    current_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    remote_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    clean_worktree: bool
    fast_forward_available: bool
    update_available: bool
    ahead_by: int = Field(ge=0)
    behind_by: int = Field(ge=0)
    restart_required: bool
    credentials_exposed: bool = False


class LocalUpdateAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    update_id: UUID
    previous_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    target_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    branch: str
    restart_scheduled: bool
    rollback_on_failed_health: bool
    credentials_exposed: bool = False
