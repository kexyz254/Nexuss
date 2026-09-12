from __future__ import annotations

import time
from datetime import UTC, datetime
from threading import Event
from uuid import uuid4

import pytest

from nexuss.core.service import CoreSimulatorService
from nexuss.domain.models import (
    ApprovalDecision,
    ApprovalDecisionKind,
    CapabilityResult,
    Channel,
    EvidenceRecord,
    IdentitySession,
    StepStatus,
    TaskRequest,
    TaskState,
)
from nexuss.interactions.models import InteractionState
from nexuss.interactions.service import (
    _interaction_state_for_core_task,
    _task_display_text,
)


def _request(session_id):
    return TaskRequest(
        request_id=uuid4(),
        channel=Channel.TEXT,
        utterance="Build Nexuss change: add a compact diagnostics badge",
        user_session_id=session_id,
        target_devices=[],
        requested_at=datetime.now(UTC),
        client_context={"source": "governed-async-test"},
    )


def _approve(task):
    approval = task.approval
    assert approval is not None
    assert approval.approval_token is not None
    return ApprovalDecision(
        approval_id=approval.approval_id,
        approval_token=approval.approval_token,
        payload_sha256=approval.payload_sha256,
        decision=ApprovalDecisionKind.APPROVE,
    )


def test_engineering_task_waits_for_one_exact_approval_then_runs_in_background(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The legacy environment variable may enable the developer feature, but it
    # no longer pre-authorizes the High-risk mission itself.
    monkeypatch.setenv("NEXUSS_DEVELOPER_SELF_BUILD", "1")
    started = Event()
    release = Event()

    def fake_execute(step, observed_at=None, **kwargs):
        started.set()
        assert kwargs.get("task_id") is not None
        assert kwargs.get("approval") is None
        assert release.wait(timeout=3)
        return CapabilityResult(
            step_id=step.step_id,
            capability_id=step.capability_id,
            status=StepStatus.VERIFIED,
            evidence=[
                EvidenceRecord(
                    source="test:governed-background",
                    observed_at=observed_at or datetime.now(UTC),
                    attributes={
                        "engineering_build_receipt": True,
                        "sha256_verification": True,
                    },
                )
            ],
        )

    monkeypatch.setattr("nexuss.core.service.execute_step", fake_execute)
    session_id = uuid4()
    session = IdentitySession(session_id=session_id, authenticated=True)
    core = CoreSimulatorService()

    pending = core.create_task(_request(session_id), session)

    assert pending.state is TaskState.AWAITING_APPROVAL
    assert pending.approval is not None
    assert pending.approval.capability_id == "engineering.build_artifact"
    assert started.is_set() is False

    running = core.approve_task(
        pending.task_id,
        _approve(pending),
        session,
    )

    assert running.state is TaskState.EXECUTING
    assert core.get_task(running.task_id).state is TaskState.EXECUTING
    assert started.wait(timeout=2)
    release.set()

    deadline = time.monotonic() + 3
    terminal = core.get_task(running.task_id)
    while terminal.state is TaskState.EXECUTING and time.monotonic() < deadline:
        time.sleep(0.01)
        terminal = core.get_task(running.task_id)

    assert terminal.state is TaskState.COMPLETED
    assert terminal.results[0].status is StepStatus.VERIFIED
    assert any(
        event.event_type == "approval_granted"
        for event in terminal.events
    )
    assert any(
        event.event_type == "engineering_execution_started"
        for event in terminal.events
    )
    assert any(
        event.event_type == "verification_completed"
        for event in terminal.events
    )


def test_interaction_projection_treats_running_core_task_as_in_progress() -> None:
    assert (
        _interaction_state_for_core_task("executing")
        is InteractionState.RESPONDED
    )
    assert (
        _interaction_state_for_core_task("verifying")
        is InteractionState.RESPONDED
    )
    assert (
        _interaction_state_for_core_task("failed")
        is InteractionState.FAILED
    )

    class Running:
        state = "executing"
        results = ()

    text = _task_display_text(Running(), fallback="")
    assert "created the governed task" in text
    assert "Task Runtime" in text
