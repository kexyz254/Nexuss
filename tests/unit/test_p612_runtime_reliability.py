"""P6.12 runtime reliability regression tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from nexuss.core.intents import classify_intent
from nexuss.core.planner import build_plan
from nexuss.core.policy import evaluate_step
from nexuss.core.service import CoreSimulatorService
from nexuss.core.task_status import task_progress
from nexuss.device.client import (
    DeviceCommandError,
    DisabledDeviceNodeClient,
    inspect_device_node_runtime,
)
from nexuss.domain.models import (
    Channel,
    IdentitySession,
    IntentKind,
    PolicyOutcome,
    TaskRequest,
)


def test_exact_managed_note_phrase_reaches_governed_write() -> None:
    intent = classify_intent(
        "Create a managed note named nexuss-approval-validation "
        "with the content: Nexuss approval system validation."
    )
    assert intent.kind is IntentKind.CREATE_NOTE

    plan = build_plan(uuid4(), intent)
    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert step.capability_id == "workspace.create_note"

    decision = evaluate_step(step)
    assert decision.outcome is PolicyOutcome.REQUIRE_APPROVAL
    assert decision.reason_code == "EXPLICIT_USER_APPROVAL_REQUIRED"


def test_when_is_today_uses_deterministic_clock_route() -> None:
    intent = classify_intent("when is today?")
    assert intent.kind is IntentKind.DATETIME_QUERY
    assert intent.entities["datetime_field"] == "date"


def test_task_progress_projects_authoritative_completed_state() -> None:
    session_id = uuid4()
    service = CoreSimulatorService()
    task = service.create_task(
        TaskRequest(
            request_id=uuid4(),
            channel=Channel.TEXT,
            utterance="hello",
            user_session_id=session_id,
            requested_at=datetime.now(UTC),
        ),
        IdentitySession(
            session_id=session_id,
            authenticated=True,
        ),
    )

    progress = task_progress(task)
    assert progress.authoritative_state == "completed"
    assert progress.phase == "done"
    assert progress.progress_percent == 100
    assert progress.terminal is True
    assert progress.retry == "not_applicable"


def test_device_runtime_status_is_safe_when_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEXUSS_DEVICE_NODE_URL", raising=False)
    monkeypatch.delenv("NEXUSS_DEVICE_NODE_SECRET", raising=False)

    status = inspect_device_node_runtime()
    assert status["configured"] is False
    assert status["reachable"] is False
    assert status["reason_code"] == "TRUSTED_DEVICE_NODE_NOT_CONFIGURED"
    assert "secret" not in status


def test_disabled_device_client_fails_closed() -> None:
    client = DisabledDeviceNodeClient()
    with pytest.raises(
        DeviceCommandError,
        match="TRUSTED_DEVICE_NODE_NOT_CONFIGURED",
    ):
        client.open_web_search(
            UUID("00000000-0000-0000-0000-000000000001"),
            "windows-primary",
            "https://www.google.com/search?q=forex",
        )


def test_deterministic_runtime_routes() -> None:
    from nexuss.conversation.stabilization import deterministic_route_result
    note = deterministic_route_result("Create a managed note named p612-validation with the content: governed note validation.")
    assert note is not None and note.classification.capability_hint == "workspace.create_note"
    assert note.classification.action_instruction is not None
    assert note.classification.action_instruction.endswith("governed note validation.")
    clock = deterministic_route_result("whats the time now")
    assert clock is not None and clock.provider_id == "nexuss_local_clock"
    date = deterministic_route_result("when is today?")
    assert date is not None and date.provider_id == "nexuss_local_clock"
    research = deterministic_route_result("can you use deepseek to research on crypto today")
    assert research is not None and research.classification.capability_hint == "knowledge.web_research"
    assert "evidence source" in research.classification.response
