"""Capability execution router for simulated and live read-only P2 capabilities."""

from datetime import UTC, datetime

from nexuss.core.local_workspace import (
    LocalWorkspaceEvidenceError,
    collect_local_workspace_status,
)
from nexuss.core.simulator import execute_step as execute_simulated_step
from nexuss.domain.models import CapabilityResult, EvidenceRecord, PlanStep, StepStatus


def execute_step(step: PlanStep, observed_at: datetime | None = None) -> CapabilityResult:
    if step.capability_id != "workspace.read_status":
        return execute_simulated_step(step, observed_at=observed_at)

    timestamp = observed_at or datetime.now(UTC)
    try:
        attributes = collect_local_workspace_status(
            observed_at=timestamp,
        )
    except LocalWorkspaceEvidenceError:
        return CapabilityResult(
            step_id=step.step_id,
            capability_id=step.capability_id,
            status=StepStatus.FAILED,
            evidence=[],
            error_code="LOCAL_WORKSPACE_EVIDENCE_UNAVAILABLE",
        )

    evidence = EvidenceRecord(
        source="local:workspace",
        observed_at=timestamp,
        attributes=attributes,
    )
    return CapabilityResult(
        step_id=step.step_id,
        capability_id=step.capability_id,
        status=StepStatus.VERIFIED,
        evidence=[evidence],
    )
