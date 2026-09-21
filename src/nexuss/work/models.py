"""Persistent work-engine contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProjectStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class WorkStatus(StrEnum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class WorkPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class ProjectRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID
    user_session_id: UUID
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4_000)
    status: ProjectStatus = ProjectStatus.ACTIVE
    created_at: datetime
    updated_at: datetime


class WorkItemRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    work_item_id: UUID
    user_session_id: UUID
    conversation_id: UUID | None = None
    project_id: UUID | None = None
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=8_000)
    status: WorkStatus = WorkStatus.QUEUED
    priority: WorkPriority = WorkPriority.NORMAL
    due_at: datetime | None = None
    dependency_ids: tuple[UUID, ...] = ()
    resume_context: str = Field(default="", max_length=20_000)
    created_at: datetime
    updated_at: datetime


class CreateProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4_000)


class CreateWorkItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=8_000)
    project_id: UUID | None = None
    conversation_id: UUID | None = None
    priority: WorkPriority = WorkPriority.NORMAL
    due_at: datetime | None = None
    dependency_ids: tuple[UUID, ...] = Field(default=(), max_length=20)
    resume_context: str = Field(default="", max_length=20_000)


class UpdateWorkItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: WorkStatus


class WorkOverview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    projects: tuple[ProjectRecord, ...]
    items: tuple[WorkItemRecord, ...]
