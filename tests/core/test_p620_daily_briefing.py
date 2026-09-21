from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from nexuss.commitments.models import PrepareDayRequest, WorkdayBrief
from nexuss.core.executor import _execute_prepare_day
from nexuss.core.intents import classify_intent
from nexuss.core.planner import build_plan
from nexuss.domain.models import IntentKind, StepStatus


class _Commitments:
    def __init__(self, brief: WorkdayBrief) -> None:
        self.brief = brief
        self.request: PrepareDayRequest | None = None

    def prepare_day(
        self,
        request: PrepareDayRequest,
        *,
        now: datetime | None = None,
    ) -> WorkdayBrief:
        self.request = request
        return self.brief


def test_daily_briefing_plans_live_commitment_intelligence() -> None:
    intent = classify_intent("Give me my daily briefing.")
    assert intent.kind is IntentKind.DAILY_BRIEFING

    plan = build_plan(uuid4(), intent)

    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert step.capability_id == "commitments.prepare_day"
    assert step.parameters["timezone"] == "Africa/Nairobi"
    assert step.parameters["include_mobile"] is True


def test_prepare_day_returns_user_facing_read_only_brief() -> None:
    now = datetime(2026, 9, 21, 7, 0, tzinfo=UTC)
    brief = WorkdayBrief(
        planning_date=now.date(),
        timezone="Africa/Nairobi",
        connected_google_account=None,
        source_status={
            "gmail": False,
            "calendar": False,
            "contacts": False,
            "mobile": False,
        },
        commitments=(),
        calendar_events=(),
        conflicts=(),
        focus_blocks=(),
        urgent_count=0,
        overdue_count=0,
        responses_needed=0,
    )
    service = _Commitments(brief)

    plan = build_plan(
        uuid4(),
        classify_intent("Give me my daily briefing."),
    )
    result = _execute_prepare_day(
        plan.steps[0],
        now,
        service,  # type: ignore[arg-type]
    )

    assert result.status is StepStatus.VERIFIED
    display = result.evidence[0].attributes["display_text"]
    assert "Operational brief" in display
    assert "Read-only brief" in display
    assert "Unavailable sources" in display
    assert service.request is not None
    assert service.request.include_mobile is True


def test_application_attaches_single_commitment_runtime_to_core() -> None:
    source = Path("src/nexuss/api/app.py").read_text(encoding="utf-8")
    assert "commitment_service = CommitmentIntelligenceService(" in source
    assert "service.set_commitment_service(commitment_service)" in source
