"""Contracts for proactive schedules and alerts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ScheduleStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


class ScheduleRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schedule_id: UUID
    conversation_id: UUID
    user_session_id: UUID
    title: str = Field(min_length=1, max_length=240)
    prompt: str = Field(min_length=1, max_length=4_000)
    next_run_at: datetime
    interval_seconds: int | None = Field(default=None, ge=60)
    status: ScheduleStatus = ScheduleStatus.ACTIVE
    created_at: datetime
    updated_at: datetime


class AlertRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    alert_id: UUID
    conversation_id: UUID
    user_session_id: UUID
    source_type: str = Field(min_length=1, max_length=80)
    source_id: UUID
    title: str = Field(min_length=1, max_length=240)
    detail: str = Field(min_length=1, max_length=4_000)
    fired_at: datetime
    acknowledged_at: datetime | None = None


class CreateScheduleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    title: str = Field(min_length=1, max_length=240)
    prompt: str = Field(min_length=1, max_length=4_000)
    next_run_at: datetime
    interval_seconds: int | None = Field(default=None, ge=60)
