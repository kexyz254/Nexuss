"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Capability execution router for Nexuss P4 verified local and trusted-device capabilities.
"""

from datetime import UTC, datetime
from uuid import UUID

from nexuss.core.local_workspace import (
    LocalWorkspaceEvidenceError,
    collect_local_workspace_status,
)
from nexuss.core.managed_notes import ManagedNoteStore, PreparedNote
from nexuss.core.simulator import execute_step as execute_simulated_step
from nexuss.device.client import DeviceCommandError, DeviceNodeClient
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


def _execute_launch_notepad(
    step: PlanStep,
    timestamp: datetime,
    task_id: UUID,
    device_client: DeviceNodeClient,
) -> CapabilityResult:
    target_node_id = str(step.parameters.get("target_node_id", "windows-primary"))
    try:
        evidence = device_client.launch_notepad(task_id, target_node_id)
    except DeviceCommandError:
        return CapabilityResult(
            step_id=step.step_id,
            capability_id=step.capability_id,
            status=StepStatus.FAILED,
            evidence=[],
            error_code="TRUSTED_DEVICE_COMMAND_FAILED",
        )
    return CapabilityResult(
        step_id=step.step_id,
        capability_id=step.capability_id,
        status=StepStatus.VERIFIED if evidence.verified_running else StepStatus.FAILED,
        evidence=[
            EvidenceRecord(
                source="device:windows-node",
                observed_at=timestamp,
                attributes={
                    "source_mode": evidence.source_mode,
                    "command_id": str(evidence.command_id),
                    "node_id": evidence.node_id,
                    "node_hostname": evidence.node_hostname,
                    "executable": evidence.executable,
                    "process_id": evidence.process_id,
                    "started_at": evidence.started_at.isoformat(),
                    "verified_running": evidence.verified_running,
                    "reversible": True,
                },
            )
        ],
        error_code=None if evidence.verified_running else "DEVICE_PROCESS_NOT_RUNNING",
    )


def execute_step(
    step: PlanStep,
    observed_at: datetime | None = None,
    *,
    note_store: ManagedNoteStore | None = None,
    device_client: DeviceNodeClient | None = None,
    task_id: UUID | None = None,
) -> CapabilityResult:
    timestamp = observed_at or datetime.now(UTC)

    if step.capability_id == "assistant.respond":
        return _execute_assistant_response(step, timestamp)

    if step.capability_id == "workspace.create_note":
        if note_store is None:
            raise RuntimeError("ManagedNoteStore is required for controlled writes")
        return _execute_create_note(step, timestamp, note_store)

    if step.capability_id == "device.launch_notepad":
        if task_id is None or device_client is None:
            return CapabilityResult(
                step_id=step.step_id,
                capability_id=step.capability_id,
                status=StepStatus.FAILED,
                evidence=[],
                error_code="TRUSTED_DEVICE_NODE_NOT_CONFIGURED",
            )
        return _execute_launch_notepad(step, timestamp, task_id, device_client)

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
