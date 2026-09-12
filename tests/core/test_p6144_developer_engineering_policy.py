from uuid import uuid4

from nexuss.core.policy import evaluate_step
from nexuss.domain.models import PlanStep, PolicyOutcome, RiskTier


def _step(capability_id: str, risk: RiskTier) -> PlanStep:
    return PlanStep(
        step_id=uuid4(),
        order=1,
        capability_id=capability_id,
        risk_tier=risk,
        expected_evidence=["receipt"],
        parameters={"target": "latest failed build", "goal": "bounded build"},
        reversible=False,
    )


def test_build_requires_exact_mission_approval_even_in_developer_env(monkeypatch):
    monkeypatch.setenv("NEXUSS_DEVELOPER_SELF_BUILD", "1")
    decision = evaluate_step(_step("engineering.build_artifact", RiskTier.HIGH))
    assert decision.outcome is PolicyOutcome.REQUIRE_APPROVAL
    assert decision.reason_code == "DEVELOPER_ENGINEERING_MISSION_APPROVAL_REQUIRED"


def test_failed_build_repair_requires_exact_mission_approval():
    decision = evaluate_step(
        _step("engineering.repair_failed_build", RiskTier.HIGH)
    )
    assert decision.outcome is PolicyOutcome.REQUIRE_APPROVAL
    assert decision.reason_code == "DEVELOPER_ENGINEERING_MISSION_APPROVAL_REQUIRED"


def test_acceptance_verification_remains_read_only_allow():
    decision = evaluate_step(
        _step("engineering.verify_acceptance", RiskTier.LOW)
    )
    assert decision.outcome is PolicyOutcome.ALLOW
