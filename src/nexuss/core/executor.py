"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Capability execution router for Nexuss P3 verified capabilities.
"""

from datetime import UTC, datetime

from nexuss.core.local_workspace import (
    LocalWorkspaceEvidenceError,
    collect_local_workspace_status,
)
from nexuss.core.managed_notes import ManagedNoteStore, PreparedNote
from nexuss.core.simulator import execute_step as execute_simulated_step
from nexuss.domain.models import CapabilityResult, EvidenceRecord, PlanStep, StepStatus


def _execute_assistant_response(step: PlanStep, timestamp: datetime) -> CapabilityResult:
    response = str(step.parameters.get("response", ""))
    if not response:
        return CapabilityResult(
            step_id=step.step_id,
            capability_id=step.capability_id,
            status=StepStatus.FAILED,
            evidence=[],
            error_code="ASSISTANT_RESPONSE_MISSING",
        )
    return CapabilityResult(
        step_id=step.step_id,
        capability_id=step.capability_id,
        status=StepStatus.VERIFIED,
        evidence=[
            EvidenceRecord(
                source="nexuss:deterministic_response",
                observed_at=timestamp,
                attributes={"response": response, "source_mode": "deterministic_local"},
            )
        ],
    )


def _execute_create_note(
    step: PlanStep,
    timestamp: datetime,
    note_store: ManagedNoteStore,
) -> CapabilityResult:
    prepared = PreparedNote(
        title=str(step.parameters["title"]),
        filename=str(step.parameters["filename"]),
        content=str(step.parameters["content"]),
        content_bytes=str(step.parameters["content"]).encode("utf-8"),
        content_sha256=str(step.parameters["content_sha256"]),
    )
    created = note_store.create(prepared)
    return CapabilityResult(
        step_id=step.step_id,
        capability_id=step.capability_id,
        status=StepStatus.VERIFIED,
        evidence=[
            EvidenceRecord(
                source="local:managed_workspace",
                observed_at=timestamp,
                attributes={
                    "source_mode": "live_local_controlled_write",
                    "filename": created.filename,
                    "managed_path": str(created.path),
                    "byte_count": created.byte_count,
                    "sha256": created.sha256,
                    "verified": True,
                    "reversible": True,
                },
            )
        ],
    )


def execute_step(
    step: PlanStep,
    observed_at: datetime | None = None,
    *,
    note_store: ManagedNoteStore | None = None,
) -> CapabilityResult:
    timestamp = observed_at or datetime.now(UTC)

    if step.capability_id == "assistant.respond":
        return _execute_assistant_response(step, timestamp)

    if step.capability_id == "workspace.create_note":
        if note_store is None:
            raise RuntimeError("ManagedNoteStore is required for controlled writes")
        return _execute_create_note(step, timestamp, note_store)

    if step.capability_id == "workspace.read_status":
        try:
            attributes = collect_local_workspace_status(observed_at=timestamp)
        except LocalWorkspaceEvidenceError:
            return CapabilityResult(
                step_id=step.step_id,
                capability_id=step.capability_id,
                status=StepStatus.FAILED,
                evidence=[],
                error_code="LOCAL_WORKSPACE_EVIDENCE_UNAVAILABLE",
            )

        return CapabilityResult(
            step_id=step.step_id,
            capability_id=step.capability_id,
            status=StepStatus.VERIFIED,
            evidence=[
                EvidenceRecord(
                    source="local:workspace",
                    observed_at=timestamp,
                    attributes=attributes,
                )
            ],
        )

    return execute_simulated_step(step, observed_at=timestamp)
