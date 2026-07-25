"""Application service coordinating the complete Nexuss P2 task lifecycle."""

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from nexuss.core.executor import execute_step
from nexuss.core.intents import classify_intent
from nexuss.core.ledger import InMemoryActionLedger
from nexuss.core.planner import build_plan
from nexuss.core.policy import evaluate_step
from nexuss.domain.models import (
    ActionReceipt,
    CapabilityResult,
    IdentitySession,
    PolicyOutcome,
    StepStatus,
    TaskRequest,
    TaskState,
    TaskView,
)


class InvalidSessionError(ValueError):
    """Raised when a request is not backed by an authenticated matching session."""


class TaskNotFoundError(LookupError):
    """Raised when a requested task does not exist."""


class CoreSimulatorService:
    def __init__(self) -> None:
        self._tasks: dict[UUID, TaskView] = {}
        self._request_index: dict[UUID, UUID] = {}
        self._ledger = InMemoryActionLedger()

    def create_task(self, request: TaskRequest, session: IdentitySession) -> TaskView:
        existing_task_id = self._request_index.get(request.request_id)
        if existing_task_id is not None:
            return self._tasks[existing_task_id]

        if not session.authenticated or session.session_id != request.user_session_id:
            raise InvalidSessionError("Authenticated session does not match the request")

        task_id = uuid5(NAMESPACE_URL, f"nexuss:task:{request.request_id}")
        now = datetime.now(UTC)
        intent = classify_intent(request.utterance)
        plan = build_plan(task_id, intent)
        decisions = [evaluate_step(step) for step in plan.steps]

        if any(decision.outcome is PolicyOutcome.DENY for decision in decisions):
            state = TaskState.DENIED
            results: list[CapabilityResult] = []
        elif any(decision.outcome is PolicyOutcome.REQUIRE_APPROVAL for decision in decisions):
            state = TaskState.AWAITING_APPROVAL
            results = []
        else:
            results = [execute_step(step, observed_at=now) for step in plan.steps]
            verified = bool(results) and all(
                result.status is StepStatus.VERIFIED for result in results
            )
            state = TaskState.COMPLETED if verified else TaskState.FAILED

        task = TaskView(
            task_id=task_id,
            request_id=request.request_id,
            state=state,
            intent=intent,
            plan=plan,
            policy_decisions=decisions,
            results=results,
            created_at=now,
            updated_at=now,
        )
        self._tasks[task_id] = task
        self._request_index[request.request_id] = task_id

        receipt = ActionReceipt(
            receipt_id=uuid5(NAMESPACE_URL, f"nexuss:receipt:{task_id}"),
            task_id=task_id,
            request_id=request.request_id,
            state=state,
            intent=intent,
            plan_id=plan.plan_id,
            policy_decisions=decisions,
            results=results,
            created_at=now,
            verified=state is TaskState.COMPLETED,
        )
        self._ledger.append(receipt)
        return task

    def get_task(self, task_id: UUID) -> TaskView:
        task = self._tasks.get(task_id)
        if task is None:
            raise TaskNotFoundError(str(task_id))
        return task

    def get_receipt(self, task_id: UUID) -> ActionReceipt:
        receipt = self._ledger.get(task_id)
        if receipt is None:
            raise TaskNotFoundError(str(task_id))
        return receipt
