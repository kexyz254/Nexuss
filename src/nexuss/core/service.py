"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Nexuss P5 orchestration with knowledge, media, and trusted cross-device actions.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from threading import RLock, Thread
from uuid import NAMESPACE_URL, UUID, uuid5

from nexuss.connectors.contracts import ConnectorStatus
from nexuss.connectors.errors import ConnectorError
from nexuss.connectors.github.runtime import get_github_connector
from nexuss.core.executor import PhonePairingGateway, execute_step
from nexuss.core.intents import classify_intent
from nexuss.core.ledger import InMemoryActionLedger
from nexuss.core.managed_notes import InvalidNoteError, ManagedNoteError, ManagedNoteStore
from nexuss.core.planner import build_plan
from nexuss.core.policy import evaluate_step
from nexuss.core.state_machine import validate_transition
from nexuss.device.client import (
    DeviceCommandError,
    DeviceNodeClient,
    DisabledDeviceNodeClient,
)
from nexuss.domain.models import (
    ActionEvent,
    ActionReceipt,
    ApprovalChannel,
    ApprovalDecision,
    ApprovalDecisionKind,
    ApprovalRequest,
    ApprovalStatus,
    CapabilityResult,
    EvidenceRecord,
    IdentitySession,
    Intent,
    IntentKind,
    PlanStep,
    PolicyDecision,
    PolicyOutcome,
    RiskTier,
    StepStatus,
    TaskPlan,
    TaskRequest,
    TaskState,
    TaskView,
)
from nexuss.local_control.client import (
    HttpLocalControlClient,
    LocalControlError,
)
from nexuss.knowledge.provider import KnowledgeProvider, WikipediaKnowledgeProvider
from nexuss.media.youtube import YouTubeDataProvider, YouTubeProvider
from nexuss.memory.store import MemoryStore
from nexuss.mobile.models import MobileApprovalSummary, MobileHandoffSummary

_HANDOFF_FRESHNESS = timedelta(minutes=2)

_APPROVAL_LIFETIME = timedelta(minutes=5)
# This constant is a JSON schema field name, not a credential value.
_APPROVAL_TOKEN_FIELD = "approval_token"  # nosec B105


class InvalidSessionError(ValueError):
    """Raised when a request is not backed by an authenticated matching session."""


class TaskNotFoundError(LookupError):
    """Raised when a requested task does not exist."""


class ApprovalValidationError(ValueError):
    """Raised when approval is expired, modified, reused, or session-mismatched."""


class RollbackValidationError(ValueError):
    """Raised when receipt-bound rollback cannot be authorized or verified."""


