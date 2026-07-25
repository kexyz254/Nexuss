"""Deterministic task planning for the P1 simulator."""

from uuid import NAMESPACE_URL, UUID, uuid5

from nexuss.domain.models import Intent, IntentKind, PlanStep, RiskTier, TaskPlan


def _step_id(task_id: UUID, order: int, capability_id: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"nexuss:{task_id}:{order}:{capability_id}")


def build_plan(task_id: UUID, intent: Intent) -> TaskPlan:
    capability_specs: dict[IntentKind, list[tuple[str, RiskTier, list[str]]]] = {
        IntentKind.DAILY_BRIEFING: [
            ("calendar.read_summary", RiskTier.LOW, ["calendar_snapshot"]),
            ("email.read_summary", RiskTier.LOW, ["email_snapshot"]),
            ("github.read_summary", RiskTier.LOW, ["repository_snapshot"]),
            ("ats.read_health", RiskTier.LOW, ["ats_health_snapshot"]),
        ],
        IntentKind.SYSTEM_HEALTH: [
            ("nexuss.read_health", RiskTier.LOW, ["health_snapshot"]),
        ],
        IntentKind.PREPARE_WORKSPACE: [
            ("device.workspace.prepare", RiskTier.MEDIUM, ["workspace_state"]),
        ],
        IntentKind.PLAY_MEDIA: [
            ("media.prepare_playback", RiskTier.LOW, ["playback_state"]),
        ],
        IntentKind.ATS_READ: [
            ("ats.read_intelligence", RiskTier.LOW, ["ats_intelligence_snapshot"]),
        ],
        IntentKind.ATS_WRITE: [
            ("ats.write_order", RiskTier.CRITICAL, ["trade_confirmation"]),
        ],
        IntentKind.FINANCIAL_TRANSFER: [
            ("finance.transfer", RiskTier.CRITICAL, ["transaction_receipt"]),
        ],
        IntentKind.SOCIAL_PUBLISH: [
            ("social.publish", RiskTier.HIGH, ["published_post"]),
        ],
        IntentKind.UNKNOWN: [
            ("nexuss.unsupported", RiskTier.HIGH, ["unsupported_reason"]),
        ],
    }

    specs = capability_specs[intent.kind]
    steps = [
        PlanStep(
            step_id=_step_id(task_id, order, capability_id),
            order=order,
            capability_id=capability_id,
            risk_tier=risk,
            expected_evidence=evidence,
        )
        for order, (capability_id, risk, evidence) in enumerate(specs, start=1)
    ]
    plan_id = uuid5(NAMESPACE_URL, f"nexuss:{task_id}:plan:{intent.kind}")
    return TaskPlan(plan_id=plan_id, task_id=task_id, intent=intent, steps=steps)
