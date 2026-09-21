'''Certified autonomous execution through Nexuss Core.'''

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from nexuss.capabilities.models import CapabilityMappingState
from nexuss.domain.models import Channel, IdentitySession, TaskRequest
from nexuss.orchestration.autonomy_models import (
    AutonomyMode,
    AutonomousLifecycleEvent,
    AutonomousRunReceipt,
    AutonomousRunResponse,
    AutonomousRunState,
    AutonomousStepRecord,
    AutonomousStepState,
)
from nexuss.orchestration.models import UniversalActionPlanResponse


class BoundedAutonomyError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _required(arguments: dict[str, object], key: str, maximum: int) -> str:
    value = str(arguments.get(key, "")).strip()
    if not value:
        raise BoundedAutonomyError(
            "AUTONOMY_ARGUMENT_REQUIRED",
            f"Certified adapter requires {key!r}.",
        )
    if len(value) > maximum:
        raise BoundedAutonomyError(
            "AUTONOMY_ARGUMENT_TOO_LONG",
            f"Argument {key!r} is outside the certified bound.",
        )
    return value


def _none(arguments: dict[str, object]) -> str:
    if arguments:
        raise BoundedAutonomyError(
            "AUTONOMY_ARGUMENTS_UNEXPECTED",
            "This certified capability accepts no provider arguments.",
        )
    return ""


def _workspace(arguments: dict[str, object]) -> str:
    _none(arguments)
    return "Inspect this local workspace."


def _github_status(arguments: dict[str, object]) -> str:
    _none(arguments)
    return "Check my GitHub connection status."


def _github_list(arguments: dict[str, object]) -> str:
    _none(arguments)
    return "List my GitHub repositories."


def _phones(arguments: dict[str, object]) -> str:
    _none(arguments)
    return "List my paired phones."


def _research(arguments: dict[str, object]) -> str:
    return f"Research {_required(arguments, 'query', 240)}."


def _answer(arguments: dict[str, object]) -> str:
    return _required(arguments, "question", 2_000)


def _media(arguments: dict[str, object]) -> str:
    return f"Find media for {_required(arguments, 'query', 240)}."


def _recall(arguments: dict[str, object]) -> str:
    return f"What do you remember about {_required(arguments, 'query', 500)}?"


def _note(arguments: dict[str, object]) -> str:
    title = _required(arguments, "title", 160)
    content = _required(arguments, "content", 8_000)
    return f"Create a note called {title} with the content: {content}"


def _notepad(arguments: dict[str, object]) -> str:
    _none(arguments)
    return "Open Notepad on this computer."


def _web(arguments: dict[str, object]) -> str:
    return f"Open Chrome and search {_required(arguments, 'query', 240)}."


def _cognitive(
    arguments: dict[str, object],
    verb: str,
) -> str:
    instruction = _required(arguments, "instruction", 8_000)
    return f"{verb} {instruction}"


def _analyze(arguments: dict[str, object]) -> str:
    return _cognitive(arguments, "Analyze")


def _compare(arguments: dict[str, object]) -> str:
    return _cognitive(arguments, "Compare")


def _plan(arguments: dict[str, object]) -> str:
    return _cognitive(arguments, "Plan how to")


def _summarize(arguments: dict[str, object]) -> str:
    return _cognitive(arguments, "Summarize")


def _review(arguments: dict[str, object]) -> str:
    return _cognitive(arguments, "Review")


def _write(arguments: dict[str, object]) -> str:
    return _cognitive(arguments, "Write")


def _rewrite(arguments: dict[str, object]) -> str:
    return _cognitive(arguments, "Rewrite")


def _design(arguments: dict[str, object]) -> str:
    return _cognitive(arguments, "Design")


def _debug(arguments: dict[str, object]) -> str:
    return _cognitive(arguments, "Debug")


def _code(arguments: dict[str, object]) -> str:
    return _cognitive(arguments, "Code")


def _synthesize(arguments: dict[str, object]) -> str:
    return _cognitive(arguments, "Synthesize")


def _create(arguments: dict[str, object]) -> str:
    return _cognitive(arguments, "Brainstorm")


def _repository(arguments: dict[str, object]) -> str:
    name = str(arguments.get("repository_name", arguments.get("name", ""))).strip()
    if not name or len(name) > 100:
        raise BoundedAutonomyError(
            "AUTONOMY_REPOSITORY_NAME_INVALID",
            "A bounded repository name is required.",
        )
    return f"Create a private uninitialized GitHub repository named {name}."


