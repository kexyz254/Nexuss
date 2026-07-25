"""Capability registry and lifecycle-state contract tests."""

import pytest

from nexuss.core.registry import get_capability, list_capabilities
from nexuss.core.state_machine import InvalidStateTransitionError, validate_transition
from nexuss.domain.models import ApprovalPolicy, CapabilityStatus, TaskState


def test_active_write_capability_is_explicitly_registered() -> None:
    manifest = get_capability("workspace.create_note")

    assert manifest is not None
    assert manifest.status is CapabilityStatus.ACTIVE
    assert manifest.approval_policy is ApprovalPolicy.EXPLICIT
    assert manifest.reversible is True


def test_registry_has_unique_capability_ids() -> None:
    identifiers = [manifest.capability_id for manifest in list_capabilities()]
    assert len(identifiers) == len(set(identifiers))


def test_valid_approval_lifecycle_transitions() -> None:
    validate_transition(TaskState.RECEIVED, TaskState.PLANNED)
    validate_transition(TaskState.PLANNED, TaskState.AWAITING_APPROVAL)
    validate_transition(TaskState.AWAITING_APPROVAL, TaskState.APPROVED)
    validate_transition(TaskState.APPROVED, TaskState.EXECUTING)
    validate_transition(TaskState.EXECUTING, TaskState.VERIFYING)
    validate_transition(TaskState.VERIFYING, TaskState.COMPLETED)


def test_completed_task_cannot_return_to_execution() -> None:
    with pytest.raises(InvalidStateTransitionError):
        validate_transition(TaskState.COMPLETED, TaskState.EXECUTING)
