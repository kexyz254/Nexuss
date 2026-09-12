from uuid import uuid4

from nexuss.core.intents import classify_intent
from nexuss.core.planner import build_plan
from nexuss.core.registry import get_capability
from nexuss.domain.models import IntentKind


def test_acceptance_capability_is_registered_read_only():
    manifest = get_capability("engineering.verify_acceptance")
    assert manifest is not None
    assert manifest.risk_tier.value == "low"
    assert manifest.approval_policy.value == "none"
    assert manifest.execution_mode == "deterministic_local_readonly"


def test_build_capability_is_high_risk():
    manifest = get_capability("engineering.build_artifact")
    assert manifest is not None
    assert manifest.risk_tier.value == "high"


def test_acceptance_instruction_plans_deterministically():
    intent = classify_intent("Verify engineering acceptance: P6.14")
    assert intent.kind is IntentKind.ENGINEERING_VERIFY_ACCEPTANCE
    plan = build_plan(uuid4(), intent)
    assert len(plan.steps) == 1
    assert plan.steps[0].capability_id == "engineering.verify_acceptance"
