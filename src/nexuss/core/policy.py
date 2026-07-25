"""Fail-closed policy evaluation for the P1 simulator."""

from nexuss.domain.models import PlanStep, PolicyDecision, PolicyOutcome, RiskTier

_ALLOWLIST = {
    "calendar.read_summary",
    "email.read_summary",
    "github.read_summary",
    "ats.read_health",
    "ats.read_intelligence",
    "nexuss.read_health",
    "media.prepare_playback",
}

_REQUIRE_APPROVAL = {"device.workspace.prepare"}

_DENYLIST = {
    "ats.write_order",
    "finance.transfer",
    "social.publish",
    "nexuss.unsupported",
}


def evaluate_step(step: PlanStep) -> PolicyDecision:
    if step.capability_id in _DENYLIST:
        return PolicyDecision(
            step_id=step.step_id,
            capability_id=step.capability_id,
            outcome=PolicyOutcome.DENY,
            reason_code="CAPABILITY_PROHIBITED_IN_P1",
            explanation="The requested capability is excluded from the P1 simulator.",
        )

    if step.capability_id in _REQUIRE_APPROVAL:
        return PolicyDecision(
            step_id=step.step_id,
            capability_id=step.capability_id,
            outcome=PolicyOutcome.REQUIRE_APPROVAL,
            reason_code="USER_APPROVAL_REQUIRED",
            explanation="Workspace preparation requires explicit user approval.",
        )

    if step.capability_id in _ALLOWLIST and step.risk_tier is RiskTier.LOW:
        return PolicyDecision(
            step_id=step.step_id,
            capability_id=step.capability_id,
            outcome=PolicyOutcome.ALLOW,
            reason_code="READ_ONLY_LOW_RISK",
            explanation="The capability is read-only or simulated and low risk.",
        )

    return PolicyDecision(
        step_id=step.step_id,
        capability_id=step.capability_id,
        outcome=PolicyOutcome.DENY,
        reason_code="FAIL_CLOSED_UNCLASSIFIED_CAPABILITY",
        explanation="No explicit policy authorizes this capability.",
    )
