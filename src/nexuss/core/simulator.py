"""Deterministic capability simulator for P1."""

from datetime import UTC, datetime

from nexuss.domain.models import CapabilityResult, EvidenceRecord, PlanStep, StepStatus

_SIMULATED_ATTRIBUTES: dict[str, dict[str, object]] = {
    "calendar.read_summary": {"events": 2, "source_mode": "simulated"},
    "email.read_summary": {"unread_priority": 3, "source_mode": "simulated"},
    "github.read_summary": {"repositories": 4, "open_pull_requests": 1, "source_mode": "simulated"},
    "ats.read_health": {"status": "healthy", "mode": "read_only_simulated"},
    "ats.read_intelligence": {
        "status": "available",
        "mode": "read_only_simulated",
        "market_signal": "not_real_data",
    },
    "nexuss.read_health": {"status": "ready", "mode": "p2_ui_local_readonly"},
    "media.prepare_playback": {"status": "prepared", "source_mode": "simulated"},
}


def execute_step(step: PlanStep, observed_at: datetime | None = None) -> CapabilityResult:
    timestamp = observed_at or datetime.now(UTC)
    attributes = _SIMULATED_ATTRIBUTES.get(step.capability_id)
    if attributes is None:
        return CapabilityResult(
            step_id=step.step_id,
            capability_id=step.capability_id,
            status=StepStatus.FAILED,
            evidence=[],
            error_code="SIMULATOR_CAPABILITY_NOT_FOUND",
        )

    evidence = EvidenceRecord(
        source=f"simulator:{step.capability_id}",
        observed_at=timestamp,
        attributes=attributes,
    )
    return CapabilityResult(
        step_id=step.step_id,
        capability_id=step.capability_id,
        status=StepStatus.VERIFIED,
        evidence=[evidence],
    )