_READ_ADAPTERS: dict[str, Callable[[dict[str, object]], str]] = {
    "workspace.read_status": _workspace,
    "github.connection.status": _github_status,
    "github.repositories.list": _github_list,
    "device.list_phones": _phones,
    "knowledge.web_research": _research,
    "knowledge.answer": _answer,
    "media.youtube.discover": _media,
    "memory.recall": _recall,
    "intelligence.analyze": _analyze,
    "intelligence.compare": _compare,
    "intelligence.plan": _plan,
    "intelligence.summarize": _summarize,
    "intelligence.review": _review,
    "intelligence.write": _write,
    "intelligence.rewrite": _rewrite,
    "intelligence.design": _design,
    "intelligence.debug": _debug,
    "intelligence.code": _code,
    "intelligence.research_synthesis": _synthesize,
    "intelligence.create": _create,
}

_APPROVAL_ADAPTERS: dict[str, Callable[[dict[str, object]], str]] = {
    "workspace.create_note": _note,
    "device.launch_notepad": _notepad,
    "device.open_web_search": _web,
    "github.repository.create": _repository,
}

_READ_MODES = frozenset({
    "deterministic_local",
    "live_local_readonly",
    "live_public_web_readonly",
    "live_github_readonly",
    "official_google_readonly",
    "official_media_connector",
    "cross_channel_readonly_intelligence",
    "proposal_only_cognitive_provider",
})


def certified_autonomy_capabilities() -> dict[str, tuple[str, ...]]:
    return {
        "automatic_read_execution": tuple(sorted(_READ_ADAPTERS)),
        "automatic_approval_preparation": tuple(sorted(_APPROVAL_ADAPTERS)),
    }


