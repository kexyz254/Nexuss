from __future__ import annotations

from uuid import uuid4

from nexuss.core.intents import classify_intent
from nexuss.core.planner import build_plan
from nexuss.core.policy import evaluate_step
from nexuss.domain.models import (
    Intent,
    IntentKind,
    PolicyOutcome,
)


def test_update_status_phrase_is_read_only() -> None:
    intent = classify_intent("Check for Nexuss updates.")
    assert intent.kind is IntentKind.SYSTEM_UPDATE_STATUS

    plan = build_plan(uuid4(), intent)
    assert [step.capability_id for step in plan.steps] == [
        "system.update.inspect"
    ]
    decision = evaluate_step(plan.steps[0])
    assert decision.outcome is PolicyOutcome.ALLOW


def test_update_apply_is_bound_to_exact_shas_and_requires_approval() -> None:
    current = "1" * 40
    target = "2" * 40
    intent = Intent(
        kind=IntentKind.SYSTEM_UPDATE_APPLY,
        normalized_text="update nexuss",
        confidence=1.0,
        entities={
            "branch": "feature/p5-knowledge-media-mobile",
            "current_sha": current,
            "target_sha": target,
        },
    )

    plan = build_plan(uuid4(), intent)
    step = plan.steps[0]

    assert step.capability_id == "system.update.apply"
    assert step.parameters["expected_current_sha"] == current
    assert step.parameters["expected_target_sha"] == target
    assert evaluate_step(step).outcome is PolicyOutcome.REQUIRE_APPROVAL


def test_update_contract_denies_moving_or_missing_target() -> None:
    current = "1" * 40
    intent = Intent(
        kind=IntentKind.SYSTEM_UPDATE_APPLY,
        normalized_text="update nexuss",
        confidence=1.0,
        entities={
            "branch": "feature/p5-knowledge-media-mobile",
            "current_sha": current,
            "target_sha": current,
        },
    )
    decision = evaluate_step(build_plan(uuid4(), intent).steps[0])
    assert decision.outcome is PolicyOutcome.DENY
    assert decision.reason_code == "LOCAL_UPDATE_CONTRACT_INVALID"


def test_system_health_uses_live_system_intelligence() -> None:
    intent = classify_intent("Run system diagnostics.")
    assert intent.kind is IntentKind.SYSTEM_HEALTH
    plan = build_plan(uuid4(), intent)
    assert [step.capability_id for step in plan.steps] == [
        "system.runtime.inspect"
    ]
