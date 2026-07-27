"""Planner and capability-registry policy boundary tests."""

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
    assert decision.reason_code == "CAPABILITY_PROHIBITED_BY_POLICY"


def test_unreleased_workspace_preparation_is_denied() -> None:
    plan = build_plan(TASK_ID, classify_intent("Prepare my workspace"))
    decision = evaluate_step(plan.steps[0])

    assert decision.outcome is PolicyOutcome.DENY


def test_create_note_requires_exact_user_approval() -> None:
    plan = build_plan(
        TASK_ID,
        classify_intent("Create a note called P3 test with content validation complete"),
    )
    decision = evaluate_step(plan.steps[0])

    assert plan.steps[0].capability_id == "workspace.create_note"
    assert plan.steps[0].reversible is True
    assert decision.outcome is PolicyOutcome.REQUIRE_APPROVAL
    assert decision.reason_code == "EXPLICIT_USER_APPROVAL_REQUIRED"


def test_identity_response_is_allowed_without_side_effect() -> None:
    plan = build_plan(TASK_ID, classify_intent("Who are you?"))
    decision = evaluate_step(plan.steps[0])

    assert plan.steps[0].capability_id == "assistant.respond"
    assert decision.outcome is PolicyOutcome.ALLOW
    assert decision.reason_code == "INFORMATIONAL_NO_SIDE_EFFECT"


def test_youtube_phone_handoff_is_low_risk_and_requires_no_approval() -> None:
    plan = build_plan(
        TASK_ID,
        classify_intent(
            "Open YouTube on my phone and search Silence by Popcaan"
        ),
    )
    decision = evaluate_step(plan.steps[0])

    assert plan.steps[0].capability_id == "phone.open_youtube"
    assert plan.steps[0].risk_tier.value == "low"
    assert decision.outcome is PolicyOutcome.ALLOW