def _payload_sha256(step: PlanStep) -> str:
    payload = {
        "capability_id": step.capability_id,
        "parameters": step.parameters,
        "reversible": step.reversible,
        "risk_tier": step.risk_tier,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class CoreSimulatorService:
    """Prototype orchestration service; state is process-local until the persistence phase."""

    def __init__(
        self,
        *,
        note_store: ManagedNoteStore | None = None,
        device_client: DeviceNodeClient | None = None,
        knowledge_provider: KnowledgeProvider | None = None,
        youtube_provider: YouTubeProvider | None = None,
        pairing_gateway: PhonePairingGateway | None = None,
        memory_store: MemoryStore | None = None,
    ) -> None:
        self._tasks: dict[UUID, TaskView] = {}
        self._request_index: dict[UUID, UUID] = {}
        self._ledger = InMemoryActionLedger()
        self._note_store = note_store or ManagedNoteStore()
        self._device_client = device_client or DisabledDeviceNodeClient()
        self._knowledge_provider = knowledge_provider or WikipediaKnowledgeProvider()
        self._youtube_provider = youtube_provider or YouTubeDataProvider()
        self._pairing_gateway = pairing_gateway
        self._memory_store = memory_store
        self._lock = RLock()

    @staticmethod
    def _validate_session(session: IdentitySession, expected_session_id: UUID) -> None:
        if not session.authenticated or session.session_id != expected_session_id:
            raise InvalidSessionError("Authenticated session does not match the task")

    @staticmethod
    def _append_event(
        task_id: UUID,
        events: list[ActionEvent],
        *,
        state: TaskState,
        event_type: str,
        detail: str,
        occurred_at: datetime,
    ) -> None:
        sequence = len(events) + 1
        events.append(
            ActionEvent(
                event_id=uuid5(
                    NAMESPACE_URL,
                    f"nexuss:event:{task_id}:{sequence}:{event_type}:{state}",
                ),
                sequence=sequence,
                state=state,
                event_type=event_type,
                occurred_at=occurred_at,
                detail=detail,
            )
        )

    def _record_receipt(self, task: TaskView) -> None:
        previous = self._ledger.get(task.task_id)
        receipt_version = 1 if previous is None else previous.receipt_version + 1
        verified = task.state in {TaskState.COMPLETED, TaskState.ROLLED_BACK} and bool(task.results)
        reversible = task.state is TaskState.COMPLETED and any(
            result.capability_id in {"workspace.create_note", "device.launch_notepad"}
            and result.status is StepStatus.VERIFIED
            for result in task.results
        )
        receipt = ActionReceipt(
            receipt_id=uuid5(NAMESPACE_URL, f"nexuss:receipt:{task.task_id}"),
            receipt_version=receipt_version,
            task_id=task.task_id,
            request_id=task.request_id,
            state=task.state,
            intent=task.intent,
            plan_id=task.plan.plan_id,
            policy_decisions=task.policy_decisions,
            results=task.results,
            events=task.events,
            created_at=task.created_at,
            updated_at=task.updated_at,
            verified=verified,
            reversible=reversible,
        )
        self._ledger.append(receipt)

    @staticmethod
    def _invalid_note_plan(task_id: UUID, intent: Intent, error_code: str) -> TaskPlan:
        capability_id = "workspace.create_note"
        step = PlanStep(
            step_id=uuid5(NAMESPACE_URL, f"nexuss:{task_id}:1:{capability_id}"),
            order=1,
            capability_id=capability_id,
            risk_tier=RiskTier.MEDIUM,
            expected_evidence=["validation_error"],
            parameters={"validation_error": error_code},
            reversible=False,
        )
        return TaskPlan(
            plan_id=uuid5(NAMESPACE_URL, f"nexuss:{task_id}:plan:{intent.kind}:invalid"),
            task_id=task_id,
            intent=intent,
            steps=[step],
        )

    @staticmethod
    def _approval_for(
        task_id: UUID,
        session_id: UUID,
        step: PlanStep,
        now: datetime,
    ) -> ApprovalRequest:
        payload_hash = _payload_sha256(step)
        if step.capability_id == "device.launch_notepad":
            target_node_id = str(step.parameters.get("target_node_id", "windows-primary"))
            action_title = "Launch Notepad on trusted Windows node"
            action_summary = (
                "Start only the fixed Windows Notepad executable through the signed "
                f"device node {target_node_id}."
            )
            exact_preview = (
                f"Capability: {step.capability_id}\n"
                f"Target node: {target_node_id}\n"
                "Executable: C:\\Windows\\System32\\notepad.exe\n"
                "Shell: disabled\nArguments: none"
            )
            destination_label = f"Trusted Windows node · {target_node_id}"
            approval_channel = ApprovalChannel.PHONE
        elif step.capability_id == "device.open_web_search":
            launch_url = str(step.parameters.get("launch_url", ""))
            action_title = "Open approved search in Chrome"
            action_summary = (
                "Open one allowlisted HTTPS search URL in Chrome on the "
                "trusted Windows node."
            )
            exact_preview = (
                f"Capability: {step.capability_id}\n"
                f"Target node: {step.parameters.get('target_node_id', 'windows-primary')}\n"
                f"URL: {launch_url}\nShell: disabled\nArguments: fixed --new-tab + approved URL"
            )
            destination_label = "Trusted Windows node · Chrome"
            approval_channel = ApprovalChannel.PHONE
        elif step.capability_id == "github.repository.create":
            account_login = str(
                step.parameters.get("account_login", "")
            )
            account_id = str(step.parameters.get("account_id", ""))
            repository_name = str(
                step.parameters.get("repository_name", "")
            )
            connector_digest = str(
                step.parameters.get(
                    "connector_payload_sha256",
                    "",
                )
            )
            action_title = "Create private GitHub repository"
            action_summary = (
                "Create one empty private repository for the "
                f"verified GitHub account {account_login}."
            )
            exact_preview = (
                f"Capability: {step.capability_id}\n"
                f"Account: {account_login}\n"
                f"Account ID: {account_id}\n"
                f"Repository: {repository_name}\n"
                "Visibility: private\n"
                "README: none\n"
                ".gitignore: none\n"
                "License: none\n"
                "Template: none\n"
                "Initial commit: none\n"
                f"GitHub payload SHA-256: {connector_digest}"
            )
            destination_label = (
                f"GitHub · {account_login}/{repository_name}"
            )
            approval_channel = ApprovalChannel.PHONE
        elif step.capability_id == "phone.open_youtube":
            launch_url = str(step.parameters.get("launch_url", ""))
            action_title = "Open YouTube on paired phone"
            action_summary = (
                "Hand the exact allowlisted YouTube HTTPS URL to the paired "
                "phone after local approval."
            )
            exact_preview = (
                f"Capability: {step.capability_id}\n"
                f"URL: {launch_url}\n"
                "Target: paired approval phone"
            )
            destination_label = "Paired approval phone · YouTube"
            approval_channel = ApprovalChannel.PHONE
        elif step.capability_id == "system.update.apply":
            branch = str(
                step.parameters.get(
                    "branch",
                    "feature/p5-knowledge-media-mobile",
                )
            )
            current_sha = str(
                step.parameters.get("expected_current_sha", "")
            )
            target_sha = str(
                step.parameters.get("expected_target_sha", "")
            )
            action_title = "Apply verified Nexuss update"
            action_summary = (
                "Fast-forward the clean local Nexuss repository to the "
                "exact GitHub revision below, restart the local runtime, "
                "and roll back automatically if health checks fail."
            )
            exact_preview = (
                f"Capability: {step.capability_id}\n"
                f"Branch: {branch}\n"
                f"Current SHA: {current_sha}\n"
                f"Target SHA: {target_sha}\n"
                "Git operation: fetch + merge --ff-only\n"
                "Restart: local connector, trusted node, and Core\n"
                "Failed startup: automatic git rollback to current SHA\n"
                "Arbitrary shell: disabled"
            )
            destination_label = "Nexuss local runtime · verified GitHub revision"
            approval_channel = ApprovalChannel.DESKTOP
        elif step.capability_id in {
            "engineering.build_artifact",
            "engineering.repair_failed_build",
        }:
            is_repair = step.capability_id == "engineering.repair_failed_build"
            action_title = (
                "Repair failed Nexuss engineering build"
                if is_repair
                else "Run Nexuss Developer Engineering mission"
            )
            action_summary = (
                "Resume the retained failed isolated candidate with bounded repair "
                "and deterministic re-verification."
                if is_repair
                else (
                    "Run one bounded isolated Developer Engineering mission; live "
                    "application remains gated by deterministic verification."
                )
            )
            requested = str(
                step.parameters.get(
                    "target" if is_repair else "goal",
                    "No engineering target supplied.",
                )
            )
            exact_preview = (
                f"Capability: {step.capability_id}\n"
                f"Requested scope: {requested}\n"
                "Execution: isolated engineering workspace\n"
                "Provider authority: worker only; no self-approval or publication\n"
                "Live apply: only after deterministic regression/acceptance gates"
            )
            destination_label = "Nexuss · Developer Engineering"
            approval_channel = ApprovalChannel.DESKTOP
        else:
            filename = str(step.parameters.get("filename", "managed action"))
            action_title = "Create managed note"
            action_summary = f"Create {filename} without overwriting an existing file."
            exact_preview = str(
                step.parameters.get("content", "No content preview available.")
            )
            destination_label = "Nexuss Managed Workspace"
            approval_channel = ApprovalChannel.DESKTOP

        return ApprovalRequest(
            approval_id=uuid5(NAMESPACE_URL, f"nexuss:approval:{task_id}:{payload_hash}"),
            task_id=task_id,
            capability_id=step.capability_id,
            status=ApprovalStatus.PENDING,
            action_title=action_title,
            action_summary=action_summary,
            exact_preview=exact_preview,
            destination_label=destination_label,
            payload_sha256=payload_hash,
            approval_token=secrets.token_urlsafe(32),
            session_id=session_id,
            expires_at=now + _APPROVAL_LIFETIME,
            risk_tier=step.risk_tier,
            reversible=step.reversible,
            approval_channel=approval_channel,
        )

    @staticmethod
    def _is_background_engineering_plan(plan: TaskPlan) -> bool:
        return (
            len(plan.steps) == 1
            and plan.steps[0].capability_id in {
                "engineering.build_artifact",
                "engineering.repair_failed_build",
            }
        )

    def _start_background_engineering_task(self, task_id: UUID) -> None:
        worker = Thread(
            target=self._run_background_engineering_task,
            args=(task_id,),
            name=f"nexuss-engineering-{str(task_id)[:8]}",
            daemon=True,
        )
        worker.start()

    def _run_background_engineering_task(self, task_id: UUID) -> None:
        # Resolve the authoritative persisted task under the Core lock, then
        # release it before provider/network/test work.
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.state is not TaskState.EXECUTING:
                return
            if not self._is_background_engineering_plan(task.plan):
                return
            step = task.plan.steps[0]
            session_id = task.user_session_id

        observed_at = datetime.now(UTC)
        try:
            result = execute_step(
                step,
                observed_at=observed_at,
                note_store=self._note_store,
                device_client=self._device_client,
                task_id=task_id,
                knowledge_provider=self._knowledge_provider,
                youtube_provider=self._youtube_provider,
                session_id=session_id,
                pairing_gateway=self._pairing_gateway,
                memory_store=self._memory_store,
                approval=None,
            )
        except Exception as exc:
            result = CapabilityResult(
                step_id=step.step_id,
                capability_id=step.capability_id,
                status=StepStatus.FAILED,
                evidence=[
                    EvidenceRecord(
                        source="local:governed_background_engineering",
                        observed_at=datetime.now(UTC),
                        attributes={
                            "source_mode": "governed_background_engineering",
                            "error_type": type(exc).__name__,
                            "credentials_exposed": False,
                            "live_repository_modified": False,
                        },
                    )
                ],
                error_code="ENGINEERING_BACKGROUND_EXECUTION_FAILED",
            )

        with self._lock:
            current = self._tasks.get(task_id)
            if current is None or current.state is not TaskState.EXECUTING:
                return
            events = list(current.events)
            verify_at = datetime.now(UTC)
            validate_transition(TaskState.EXECUTING, TaskState.VERIFYING)
            self._append_event(
                task_id,
                events,
                state=TaskState.VERIFYING,
                event_type="verification_started",
                detail=(
                    "Nexuss is verifying returned engineering evidence against "
                    "the action contract."
                ),
                occurred_at=verify_at,
            )
            verified = (
                result.status is StepStatus.VERIFIED
                and bool(result.evidence)
            )
            final_state = (
                TaskState.COMPLETED if verified else TaskState.FAILED
            )
            validate_transition(TaskState.VERIFYING, final_state)
            self._append_event(
                task_id,
                events,
                state=final_state,
                event_type=(
                    "verification_completed"
                    if verified
                    else "verification_failed"
                ),
                detail=(
                    "The governed engineering build returned verified evidence."
                    if verified
                    else (
                        "The governed engineering build stopped without verified "
                        "completion evidence."
                    )
                ),
                occurred_at=datetime.now(UTC),
            )
            updated = current.model_copy(
                update={
                    "state": final_state,
                    "results": [result],
                    "events": events,
                    "updated_at": datetime.now(UTC),
                }
            )
            self._tasks[task_id] = updated
            self._record_receipt(updated)

    def _execute_authorized_steps(
        self,
        task_id: UUID,
        plan: TaskPlan,
        events: list[ActionEvent],
        now: datetime,
        session_id: UUID,
        approval: ApprovalRequest | None = None,
    ) -> tuple[TaskState, list[CapabilityResult]]:
        validate_transition(events[-1].state, TaskState.EXECUTING)
        self._append_event(
            task_id,
            events,
            state=TaskState.EXECUTING,
            event_type="execution_started",
            detail="Authorized capabilities entered bounded execution.",
            occurred_at=now,
        )
        results: list[CapabilityResult] = []
        try:
            for step in plan.steps:
                results.append(
                    execute_step(
                        step,
                        observed_at=now,
                        note_store=self._note_store,
                        device_client=self._device_client,
                        task_id=task_id,
                        knowledge_provider=self._knowledge_provider,
                        youtube_provider=self._youtube_provider,
                        session_id=session_id,
                        pairing_gateway=self._pairing_gateway,
                        memory_store=self._memory_store,
                        approval=approval,
                    )
                )
        except ManagedNoteError as exc:
            validate_transition(TaskState.EXECUTING, TaskState.FAILED)
            self._append_event(
                task_id,
                events,
                state=TaskState.FAILED,
                event_type="execution_failed",
                detail=str(exc),
                occurred_at=datetime.now(UTC),
            )
            return TaskState.FAILED, results

        validate_transition(TaskState.EXECUTING, TaskState.VERIFYING)
        self._append_event(
            task_id,
            events,
            state=TaskState.VERIFYING,
            event_type="verification_started",
            detail="Nexuss is verifying returned evidence against the action contract.",
            occurred_at=datetime.now(UTC),
        )
        verified = bool(results) and all(
            result.status is StepStatus.VERIFIED and bool(result.evidence) for result in results
        )
        final_state = TaskState.COMPLETED if verified else TaskState.FAILED
        validate_transition(TaskState.VERIFYING, final_state)
        self._append_event(
            task_id,
            events,
            state=final_state,
            event_type="verification_completed" if verified else "verification_failed",
            detail=(
                "All expected evidence was verified."
                if verified
                else "The execution result did not satisfy the evidence contract."
            ),
            occurred_at=datetime.now(UTC),
        )
        return final_state, results

    def create_task(self, request: TaskRequest, session: IdentitySession) -> TaskView:
        with self._lock:
            existing_task_id = self._request_index.get(request.request_id)
            if existing_task_id is not None:
                return self._tasks[existing_task_id].model_copy(deep=True)

            self._validate_session(session, request.user_session_id)
            task_id = uuid5(NAMESPACE_URL, f"nexuss:task:{request.request_id}")
            now = datetime.now(UTC)
            intent = classify_intent(request.utterance)
            if intent.kind is IntentKind.GITHUB_CREATE_REPOSITORY:
                entities = dict(intent.entities)
                try:
                    github_health = get_github_connector().health(now=now)
                except ConnectorError:
                    github_health = None
                if (
                    github_health is not None
                    and github_health.status is ConnectorStatus.CONNECTED
                    and github_health.identity is not None
                    and github_health.identity.verified
                ):
                    entities["account_login"] = (
                        github_health.identity.account_label
                    )
                    entities["account_id"] = (
                        github_health.identity.external_account_id
                    )
                intent = intent.model_copy(
                    update={"entities": entities}
                )
            if intent.kind is IntentKind.SYSTEM_UPDATE_APPLY:
                entities = dict(intent.entities)
                try:
                    update_status = (
                        HttpLocalControlClient.from_environment()
                        .inspect_update()
                    )
                except (LocalControlError, ValueError):
                    update_status = None

                if update_status is not None:
                    entities.update(
                        {
                            "branch": update_status.branch,
                            "current_sha": update_status.current_sha,
                            "target_sha": update_status.remote_sha,
                            "clean_worktree": str(
                                update_status.clean_worktree
                            ).lower(),
                            "fast_forward_available": str(
                                update_status.fast_forward_available
                            ).lower(),
                        }
                    )

                intent = intent.model_copy(
                    update={"entities": entities}
                )

            events: list[ActionEvent] = []
            self._append_event(
                task_id,
                events,
                state=TaskState.RECEIVED,
                event_type="request_received",
                detail="Authenticated request accepted for interpretation.",
                occurred_at=now,
            )

            invalid_note_error: InvalidNoteError | None = None
            try:
                plan = build_plan(task_id, intent)
            except InvalidNoteError as exc:
                invalid_note_error = exc
                plan = self._invalid_note_plan(task_id, intent, str(exc))

            validate_transition(TaskState.RECEIVED, TaskState.PLANNED)
            self._append_event(
                task_id,
                events,
                state=TaskState.PLANNED,
                event_type="plan_generated",
                detail=f"Generated a {len(plan.steps)}-step deterministic capability plan.",
                occurred_at=now,
            )

            if invalid_note_error is not None:
                decisions = [
                    PolicyDecision(
                        step_id=plan.steps[0].step_id,
                        capability_id=plan.steps[0].capability_id,
                        outcome=PolicyOutcome.DENY,
                        reason_code="INVALID_MANAGED_NOTE_REQUEST",
                        explanation=str(invalid_note_error),
                    )
                ]
            else:
                decisions = [evaluate_step(step) for step in plan.steps]

            approval: ApprovalRequest | None = None
            results: list[CapabilityResult] = []
            background_engineering = False

            if any(decision.outcome is PolicyOutcome.DENY for decision in decisions):
                validate_transition(TaskState.PLANNED, TaskState.DENIED)
                state = TaskState.DENIED
                self._append_event(
                    task_id,
                    events,
                    state=state,
                    event_type="policy_denied",
                    detail="Policy denied at least one required capability.",
                    occurred_at=now,
                )
            elif any(
                decision.outcome is PolicyOutcome.REQUIRE_APPROVAL for decision in decisions
            ):
                validate_transition(TaskState.PLANNED, TaskState.AWAITING_APPROVAL)
                state = TaskState.AWAITING_APPROVAL
                approval = self._approval_for(task_id, session.session_id, plan.steps[0], now)
                self._append_event(
                    task_id,
                    events,
                    state=state,
                    event_type="approval_requested",
                    detail="Execution is paused pending explicit approval of the exact payload.",
                    occurred_at=now,
                )
            else:
                if self._is_background_engineering_plan(plan):
                    # Persist the authoritative task before long provider/test work.
                    validate_transition(TaskState.PLANNED, TaskState.EXECUTING)
                    state = TaskState.EXECUTING
                    background_engineering = True
                    self._append_event(
                        task_id,
                        events,
                        state=TaskState.EXECUTING,
                        event_type="engineering_execution_started",
                        detail=(
                            "The governed Prompt-to-Build task was persisted before "
                            "isolated background engineering began."
                        ),
                        occurred_at=datetime.now(UTC),
                    )
                else:
                    state, results = self._execute_authorized_steps(
                        task_id, plan, events, now, request.user_session_id
                    )

            task = TaskView(
                task_id=task_id,
                request_id=request.request_id,
                user_session_id=request.user_session_id,
                state=state,
                intent=intent,
                plan=plan,
                policy_decisions=decisions,
                results=results,
                events=events,
                approval=approval,
                created_at=now,
                updated_at=datetime.now(UTC),
            )
            self._tasks[task_id] = task
            self._request_index[request.request_id] = task_id
            self._record_receipt(task)
            if background_engineering:
                self._start_background_engineering_task(task_id)
            return task.model_copy(deep=True)

    def approve_task(
        self,
        task_id: UUID,
        decision: ApprovalDecision,
        session: IdentitySession,
        *,
        approval_channel: ApprovalChannel = ApprovalChannel.DESKTOP,
    ) -> TaskView:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise TaskNotFoundError(str(task_id))
            self._validate_session(session, task.user_session_id)
            if task.state is not TaskState.AWAITING_APPROVAL or task.approval is None:
                raise ApprovalValidationError("TASK_IS_NOT_AWAITING_APPROVAL")

            approval = task.approval
            if (
                decision.decision is ApprovalDecisionKind.APPROVE
                and approval.approval_channel is not approval_channel
            ):
                raise ApprovalValidationError(
                    "PHONE_APPROVAL_REQUIRED"
                    if approval.approval_channel is ApprovalChannel.PHONE
                    else "DESKTOP_APPROVAL_REQUIRED"
                )
            now = datetime.now(UTC)
            if now >= approval.expires_at:
                validate_transition(task.state, TaskState.DENIED)
                expired = approval.model_copy(
                    update={
                        "status": ApprovalStatus.EXPIRED,
                        _APPROVAL_TOKEN_FIELD: None,
                    }
                )
                self._append_event(
                    task_id,
                    task.events,
                    state=TaskState.DENIED,
                    event_type="approval_expired",
                    detail="The approval window expired before authorization.",
                    occurred_at=now,
                )
                task = task.model_copy(
                    update={
                        "state": TaskState.DENIED,
                        "approval": expired,
                        "updated_at": now,
                    }
                )
                self._tasks[task_id] = task
                self._record_receipt(task)
                raise ApprovalValidationError("APPROVAL_EXPIRED")

            if decision.approval_id != approval.approval_id:
                raise ApprovalValidationError("APPROVAL_ID_MISMATCH")
            if not secrets.compare_digest(decision.approval_token, approval.approval_token or ""):
                raise ApprovalValidationError("APPROVAL_TOKEN_MISMATCH")
            if not secrets.compare_digest(decision.payload_sha256, approval.payload_sha256):
                raise ApprovalValidationError("APPROVAL_PAYLOAD_HASH_MISMATCH")
            if approval.status is not ApprovalStatus.PENDING:
                raise ApprovalValidationError("APPROVAL_ALREADY_CONSUMED")

            if decision.decision is ApprovalDecisionKind.REJECT:
                validate_transition(task.state, TaskState.DENIED)
                rejected = approval.model_copy(
                    update={
                        "status": ApprovalStatus.REJECTED,
                        _APPROVAL_TOKEN_FIELD: None,
                    }
                )
                self._append_event(
                    task_id,
                    task.events,
                    state=TaskState.DENIED,
                    event_type="approval_rejected",
                    detail="The user rejected the proposed action.",
                    occurred_at=now,
                )
                task = task.model_copy(
                    update={
                        "state": TaskState.DENIED,
                        "approval": rejected,
                        "updated_at": now,
                    }
                )
                self._tasks[task_id] = task
                self._record_receipt(task)
                return task.model_copy(deep=True)

            validate_transition(task.state, TaskState.APPROVED)
            self._append_event(
                task_id,
                task.events,
                state=TaskState.APPROVED,
                event_type="approval_granted",
                detail=(
                    "The exact payload was approved from the paired phone session."
                    if approval_channel is ApprovalChannel.PHONE
                    else "The exact payload was approved by the authenticated desktop session."
                ),
                occurred_at=now,
            )
            consumed = approval.model_copy(
                update={
                    "status": ApprovalStatus.CONSUMED,
                    _APPROVAL_TOKEN_FIELD: None,
                }
            )

            if self._is_background_engineering_plan(task.plan):
                validate_transition(TaskState.APPROVED, TaskState.EXECUTING)
                self._append_event(
                    task_id,
                    task.events,
                    state=TaskState.EXECUTING,
                    event_type="engineering_execution_started",
                    detail=(
                        "The approved Developer Engineering mission entered bounded "
                        "background execution. The exact approval is consumed once; "
                        "normal isolated work inside this mission does not request it again."
                    ),
                    occurred_at=datetime.now(UTC),
                )
                task = task.model_copy(
                    update={
                        "state": TaskState.EXECUTING,
                        "results": [],
                        "approval": consumed,
                        "updated_at": datetime.now(UTC),
                    }
                )
                self._tasks[task_id] = task
                self._record_receipt(task)
                self._start_background_engineering_task(task_id)
                return task.model_copy(deep=True)

            state, results = self._execute_authorized_steps(
                task_id,
                task.plan,
                task.events,
                now,
                task.user_session_id,
                approval,
            )
            task = task.model_copy(
                update={
                    "state": state,
                    "results": results,
                    "approval": consumed,
                    "updated_at": datetime.now(UTC),
                }
            )
            self._tasks[task_id] = task
            self._record_receipt(task)
            return task.model_copy(deep=True)

    def list_pending_phone_approvals(
        self,
        session_id: UUID,
    ) -> tuple[MobileApprovalSummary, ...]:
        with self._lock:
            summaries: list[MobileApprovalSummary] = []
            for task in self._tasks.values():
                approval = task.approval
                if (
                    task.user_session_id != session_id
                    or task.state is not TaskState.AWAITING_APPROVAL
                    or approval is None
                    or approval.approval_channel is not ApprovalChannel.PHONE
                    or approval.status is not ApprovalStatus.PENDING
                    or approval.approval_token is None
                ):
                    continue
                summaries.append(
                    MobileApprovalSummary(
                        task_id=task.task_id,
                        approval_id=approval.approval_id,
                        approval_token=approval.approval_token,
                        payload_sha256=approval.payload_sha256,
                        action_title=approval.action_title,
                        action_summary=approval.action_summary,
                        exact_preview=approval.exact_preview,
                        destination_label=approval.destination_label,
                        risk_tier=approval.risk_tier,
                        reversible=approval.reversible,
                        expires_at=approval.expires_at,
                    )
                )
            return tuple(sorted(summaries, key=lambda item: item.expires_at))

    def list_phone_handoffs(
        self,
        session_id: UUID,
        *,
        now: datetime | None = None,
    ) -> tuple[MobileHandoffSummary, ...]:
        """Return handoffs the phone should still act on.

        Handoffs are bounded by a freshness window. Without it a phone paired
        at any later point claims the entire history at once and opens the
        oldest link in the list, which is never what the person asked for.
        """
        checked_at = now or datetime.now(UTC)
        cutoff = checked_at - _HANDOFF_FRESHNESS
        with self._lock:
            handoffs: list[MobileHandoffSummary] = []
            for task in self._tasks.values():
                if task.user_session_id != session_id or task.state is not TaskState.COMPLETED:
                    continue
                if task.created_at < cutoff:
                    continue
                result = next(
                    (
                        item
                        for item in task.results
                        if item.capability_id == "phone.open_youtube"
                        and item.status is StepStatus.VERIFIED
                        and item.evidence
                    ),
                    None,
                )
                if result is None:
                    continue
                attributes = result.evidence[0].attributes
                launch_url = str(attributes.get("launch_url", ""))
                query = str(attributes.get("query", ""))
                if not launch_url:
                    continue
                handoffs.append(
                    MobileHandoffSummary(
                        task_id=task.task_id,
                        launch_url=launch_url,
                        query=query,
                        created_at=task.created_at,
                    )
                )
            return tuple(sorted(handoffs, key=lambda item: item.created_at))

    def rollback_task(self, task_id: UUID, session: IdentitySession) -> TaskView:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise TaskNotFoundError(str(task_id))
            self._validate_session(session, task.user_session_id)
            if task.state is not TaskState.COMPLETED:
                raise RollbackValidationError("TASK_IS_NOT_ROLLBACK_ELIGIBLE")

            source_result = next(
                (
                    result
                    for result in task.results
                    if result.capability_id in {
                        "workspace.create_note",
                        "device.launch_notepad",
                    }
                    and result.status is StepStatus.VERIFIED
                    and result.evidence
                ),
                None,
            )
            if source_result is None:
                raise RollbackValidationError("NO_RECEIPT_BOUND_REVERSIBLE_RESULT")

            now = datetime.now(UTC)
            validate_transition(task.state, TaskState.ROLLING_BACK)
            self._append_event(
                task_id,
                task.events,
                state=TaskState.ROLLING_BACK,
                event_type="rollback_started",
                detail="Receipt-bound rollback started after explicit user Undo.",
                occurred_at=now,
            )

            try:
                if source_result.capability_id == "workspace.create_note":
                    rollback_result = self._rollback_note(source_result, now)
                    detail = (
                        "The receipt-owned note was removed and absence was verified."
                    )
                else:
                    rollback_result = self._rollback_device_command(task_id, source_result, now)
                    detail = (
                        "The receipt-bound device process was terminated and absence was verified."
                    )
            except (ManagedNoteError, DeviceCommandError, ValueError) as exc:
                validate_transition(TaskState.ROLLING_BACK, TaskState.FAILED)
                self._append_event(
                    task_id,
                    task.events,
                    state=TaskState.FAILED,
                    event_type="rollback_failed",
                    detail=str(exc),
                    occurred_at=datetime.now(UTC),
                )
                failed = task.model_copy(
                    update={"state": TaskState.FAILED, "updated_at": datetime.now(UTC)}
                )
                self._tasks[task_id] = failed
                self._record_receipt(failed)
                raise RollbackValidationError(str(exc)) from exc

            validate_transition(TaskState.ROLLING_BACK, TaskState.ROLLED_BACK)
            self._append_event(
                task_id,
                task.events,
                state=TaskState.ROLLED_BACK,
                event_type="rollback_verified",
                detail=detail,
                occurred_at=datetime.now(UTC),
            )
            rolled_back = task.model_copy(
                update={
                    "state": TaskState.ROLLED_BACK,
                    "results": [*task.results, rollback_result],
                    "updated_at": datetime.now(UTC),
                }
            )
            self._tasks[task_id] = rolled_back
            self._record_receipt(rolled_back)
            return rolled_back.model_copy(deep=True)

    def _rollback_note(
        self,
        note_result: CapabilityResult,
        observed_at: datetime,
    ) -> CapabilityResult:
        attributes = note_result.evidence[0].attributes
        filename = str(attributes.get("filename", ""))
        expected_sha256 = str(attributes.get("sha256", ""))
        removed_path = self._note_store.rollback(
            filename=filename,
            expected_sha256=expected_sha256,
        )
        return CapabilityResult(
            step_id=note_result.step_id,
            capability_id="workspace.rollback_create_note",
            status=StepStatus.ROLLED_BACK,
            evidence=[
                EvidenceRecord(
                    source="local:managed_workspace",
                    observed_at=observed_at,
                    attributes={
                        "source_mode": "live_local_receipt_bound_rollback",
                        "filename": filename,
                        "removed_path": str(removed_path),
                        "expected_sha256": expected_sha256,
                        "verified_absent": True,
                    },
                )
            ],
        )

    def _rollback_device_command(
        self,
        task_id: UUID,
        device_result: CapabilityResult,
        observed_at: datetime,
    ) -> CapabilityResult:
        attributes = device_result.evidence[0].attributes
        command_id = UUID(str(attributes.get("command_id", "")))
        node_id = str(attributes.get("node_id", ""))
        evidence = self._device_client.rollback_command(task_id, command_id, node_id)
        if not evidence.verified_absent:
            raise DeviceCommandError("DEVICE_ROLLBACK_NOT_VERIFIED")
        return CapabilityResult(
            step_id=device_result.step_id,
            capability_id="device.rollback_launch_notepad",
            status=StepStatus.ROLLED_BACK,
            evidence=[
                EvidenceRecord(
                    source="device:windows-node",
                    observed_at=observed_at,
                    attributes={
                        "source_mode": evidence.source_mode,
                        "rollback_id": str(evidence.rollback_id),
                        "command_id": str(evidence.command_id),
                        "node_id": evidence.node_id,
                        "process_id": evidence.process_id,
                        "terminated": evidence.terminated,
                        "verified_absent": evidence.verified_absent,
                    },
                )
            ],
        )

    def list_tasks(self) -> tuple[TaskView, ...]:
        """Return a safe snapshot of authoritative Core tasks.

        The Supervisor consumes this read-only projection; it never becomes a
        second task state machine.
        """

        with self._lock:
            ordered = sorted(
                self._tasks.values(),
                key=lambda item: item.updated_at,
                reverse=True,
            )
            return tuple(
                task.model_copy(deep=True)
                for task in ordered
            )

    def get_task(self, task_id: UUID) -> TaskView:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise TaskNotFoundError(str(task_id))
            return task.model_copy(deep=True)

    def get_receipt(self, task_id: UUID) -> ActionReceipt:
        with self._lock:
            receipt = self._ledger.get(task_id)
            if receipt is None:
                raise TaskNotFoundError(str(task_id))
            return receipt

    def get_receipt_history(self, task_id: UUID) -> tuple[ActionReceipt, ...]:
        with self._lock:
            history = self._ledger.history(task_id)
            if not history:
                raise TaskNotFoundError(str(task_id))
            return history
