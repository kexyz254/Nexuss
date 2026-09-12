from uuid import uuid4

from nexuss.core.intents import classify_intent
from nexuss.core.planner import build_plan
from nexuss.domain.models import IntentKind


def test_repair_instruction_classifies_and_plans_high_risk_capability():
    intent = classify_intent(
        "Repair latest failed engineering build: P6.15 New Chat smoke slice"
    )
    assert intent.kind is IntentKind.ENGINEERING_REPAIR_FAILED_BUILD
    plan = build_plan(uuid4(), intent)
    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert step.capability_id == "engineering.repair_failed_build"
    assert step.risk_tier.value == "high"
