"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Validated Nexuss task-state transitions.
"""

from nexuss.domain.models import TaskState

_ALLOWED_TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    TaskState.RECEIVED: frozenset({TaskState.PLANNED, TaskState.FAILED}),
    TaskState.PLANNED: frozenset(
        {TaskState.AWAITING_APPROVAL, TaskState.EXECUTING, TaskState.DENIED, TaskState.FAILED}
    ),
    TaskState.AWAITING_APPROVAL: frozenset(
        {TaskState.APPROVED, TaskState.DENIED, TaskState.FAILED}
    ),
    TaskState.APPROVED: frozenset({TaskState.EXECUTING, TaskState.FAILED}),
    TaskState.EXECUTING: frozenset(
        {TaskState.VERIFYING, TaskState.FAILED, TaskState.PARTIALLY_COMPLETED}
    ),
    TaskState.VERIFYING: frozenset(
        {TaskState.COMPLETED, TaskState.FAILED, TaskState.PARTIALLY_COMPLETED}
    ),
    TaskState.COMPLETED: frozenset({TaskState.ROLLING_BACK}),
    TaskState.ROLLING_BACK: frozenset({TaskState.ROLLED_BACK, TaskState.FAILED}),
    TaskState.PARTIALLY_COMPLETED: frozenset({TaskState.ROLLING_BACK}),
    TaskState.DENIED: frozenset(),
    TaskState.FAILED: frozenset(),
    TaskState.ROLLED_BACK: frozenset(),
}


class InvalidStateTransitionError(RuntimeError):
    """Raised when lifecycle code attempts a transition outside the state contract."""


def validate_transition(current: TaskState, target: TaskState) -> None:
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise InvalidStateTransitionError(f"Invalid Nexuss transition: {current} -> {target}")
