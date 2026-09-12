"""Nexuss P6.12 read-only task lifecycle projection.

This module does not create a second task state machine. It projects the
authoritative TaskView into a compact, privacy-preserving status surface.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from nexuss.domain.models import StepStatus, TaskState, TaskView


class TaskProgressSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    authoritative_state: str
    phase: str
    progress_percent: int = Field(ge=0, le=100)
    terminal: bool
    approval_required: bool
    retry: Literal[
        "not_applicable",
        "manual_retry_possible",
        "not_safe",
    ]
    retry_reason: str | None = None
    capability_ids: list[str]
    verified_results: int = Field(ge=0)
    failed_results: int = Field(ge=0)
    last_event_type: str | None = None
    last_event_at: str | None = None
    observed_at: str


_PHASES: dict[TaskState, tuple[str, int, bool]] = {
    TaskState.RECEIVED: ("started", 5, False),
    TaskState.PLANNED: ("thinking", 20, False),
    TaskState.AWAITING_APPROVAL: ("waiting_for_approval", 35, False),
    TaskState.APPROVED: ("approved", 45, False),
    TaskState.EXECUTING: ("running", 65, False),
    TaskState.VERIFYING: ("finishing_up", 85, False),
    TaskState.COMPLETED: ("done", 100, True),
    TaskState.PARTIALLY_COMPLETED: ("needs_review", 100, True),
    TaskState.DENIED: ("denied", 100, True),
    TaskState.FAILED: ("failed", 100, True),
    TaskState.ROLLING_BACK: ("undoing", 85, False),
    TaskState.ROLLED_BACK: ("undone", 100, True),
}

_TRANSIENT_FAILURE_CODES = frozenset(
    {
        "TRUSTED_DEVICE_NODE_UNREACHABLE",
        "KNOWLEDGE_PROVIDER_NOT_CONFIGURED",
        "YOUTUBE_PROVIDER_NOT_CONFIGURED",
        "MOBILE_PAIRING_GATEWAY_NOT_CONFIGURED",
    }
)


def _retry_classification(task: TaskView) -> tuple[str, str | None]:
    if task.state is not TaskState.FAILED:
        return "not_applicable", None

    errors = [
        result.error_code
        for result in task.results
        if result.error_code
    ]
    if errors and all(code in _TRANSIENT_FAILURE_CODES for code in errors):
        return (
            "manual_retry_possible",
            "The failure is classified as transient. A retry must be a new "
            "user-requested task and must pass policy and approval again.",
        )

    return (
        "not_safe",
        "Nexuss will not automatically retry this failed task.",
    )


def task_progress(task: TaskView) -> TaskProgressSnapshot:
    """Return a safe display projection of one authoritative task."""

    phase, percentage, terminal = _PHASES[task.state]
    retry, retry_reason = _retry_classification(task)
    last_event = task.events[-1] if task.events else None

    return TaskProgressSnapshot(
        task_id=str(task.task_id),
        authoritative_state=task.state.value,
        phase=phase,
        progress_percent=percentage,
        terminal=terminal,
        approval_required=task.state is TaskState.AWAITING_APPROVAL,
        retry=retry,
        retry_reason=retry_reason,
        capability_ids=[
            str(step.capability_id)
            for step in task.plan.steps
        ],
        verified_results=sum(
            1
            for result in task.results
            if result.status is StepStatus.VERIFIED
        ),
        failed_results=sum(
            1
            for result in task.results
            if result.status is StepStatus.FAILED
        ),
        last_event_type=(
            last_event.event_type
            if last_event is not None
            else None
        ),
        last_event_at=(
            last_event.occurred_at.isoformat()
            if last_event is not None
            else None
        ),
        observed_at=datetime.now(UTC).isoformat(),
    )
