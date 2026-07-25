"""Planner and policy boundary tests."""

from uuid import UUID

from nexuss.core.intents import classify_intent
from nexuss.core.planner import build_plan
from nexuss.core.policy import evaluate_step
from nexuss.domain.models import PolicyOutcome

TASK_ID = UUID("00000000-0000-0000-0000-000000000101")


def test_daily_briefing_plan_is_deterministic() -> None:
    intent = classify_intent("daily briefing")
    first = build_plan(TASK_ID, intent)
    second = build_plan(TASK_ID, intent)

    assert first == second
    assert [step.capability_id for step in first.steps] == [
        "calendar.read_summary",
        "email.read_summary",
        "github.read_summary",
        "ats.read_health",
    ]


def test_ats_write_is_denied_before_execution() -> None:
    plan = build_plan(TASK_ID, classify_intent("ATS sell BTC"))
    decision = evaluate_step(plan.steps[0])

    assert decision.outcome is PolicyOutcome.DENY
    assert decision.reason_code == "CAPABILITY_PROHIBITED_IN_P1"


def test_workspace_preparation_requires_approval() -> None:
    plan = build_plan(TASK_ID, classify_intent("Prepare my workspace"))
    decision = evaluate_step(plan.steps[0])

    assert decision.outcome is PolicyOutcome.REQUIRE_APPROVAL