def _dump(value: object) -> object:
    method = getattr(value, "model_dump", None)
    if callable(method):
        return method(mode="json")
    data = getattr(value, "__dict__", None)
    if isinstance(data, dict):
        return {k: _dump(v) for k, v in data.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [_dump(item) for item in value]
    return str(value)


def _evidence_hash(task: object, receipt: object) -> str:
    encoded = json.dumps(
        {"task": _dump(task), "receipt": _dump(receipt)},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class BoundedAutonomyService:
    def __init__(self, *, core_service: object) -> None:
        self._core = core_service

    def run(
        self,
        *,
        planning: UniversalActionPlanResponse,
        user_session_id: UUID,
        autonomy_mode: AutonomyMode,
        maximum_runtime_seconds: int,
    ) -> AutonomousRunResponse:
        started = datetime.now(UTC)
        monotonic_start = time.monotonic()
        run_id = uuid5(
            NAMESPACE_URL,
            f"nexuss:bounded-autonomy:{planning.receipt.request_id}",
        )
        identity = IdentitySession(
            session_id=user_session_id,
            authenticated=True,
        )
        steps: list[AutonomousStepRecord] = []
        completed_keys: set[str] = set()

        for mapped in planning.envelope.mapped_actions:
            action = mapped.action
            if time.monotonic() - monotonic_start >= maximum_runtime_seconds:
                steps.append(AutonomousStepRecord(
                    action_key=action.action_key,
                    capability_id=action.capability_id,
                    state=AutonomousStepState.BLOCKED,
                    reason_code="AUTONOMY_RUNTIME_BUDGET_EXHAUSTED",
                    explanation="The bounded runtime budget expired.",
                ))
                break

            missing = [key for key in action.depends_on if key not in completed_keys]
            if missing:
                steps.append(AutonomousStepRecord(
                    action_key=action.action_key,
                    capability_id=action.capability_id,
                    state=AutonomousStepState.PENDING,
                    reason_code="AUTONOMY_DEPENDENCY_PENDING",
                    explanation="Waiting for dependencies: " + ", ".join(missing),
                ))
                continue

            if mapped.mapping_state is not CapabilityMappingState.VERIFIED_EXISTING:
                steps.append(AutonomousStepRecord(
                    action_key=action.action_key,
                    capability_id=action.capability_id,
                    state=AutonomousStepState.BLOCKED,
                    reason_code=mapped.reason_code,
                    explanation=mapped.explanation,
                ))
                break

            is_read = (
                mapped.approval_policy == "none"
                and mapped.execution_mode in _READ_MODES
                and action.capability_id in _READ_ADAPTERS
            )
            is_approval = (
                autonomy_mode is AutonomyMode.SUPERVISED
                and mapped.approval_policy == "explicit"
                and action.capability_id in _APPROVAL_ADAPTERS
            )

            if not is_read and not is_approval:
                steps.append(AutonomousStepRecord(
                    action_key=action.action_key,
                    capability_id=action.capability_id,
                    state=(
                        AutonomousStepState.AWAITING_APPROVAL
                        if mapped.approval_policy == "explicit"
                        else AutonomousStepState.BLOCKED
                    ),
                    reason_code=(
                        "AUTONOMY_APPROVAL_REQUIRED"
                        if mapped.approval_policy == "explicit"
                        else "AUTONOMY_ADAPTER_NOT_CERTIFIED"
                    ),
                    explanation=(
                        "The action requires explicit user approval."
                        if mapped.approval_policy == "explicit"
                        else "No certified autonomy adapter exists."
                    ),
                ))
                break

            record = self._create_core_task(
                run_id=run_id,
                action_key=action.action_key,
                capability_id=action.capability_id,
                arguments=action.arguments,
                adapter=(
                    _READ_ADAPTERS[action.capability_id]
                    if is_read
                    else _APPROVAL_ADAPTERS[action.capability_id]
                ),
                identity=identity,
                expect_approval=is_approval,
            )
            steps.append(record)
            if record.state is AutonomousStepState.COMPLETED:
                completed_keys.add(action.action_key)
                continue
            break

        represented = {step.action_key for step in steps}
        for mapped in planning.envelope.mapped_actions:
            if mapped.action.action_key not in represented:
                steps.append(AutonomousStepRecord(
                    action_key=mapped.action.action_key,
                    capability_id=mapped.action.capability_id,
                    state=AutonomousStepState.PENDING,
                    reason_code="AUTONOMY_WAITING_FOR_PRIOR_STEP",
                    explanation="Waiting behind the current workflow blocker.",
                ))

        completed = sum(step.state is AutonomousStepState.COMPLETED for step in steps)
        approvals = sum(step.state is AutonomousStepState.AWAITING_APPROVAL for step in steps)
        blocked = sum(step.state is AutonomousStepState.BLOCKED for step in steps)
        failed = sum(step.state is AutonomousStepState.FAILED for step in steps)

        if failed:
            state = AutonomousRunState.PARTIAL if completed else AutonomousRunState.FAILED
        elif approvals:
            state = AutonomousRunState.AWAITING_APPROVAL
        elif blocked:
            state = AutonomousRunState.PARTIAL if completed else AutonomousRunState.BLOCKED
        elif any(step.state is AutonomousStepState.PENDING for step in steps):
            state = AutonomousRunState.PARTIAL
        else:
            state = AutonomousRunState.COMPLETED

        blocker = next((
            step.explanation
            for step in steps
            if step.state in {
                AutonomousStepState.AWAITING_APPROVAL,
                AutonomousStepState.BLOCKED,
                AutonomousStepState.FAILED,
            }
        ), None)
        updated = datetime.now(UTC)
        run_payload = {
            "run_id": str(run_id),
            "state": state.value,
            "steps": [step.model_dump(mode="json") for step in steps],
        }
        run_sha256 = hashlib.sha256(json.dumps(
            run_payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")).hexdigest()
        receipt_id = uuid5(
            NAMESPACE_URL,
            f"nexuss:bounded-autonomy-receipt:{run_id}:{run_sha256}",
        )
        events = (
            AutonomousLifecycleEvent(
                sequence=1,
                state="received",
                event_type="bounded_autonomy_received",
                occurred_at=started,
                detail="Nexuss accepted a bounded autonomy request.",
            ),
            AutonomousLifecycleEvent(
                sequence=2,
                state="planned",
                event_type="provider_plan_adopted",
                occurred_at=started,
                detail="Provider actions were mapped to the authoritative Nexuss registry.",
            ),
            AutonomousLifecycleEvent(
                sequence=3,
                state=state.value,
                event_type="bounded_autonomy_stopped",
                occurred_at=updated,
                detail=f"Run stopped in {state.value} after {completed} verified steps.",
            ),
        )
        receipt = AutonomousRunReceipt(
            receipt_id=receipt_id,
            receipt_type="bounded_autonomy_run",
            run_id=run_id,
            request_id=planning.receipt.request_id,
            provider_id=planning.envelope.plan.provider_id,
            model=planning.envelope.plan.model,
            plan_receipt_id=planning.receipt.receipt_id,
            run_sha256=run_sha256,
            events=events,
            created_at=updated,
        )
        return AutonomousRunResponse(
            run_id=run_id,
            request_id=planning.receipt.request_id,
            user_session_id=user_session_id,
            state=state,
            autonomy_mode=autonomy_mode,
            provider_id=planning.envelope.plan.provider_id,
            provider_display_name=planning.envelope.provider.display_name,
            model=planning.envelope.plan.model,
            summary=planning.envelope.plan.summary,
            response=planning.envelope.plan.response,
            plan_receipt_id=planning.receipt.receipt_id,
            steps=tuple(steps),
            completed_count=completed,
            awaiting_approval_count=approvals,
            blocked_count=blocked,
            failed_count=failed,
            current_blocker=blocker,
            created_at=started,
            updated_at=updated,
            receipt=receipt,
        )

    def _create_core_task(
        self,
        *,
        run_id: UUID,
        action_key: str,
        capability_id: str,
        arguments: dict[str, object],
        adapter: Callable[[dict[str, object]], str],
        identity: IdentitySession,
        expect_approval: bool,
    ) -> AutonomousStepRecord:
        try:
            utterance = adapter(arguments)
            request = TaskRequest(
                request_id=uuid5(
                    NAMESPACE_URL,
                    f"nexuss:autonomy-task:{run_id}:{action_key}:{capability_id}",
                ),
                channel=Channel.TEXT,
                utterance=utterance,
                user_session_id=identity.session_id,
                target_devices=[],
                requested_at=datetime.now(UTC),
                client_context={
                    "source": "bounded_autonomy",
                    "run_id": str(run_id),
                    "action_key": action_key,
                    "expected_capability_id": capability_id,
                },
            )
            task = self._core.create_task(request, identity)
        except BoundedAutonomyError as exc:
            return AutonomousStepRecord(
                action_key=action_key,
                capability_id=capability_id,
                state=AutonomousStepState.BLOCKED,
                reason_code=exc.code,
                explanation=str(exc),
            )
        except Exception as exc:
            return AutonomousStepRecord(
                action_key=action_key,
                capability_id=capability_id,
                state=AutonomousStepState.FAILED,
                reason_code="AUTONOMY_CORE_TASK_FAILED",
                explanation="Nexuss Core could not create the certified task.",
                error_code=type(exc).__name__,
            )

        planned = [str(step.capability_id) for step in task.plan.steps]
        if planned != [capability_id]:
            return AutonomousStepRecord(
                action_key=action_key,
                capability_id=capability_id,
                state=AutonomousStepState.FAILED,
                reason_code="AUTONOMY_CAPABILITY_MISMATCH",
                explanation="Core resolved a different capability; autonomy stopped.",
                core_task_id=task.task_id,
                core_task_state=str(task.state),
            )

        policy = ",".join(str(item.outcome) for item in task.policy_decisions)
        if expect_approval:
            if str(task.state) != "awaiting_approval":
                return AutonomousStepRecord(
                    action_key=action_key,
                    capability_id=capability_id,
                    state=AutonomousStepState.FAILED,
                    reason_code="AUTONOMY_APPROVAL_BOUNDARY_MISSING",
                    explanation="Protected action did not stop for approval.",
                    core_task_id=task.task_id,
                    core_task_state=str(task.state),
                    policy_outcome=policy,
                )
            return AutonomousStepRecord(
                action_key=action_key,
                capability_id=capability_id,
                state=AutonomousStepState.AWAITING_APPROVAL,
                reason_code="AUTONOMY_EXACT_APPROVAL_PREPARED",
                explanation="Exact protected action prepared; user approval is required.",
                core_task_id=task.task_id,
                core_task_state=str(task.state),
                policy_outcome=policy,
            )

        if str(task.state) != "completed":
            return AutonomousStepRecord(
                action_key=action_key,
                capability_id=capability_id,
                state=AutonomousStepState.FAILED,
                reason_code="AUTONOMY_READ_NOT_VERIFIED",
                explanation="Certified read did not complete with verified evidence.",
                core_task_id=task.task_id,
                core_task_state=str(task.state),
                policy_outcome=policy,
                error_code=next((r.error_code for r in task.results if r.error_code), None),
            )

        try:
            receipt = self._core.get_receipt(task.task_id)
        except Exception as exc:
            return AutonomousStepRecord(
                action_key=action_key,
                capability_id=capability_id,
                state=AutonomousStepState.FAILED,
                reason_code="AUTONOMY_RECEIPT_MISSING",
                explanation="Core receipt was unavailable.",
                core_task_id=task.task_id,
                core_task_state=str(task.state),
                policy_outcome=policy,
                error_code=type(exc).__name__,
            )

        if not receipt.verified:
            return AutonomousStepRecord(
                action_key=action_key,
                capability_id=capability_id,
                state=AutonomousStepState.FAILED,
                reason_code="AUTONOMY_RECEIPT_UNVERIFIED",
                explanation="Core receipt was not verified.",
                core_task_id=task.task_id,
                core_receipt_id=receipt.receipt_id,
                core_task_state=str(task.state),
                policy_outcome=policy,
            )

        return AutonomousStepRecord(
            action_key=action_key,
            capability_id=capability_id,
            state=AutonomousStepState.COMPLETED,
            reason_code="AUTONOMY_READ_VERIFIED",
            explanation="Certified read executed and verified by Nexuss.",
            core_task_id=task.task_id,
            core_receipt_id=receipt.receipt_id,
            core_task_state=str(task.state),
            policy_outcome=policy,
            evidence_count=sum(len(result.evidence) for result in task.results),
            evidence_sha256=_evidence_hash(task, receipt),
        )
