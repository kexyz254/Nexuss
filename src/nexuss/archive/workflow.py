"""Native two-phase ZIP-to-GitHub workflow for Nexuss.

The workflow reuses the existing Nexuss paired-phone approval contract. It
accepts an untrusted ZIP only through the P6.5D quarantine, creates a private
empty repository after the first phone approval, and publishes the exact
P6.5E manifest only after a second phone approval.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
from collections.abc import AsyncIterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Protocol
from urllib.parse import unquote
from uuid import NAMESPACE_URL, UUID, uuid5

from nexuss.connectors.contracts import (
    ConnectorHealth,
    ConnectorStatus,
)
from nexuss.connectors.errors import ConnectorError
from nexuss.connectors.github.archive_publisher import (
    ArchivePublishApproval,
    PreparedArchivePublish,
    VerifiedArchivePublish,
)
from nexuss.connectors.github.models import (
    PreparedRepositoryCreate,
    RepositoryCreateApproval,
    VerifiedRepositoryCreate,
)
from nexuss.core.ledger import InMemoryActionLedger
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
    TaskState,
    TaskView,
)
from nexuss.engineering.archive_intake import (
    ArchiveIntakePolicy,
    ArchiveIntakeReceipt,
    SecureArchiveIntake,
)
from nexuss.engineering.archive_publication import (
    ArchiveRepositoryImportPlanner,
    ArchiveRepositoryImportProposal,
)
from nexuss.mobile.models import MobileApprovalSummary

_APPROVAL_LIFETIME = timedelta(minutes=5)
_RETENTION_LIFETIME = timedelta(hours=24)
_MAX_UPLOAD_BYTES = 50_000_000
_MAX_NATIVE_PUBLISH_FILES = 500
_REPOSITORY_NAME = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_TERMINAL_STATES = {
    TaskState.COMPLETED,
    TaskState.PARTIALLY_COMPLETED,
    TaskState.DENIED,
    TaskState.FAILED,
    TaskState.ROLLED_BACK,
}


class ArchiveWorkflowError(RuntimeError):
    """A safe archive-workflow failure suitable for the API surface."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
        safe_details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.safe_details = safe_details or {}


class ArchiveTaskNotFoundError(LookupError):
    """Raised when an archive task does not exist."""


class ArchiveApprovalValidationError(ValueError):
    """Raised when an archive approval is invalid or no longer pending."""


class ArchiveSessionError(ValueError):
    """Raised when a session cannot operate on the archive task."""


class GitHubArchiveWorkflowService(Protocol):
    """Narrow GitHub connector surface required by the native workflow."""

    def health(
        self,
        *,
        now: datetime | None = None,
    ) -> ConnectorHealth: ...

    def prepare_private_repository(
        self,
        requested_name: str,
        *,
        description: str = "",
        now: datetime | None = None,
    ) -> PreparedRepositoryCreate: ...

    def create_private_repository(
        self,
        prepared: PreparedRepositoryCreate,
        approval: RepositoryCreateApproval,
        *,
        now: datetime | None = None,
    ) -> VerifiedRepositoryCreate: ...

    def prepare_archive_publication(
        self,
        receipt: ArchiveIntakeReceipt,
        proposal: ArchiveRepositoryImportProposal,
        verified_repository: VerifiedRepositoryCreate,
        *,
        now: datetime | None = None,
    ) -> PreparedArchivePublish: ...

    def publish_archive_to_empty_repository(
        self,
        prepared: PreparedArchivePublish,
        approval: ArchivePublishApproval,
        *,
        now: datetime | None = None,
    ) -> VerifiedArchivePublish: ...


@dataclass(slots=True)
class _ArchiveTaskContext:
    receipt: ArchiveIntakeReceipt
    proposal: ArchiveRepositoryImportProposal
    prepared_create: PreparedRepositoryCreate
    phase: str = "repository_create"
    verified_create: VerifiedRepositoryCreate | None = None
    prepared_publish: PreparedArchivePublish | None = None



class _RuntimeGitHubService:
    """Resolve the encrypted production connector only when first used."""

    @staticmethod
    def _service():
        from nexuss.connectors.github.runtime import get_github_connector

        return get_github_connector()

    def health(
        self,
        *,
        now: datetime | None = None,
    ) -> ConnectorHealth:
        return self._service().health(now=now)

    def prepare_private_repository(
        self,
        requested_name: str,
        *,
        description: str = "",
        now: datetime | None = None,
    ) -> PreparedRepositoryCreate:
        return self._service().prepare_private_repository(
            requested_name,
            description=description,
            now=now,
        )

    def create_private_repository(
        self,
        prepared: PreparedRepositoryCreate,
        approval: RepositoryCreateApproval,
        *,
        now: datetime | None = None,
    ) -> VerifiedRepositoryCreate:
        return self._service().create_private_repository(
            prepared,
            approval,
            now=now,
        )

    def prepare_archive_publication(
        self,
        receipt: ArchiveIntakeReceipt,
        proposal: ArchiveRepositoryImportProposal,
        verified_repository: VerifiedRepositoryCreate,
        *,
        now: datetime | None = None,
    ) -> PreparedArchivePublish:
        return self._service().prepare_archive_publication(
            receipt,
            proposal,
            verified_repository,
            now=now,
        )

    def publish_archive_to_empty_repository(
        self,
        prepared: PreparedArchivePublish,
        approval: ArchivePublishApproval,
        *,
        now: datetime | None = None,
    ) -> VerifiedArchivePublish:
        return self._service().publish_archive_to_empty_repository(
            prepared,
            approval,
            now=now,
        )


class ArchiveImportCoordinator:
    """Own native archive tasks without creating a second authority path."""

    def __init__(
        self,
        *,
        github: GitHubArchiveWorkflowService,
        root: Path,
        intake: SecureArchiveIntake | None = None,
        max_upload_bytes: int = _MAX_UPLOAD_BYTES,
        max_publish_files: int = _MAX_NATIVE_PUBLISH_FILES,
    ) -> None:
        self._github = github
        self._root = root.expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._intake = intake or SecureArchiveIntake(
            ArchiveIntakePolicy(
                max_archive_bytes=max_upload_bytes,
                max_entries=max_publish_files,
            )
        )
        self._max_upload_bytes = max_upload_bytes
        self._max_publish_files = max_publish_files
        self._tasks: dict[UUID, TaskView] = {}
        self._contexts: dict[UUID, _ArchiveTaskContext] = {}
        self._request_index: dict[UUID, UUID] = {}
        self._target_index: dict[str, UUID] = {}
        self._inflight_requests: set[UUID] = set()
        self._ledger = InMemoryActionLedger()
        self._lock = RLock()
        self._cleanup_stale_storage()

    @classmethod
    def from_environment(cls) -> ArchiveImportCoordinator:
        """Construct a lazy production workflow without contacting GitHub."""

        local_app_data = (
            os.getenv("LOCALAPPDATA")
            or os.getenv("XDG_DATA_HOME")
            or str(Path.home() / ".local" / "share")
        )
        return cls(
            github=_RuntimeGitHubService(),
            root=Path(local_app_data)
            / "Nexuss"
            / "archive-import-workflows",
        )

    def contains_task(self, task_id: UUID) -> bool:
        with self._lock:
            return task_id in self._tasks

    async def create_task_from_stream(
        self,
        chunks: AsyncIterable[bytes],
        *,
        request_id: UUID,
        session: IdentitySession,
        repository_name: str,
        archive_name: str,
        content_type: str,
        content_length: int | None = None,
    ) -> TaskView:
        """Stream an archive to private staging and create phase-one approval."""

        self._validate_authenticated_session(session)
        normalized_repository = self._normalize_repository_name(repository_name)
        normalized_archive = self._normalize_archive_name(archive_name)
        self._validate_content_type(content_type)

        if content_length is not None:
            if content_length <= 0:
                raise ArchiveWorkflowError(
                    "ARCHIVE_UPLOAD_EMPTY",
                    "The ZIP upload is empty.",
                    status_code=422,
                )
            if content_length > self._max_upload_bytes:
                raise ArchiveWorkflowError(
                    "ARCHIVE_COMPRESSED_SIZE_LIMIT",
                    "The ZIP upload exceeds the 50 MB native intake limit.",
                    status_code=413,
                )

        with self._lock:
            existing = self._request_index.get(request_id)
            if existing is not None:
                return self._tasks[existing].model_copy(deep=True)
            if request_id in self._inflight_requests:
                raise ArchiveWorkflowError(
                    "ARCHIVE_REQUEST_IN_PROGRESS",
                    "This archive request is already being processed.",
                    status_code=409,
                )
            self._inflight_requests.add(request_id)

        staging_root = self._root / "staging" / str(request_id)
        upload_path = staging_root / "upload.zip"
        staging_root.mkdir(parents=True, exist_ok=False)
        received = 0

        try:
            with upload_path.open("xb") as destination:
                async for chunk in chunks:
                    if not chunk:
                        continue
                    received += len(chunk)
                    if received > self._max_upload_bytes:
                        raise ArchiveWorkflowError(
                            "ARCHIVE_COMPRESSED_SIZE_LIMIT",
                            "The ZIP upload exceeds the 50 MB native intake limit.",
                            status_code=413,
                        )
                    destination.write(chunk)

            if received == 0:
                raise ArchiveWorkflowError(
                    "ARCHIVE_UPLOAD_EMPTY",
                    "The ZIP upload is empty.",
                    status_code=422,
                )

            return self._create_task_from_path(
                upload_path,
                request_id=request_id,
                session=session,
                repository_name=normalized_repository,
                archive_name=normalized_archive,
            )
        finally:
            with self._lock:
                self._inflight_requests.discard(request_id)
            shutil.rmtree(staging_root, ignore_errors=True)

    def _create_task_from_path(
        self,
        upload_path: Path,
        *,
        request_id: UUID,
        session: IdentitySession,
        repository_name: str,
        archive_name: str,
    ) -> TaskView:
        now = datetime.now(UTC)
        task_id = uuid5(NAMESPACE_URL, f"nexuss:archive-import-task:{request_id}")

        try:
            health = self._github.health(now=now)
        except ConnectorError as exc:
            raise self._workflow_error(exc) from exc

        if (
            health.status is not ConnectorStatus.CONNECTED
            or health.identity is None
            or not health.identity.verified
        ):
            raise ArchiveWorkflowError(
                "GITHUB_NOT_CONNECTED",
                "Connect and verify GitHub before importing a repository archive.",
                status_code=409,
            )

        account_login = health.identity.account_label
        target_key = f"{account_login.casefold()}/{repository_name.casefold()}"

        with self._lock:
            existing_target = self._target_index.get(target_key)
            if existing_target is not None:
                existing_task = self._tasks.get(existing_target)
                if (
                    existing_task is not None
                    and existing_task.state not in _TERMINAL_STATES
                ):
                    raise ArchiveWorkflowError(
                        "ARCHIVE_TARGET_ALREADY_PENDING",
                        "A ZIP import for this GitHub repository is already pending.",
                        status_code=409,
                    )

        quarantine_parent = self._root / "tasks" / str(task_id) / "quarantine"
        quarantine_parent.mkdir(parents=True, exist_ok=True)

        try:
            receipt = self._intake.intake(upload_path, quarantine_parent)
        except Exception as exc:
            shutil.rmtree(quarantine_parent.parent, ignore_errors=True)
            code = str(getattr(exc, "code", "ARCHIVE_INTAKE_FAILED"))
            message = str(
                getattr(
                    exc,
                    "message",
                    "The ZIP archive failed secure intake validation.",
                )
            )
            status_code = 413 if "SIZE" in code or "RATIO" in code else 422
            raise ArchiveWorkflowError(
                code,
                message,
                status_code=status_code,
                safe_details=dict(getattr(exc, "safe_details", {}) or {}),
            ) from exc

        if not receipt.publication_allowed:
            shutil.rmtree(quarantine_parent.parent, ignore_errors=True)
            raise ArchiveWorkflowError(
                "ARCHIVE_PUBLICATION_PROHIBITED",
                "The ZIP archive contains credential-like material and cannot be published.",
                status_code=422,
                safe_details={
                    "finding_count": len(receipt.security_findings),
                    "intake_id": str(receipt.intake_id),
                },
            )
        if receipt.file_count > self._max_publish_files:
            shutil.rmtree(quarantine_parent.parent, ignore_errors=True)
            raise ArchiveWorkflowError(
                "ARCHIVE_FILE_COUNT_LIMIT",
                "Native phone-reviewed publication is limited to 500 files.",
                status_code=413,
                safe_details={"file_count": receipt.file_count},
            )

        try:
            proposal = ArchiveRepositoryImportPlanner.prepare_new_private_repository(
                receipt,
                account_login=account_login,
                repository_name=repository_name,
                branch="main",
                commit_message="feat: import verified repository archive",
            )
            prepared_create = self._github.prepare_private_repository(
                repository_name,
                description="",
                now=now,
            )
        except ConnectorError as exc:
            shutil.rmtree(quarantine_parent.parent, ignore_errors=True)
            raise self._workflow_error(exc) from exc

        if (
            prepared_create.owner_login.casefold() != account_login.casefold()
            or prepared_create.repository_name.casefold()
            != repository_name.casefold()
            or prepared_create.private is not True
            or prepared_create.auto_init is not False
        ):
            shutil.rmtree(quarantine_parent.parent, ignore_errors=True)
            raise ArchiveWorkflowError(
                "ARCHIVE_REPOSITORY_PREPARATION_MISMATCH",
                "The prepared GitHub repository differs from the requested private empty target.",
                status_code=409,
            )

        intent = Intent(
            kind=IntentKind.GITHUB_CREATE_REPOSITORY,
            normalized_text=(
                f"Create private empty repository {account_login}/{repository_name} "
                f"and publish verified ZIP archive {archive_name}."
            ),
            confidence=1.0,
            entities={
                "account_login": account_login,
                "account_id": health.identity.external_account_id,
                "repository_name": repository_name,
                "archive_name": archive_name,
                "archive_sha256": receipt.archive_sha256,
                "manifest_sha256": receipt.manifest_sha256,
                "intake_id": str(receipt.intake_id),
            },
        )
        create_step = PlanStep(
            step_id=uuid5(
                NAMESPACE_URL,
                f"nexuss:{task_id}:1:github.repository.create",
            ),
            order=1,
            capability_id="github.repository.create",
            risk_tier=RiskTier.HIGH,
            expected_evidence=[
                "private_repository_verified",
                "empty_repository_verified",
                "owner_verified",
                "name_verified",
            ],
            parameters={
                "account_login": account_login,
                "account_id": health.identity.external_account_id,
                "repository_name": repository_name,
                "private": True,
                "auto_init": False,
                "connector_payload_sha256": prepared_create.payload_sha256,
            },
            reversible=False,
        )
        publish_step = PlanStep(
            step_id=uuid5(
                NAMESPACE_URL,
                f"nexuss:{task_id}:2:github.repository.publish_archive",
            ),
            order=2,
            capability_id="github.repository.publish_archive",
            risk_tier=RiskTier.HIGH,
            expected_evidence=[
                "initial_commit_verified",
                "branch_verified",
                "tree_verified",
                "all_files_verified",
            ],
            parameters={
                "account_login": account_login,
                "repository_name": repository_name,
                "branch": proposal.branch,
                "archive_sha256": receipt.archive_sha256,
                "manifest_sha256": receipt.manifest_sha256,
                "file_count": receipt.file_count,
                "publication_payload_sha256": "pending_repository_creation",
            },
            reversible=False,
        )
        plan = TaskPlan(
            plan_id=uuid5(
                NAMESPACE_URL,
                f"nexuss:{task_id}:archive-import-plan",
            ),
            task_id=task_id,
            intent=intent,
            steps=[create_step, publish_step],
        )
        policy_decisions = [
            PolicyDecision(
                step_id=step.step_id,
                capability_id=step.capability_id,
                outcome=PolicyOutcome.REQUIRE_APPROVAL,
                reason_code=(
                    "PHONE_APPROVAL_REQUIRED_FOR_EXTERNAL_WRITE"
                ),
                explanation=(
                    "This external GitHub write requires exact-payload approval "
                    "from the paired phone."
                ),
            )
            for step in plan.steps
        ]
        events: list[ActionEvent] = []
        self._append_event(
            task_id,
            events,
            state=TaskState.RECEIVED,
            event_type="archive_upload_received",
            detail=(
                f"Received {receipt.file_count} validated files from "
                f"{archive_name}; no GitHub write occurred."
            ),
            occurred_at=now,
        )
        self._append_event(
            task_id,
            events,
            state=TaskState.PLANNED,
            event_type="archive_import_planned",
            detail=(
                "Prepared a two-phase private repository creation and exact "
                "archive publication plan."
            ),
            occurred_at=now,
        )
        approval = self._repository_create_approval(
            task_id,
            session.session_id,
            create_step,
            prepared_create,
            receipt,
            now,
        )
        self._append_event(
            task_id,
            events,
            state=TaskState.AWAITING_APPROVAL,
            event_type="repository_creation_approval_requested",
            detail=(
                "Phase one is paused pending paired-phone approval of the exact "
                "private empty repository payload."
            ),
            occurred_at=now,
        )
        task = TaskView(
            task_id=task_id,
            request_id=request_id,
            user_session_id=session.session_id,
            state=TaskState.AWAITING_APPROVAL,
            intent=intent,
            plan=plan,
            policy_decisions=policy_decisions,
            results=[],
            events=events,
            approval=approval,
            created_at=now,
            updated_at=now,
        )
        context = _ArchiveTaskContext(
            receipt=receipt,
            proposal=proposal,
            prepared_create=prepared_create,
        )

        with self._lock:
            existing = self._request_index.get(request_id)
            if existing is not None:
                return self._tasks[existing].model_copy(deep=True)
            self._tasks[task_id] = task
            self._contexts[task_id] = context
            self._request_index[request_id] = task_id
            self._target_index[target_key] = task_id
            self._record_receipt(task)
            return task.model_copy(deep=True)

    def approve_task(
        self,
        task_id: UUID,
        decision: ApprovalDecision,
        session: IdentitySession,
        *,
        approval_channel: ApprovalChannel,
    ) -> TaskView:
        """Consume one exact approval and execute only its current phase."""

        now = datetime.now(UTC)
        with self._lock:
            task = self._tasks.get(task_id)
            context = self._contexts.get(task_id)
            if task is None or context is None:
                raise ArchiveTaskNotFoundError(str(task_id))
            self._validate_task_session(session, task.user_session_id)
            if task.state is not TaskState.AWAITING_APPROVAL or task.approval is None:
                raise ArchiveApprovalValidationError(
                    "TASK_IS_NOT_AWAITING_APPROVAL"
                )
            approval = task.approval
            if now >= approval.expires_at:
                self._expire_task_locked(task, context, now)
                raise ArchiveApprovalValidationError(
                    "APPROVAL_EXPIRED"
                )
            self._validate_decision(
                decision,
                approval,
                approval_channel=approval_channel,
                now=now,
            )

            if decision.decision is ApprovalDecisionKind.REJECT:
                return self._reject_phase(task, context, now)

            consumed = approval.model_copy(
                update={
                    "status": ApprovalStatus.CONSUMED,
                    "approval_token": None,
                }
            )
            self._append_event(
                task_id,
                task.events,
                state=TaskState.APPROVED,
                event_type=f"{context.phase}_approval_granted",
                detail=(
                    "The paired phone approved the exact phase payload. "
                    "The approval token is now consumed."
                ),
                occurred_at=now,
            )
            self._append_event(
                task_id,
                task.events,
                state=TaskState.EXECUTING,
                event_type=f"{context.phase}_execution_started",
                detail="Nexuss started the approved bounded GitHub operation.",
                occurred_at=now,
            )
            executing = task.model_copy(
                update={
                    "state": TaskState.EXECUTING,
                    "approval": consumed,
                    "updated_at": now,
                }
            )
            self._tasks[task_id] = executing
            self._record_receipt(executing)

        if context.phase == "repository_create":
            return self._execute_repository_creation(task_id, now)
        if context.phase == "archive_publish":
            return self._execute_archive_publication(task_id, now)
        raise ArchiveApprovalValidationError("ARCHIVE_PHASE_INVALID")

    def list_pending_phone_approvals(
        self,
        session_id: UUID,
    ) -> tuple[MobileApprovalSummary, ...]:
        now = datetime.now(UTC)
        with self._lock:
            for task_id, task in list(self._tasks.items()):
                context = self._contexts.get(task_id)
                if (
                    context is not None
                    and task.state is TaskState.AWAITING_APPROVAL
                    and task.approval is not None
                    and now >= task.approval.expires_at
                ):
                    self._expire_task_locked(task, context, now)
            summaries = [
                MobileApprovalSummary(
                    task_id=task.task_id,
                    approval_id=task.approval.approval_id,
                    approval_token=task.approval.approval_token,
                    payload_sha256=task.approval.payload_sha256,
                    action_title=task.approval.action_title,
                    action_summary=task.approval.action_summary,
                    exact_preview=task.approval.exact_preview,
                    destination_label=task.approval.destination_label,
                    risk_tier=task.approval.risk_tier,
                    reversible=task.approval.reversible,
                    expires_at=task.approval.expires_at,
                )
                for task in self._tasks.values()
                if (
                    task.user_session_id == session_id
                    and task.state is TaskState.AWAITING_APPROVAL
                    and task.approval is not None
                    and task.approval.approval_channel
                    is ApprovalChannel.PHONE
                    and task.approval.status is ApprovalStatus.PENDING
                    and task.approval.approval_token is not None
                )
            ]
            return tuple(
                sorted(summaries, key=lambda item: item.expires_at)
            )

    def get_task(self, task_id: UUID) -> TaskView:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise ArchiveTaskNotFoundError(str(task_id))
            return task.model_copy(deep=True)

    def get_receipt(self, task_id: UUID) -> ActionReceipt:
        with self._lock:
            receipt = self._ledger.get(task_id)
            if receipt is None:
                raise ArchiveTaskNotFoundError(str(task_id))
            return receipt

    def get_receipt_history(
        self,
        task_id: UUID,
    ) -> tuple[ActionReceipt, ...]:
        with self._lock:
            history = self._ledger.history(task_id)
            if not history:
                raise ArchiveTaskNotFoundError(str(task_id))
            return history

    def _execute_repository_creation(
        self,
        task_id: UUID,
        approved_at: datetime,
    ) -> TaskView:
        with self._lock:
            task = self._tasks[task_id]
            context = self._contexts[task_id]
            approval = task.approval
            if approval is None:
                raise ArchiveApprovalValidationError(
                    "APPROVAL_CONTEXT_MISSING"
                )
            connector_approval = RepositoryCreateApproval(
                approval_id=approval.approval_id,
                request_id=context.prepared_create.request_id,
                account_login=context.prepared_create.owner_login,
                payload_sha256=context.prepared_create.payload_sha256,
                approved_at=approved_at,
                expires_at=approval.expires_at,
            )

        try:
            verified = self._github.create_private_repository(
                context.prepared_create,
                connector_approval,
                now=approved_at,
            )
        except ConnectorError as exc:
            return self._fail_phase(
                task_id,
                phase="repository_create",
                exc=exc,
                partially_completed=False,
            )

        observed_at = datetime.now(UTC)
        repository = verified.repository
        create_result = CapabilityResult(
            step_id=task.plan.steps[0].step_id,
            capability_id="github.repository.create",
            status=StepStatus.VERIFIED,
            evidence=[
                EvidenceRecord(
                    source="github:rest",
                    observed_at=observed_at,
                    attributes={
                        "source_mode": "live_github_verified",
                        "repository_id": repository.repository_id,
                        "full_name": repository.full_name,
                        "html_url": str(repository.html_url),
                        "private_verified": verified.private_verified,
                        "empty_repository_verified": (
                            verified.empty_repository_verified
                        ),
                        "owner_verified": verified.owner_verified,
                        "name_verified": verified.name_verified,
                        "initial_commit": None,
                        "archive_intake_id": str(context.receipt.intake_id),
                    },
                )
            ],
        )

        with self._lock:
            context.verified_create = verified
            current = self._tasks[task_id]
            self._append_event(
                task_id,
                current.events,
                state=TaskState.VERIFYING,
                event_type="repository_creation_verified",
                detail=(
                    "Nexuss independently re-read and verified the new private "
                    "empty repository."
                ),
                occurred_at=observed_at,
            )
            verified_task = current.model_copy(
                update={
                    "state": TaskState.VERIFYING,
                    "results": [*current.results, create_result],
                    "updated_at": observed_at,
                }
            )
            self._tasks[task_id] = verified_task
            self._record_receipt(verified_task)

        try:
            prepared_publish = self._github.prepare_archive_publication(
                context.receipt,
                context.proposal,
                verified,
                now=datetime.now(UTC),
            )
        except ConnectorError as exc:
            return self._fail_phase(
                task_id,
                phase="archive_publish",
                exc=exc,
                partially_completed=True,
            )

        publish_step = task.plan.steps[1].model_copy(
            update={
                "parameters": {
                    "account_login": prepared_publish.owner_login,
                    "repository_name": prepared_publish.repository_name,
                    "repository_id": prepared_publish.repository_id,
                    "branch": prepared_publish.branch,
                    "commit_message": prepared_publish.commit_message,
                    "archive_sha256": prepared_publish.archive_sha256,
                    "manifest_sha256": prepared_publish.manifest_sha256,
                    "file_count": len(prepared_publish.files),
                    "publication_payload_sha256": (
                        prepared_publish.payload_sha256
                    ),
                    "files": [
                        {
                            "path": item.path,
                            "sha256": item.sha256,
                            "git_blob_sha1": item.git_blob_sha1,
                            "size_bytes": item.size_bytes,
                            "git_mode": item.git_mode,
                        }
                        for item in prepared_publish.files
                    ],
                }
            }
        )
        updated_plan = task.plan.model_copy(
            update={"steps": [task.plan.steps[0], publish_step]}
        )
        next_approval = self._archive_publish_approval(
            task_id,
            task.user_session_id,
            publish_step,
            prepared_publish,
            observed_at,
        )

        with self._lock:
            context.prepared_publish = prepared_publish
            context.phase = "archive_publish"
            current = self._tasks[task_id]
            self._append_event(
                task_id,
                current.events,
                state=TaskState.AWAITING_APPROVAL,
                event_type="archive_publication_approval_requested",
                detail=(
                    "The private repository is verified empty. Phase two is "
                    "paused pending approval of every archive path and hash."
                ),
                occurred_at=observed_at,
            )
            updated = current.model_copy(
                update={
                    "state": TaskState.AWAITING_APPROVAL,
                    "plan": updated_plan,
                    "approval": next_approval,
                    "updated_at": observed_at,
                }
            )
            self._tasks[task_id] = updated
            self._record_receipt(updated)
            return updated.model_copy(deep=True)

    def _execute_archive_publication(
        self,
        task_id: UUID,
        approved_at: datetime,
    ) -> TaskView:
        with self._lock:
            task = self._tasks[task_id]
            context = self._contexts[task_id]
            approval = task.approval
            prepared = context.prepared_publish
            if approval is None or prepared is None:
                raise ArchiveApprovalValidationError(
                    "ARCHIVE_PUBLICATION_CONTEXT_MISSING"
                )
            connector_approval = ArchivePublishApproval(
                approval_id=approval.approval_id,
                request_id=prepared.request_id,
                account_login=prepared.owner_login,
                repository_name=prepared.repository_name,
                payload_sha256=prepared.payload_sha256,
                approved_at=approved_at,
                expires_at=approval.expires_at,
            )

        try:
            verified = self._github.publish_archive_to_empty_repository(
                prepared,
                connector_approval,
                now=approved_at,
            )
        except ConnectorError as exc:
            return self._fail_phase(
                task_id,
                phase="archive_publish",
                exc=exc,
                partially_completed=True,
            )

        observed_at = datetime.now(UTC)
        publish_result = CapabilityResult(
            step_id=task.plan.steps[1].step_id,
            capability_id="github.repository.publish_archive",
            status=StepStatus.VERIFIED,
            evidence=[
                EvidenceRecord(
                    source="github:git-database",
                    observed_at=observed_at,
                    attributes={
                        "source_mode": "live_github_verified",
                        "repository_id": verified.repository_id,
                        "full_name": (
                            f"{verified.owner_login}/"
                            f"{verified.repository_name}"
                        ),
                        "branch": verified.branch,
                        "commit_sha": verified.commit_sha,
                        "tree_sha": verified.tree_sha,
                        "reference_sha": verified.reference_sha,
                        "file_count": verified.file_count,
                        "total_bytes": verified.total_bytes,
                        "repository_private_verified": (
                            verified.repository_private_verified
                        ),
                        "repository_owner_verified": (
                            verified.repository_owner_verified
                        ),
                        "repository_name_verified": (
                            verified.repository_name_verified
                        ),
                        "repository_was_empty_verified": (
                            verified.repository_was_empty_verified
                        ),
                        "branch_verified": verified.branch_verified,
                        "commit_verified": verified.commit_verified,
                        "tree_verified": verified.tree_verified,
                        "all_files_verified": (
                            verified.all_files_verified
                        ),
                        "initial_commit_verified": (
                            verified.initial_commit_verified
                        ),
                        "default_branch_verified": (
                            verified.default_branch_verified
                        ),
                        "force_push_used": verified.force_push_used,
                        "workflow_files_changed": (
                            verified.workflow_files_changed
                        ),
                        "credentials_exposed": (
                            verified.credentials_exposed
                        ),
                        "archive_sha256": context.receipt.archive_sha256,
                        "manifest_sha256": context.receipt.manifest_sha256,
                    },
                )
            ],
        )

        with self._lock:
            current = self._tasks[task_id]
            self._append_event(
                task_id,
                current.events,
                state=TaskState.VERIFYING,
                event_type="archive_publication_verification_started",
                detail=(
                    "Nexuss re-read the branch, root commit, recursive tree, "
                    "and every approved blob."
                ),
                occurred_at=observed_at,
            )
            self._append_event(
                task_id,
                current.events,
                state=TaskState.COMPLETED,
                event_type="archive_publication_verified",
                detail=(
                    f"Verified {verified.file_count} files in the initial "
                    f"commit on {verified.owner_login}/"
                    f"{verified.repository_name}:{verified.branch}."
                ),
                occurred_at=observed_at,
            )
            completed = current.model_copy(
                update={
                    "state": TaskState.COMPLETED,
                    "results": [*current.results, publish_result],
                    "updated_at": observed_at,
                }
            )
            self._tasks[task_id] = completed
            self._record_receipt(completed)
            return completed.model_copy(deep=True)

    def _expire_task_locked(
        self,
        task: TaskView,
        context: _ArchiveTaskContext,
        now: datetime,
    ) -> TaskView:
        approval = task.approval
        if approval is None:
            raise ArchiveApprovalValidationError(
                "APPROVAL_CONTEXT_MISSING"
            )
        expired = approval.model_copy(
            update={
                "status": ApprovalStatus.EXPIRED,
                "approval_token": None,
            }
        )
        state = (
            TaskState.DENIED
            if context.phase == "repository_create"
            else TaskState.PARTIALLY_COMPLETED
        )
        self._append_event(
            task.task_id,
            task.events,
            state=state,
            event_type=f"{context.phase}_approval_expired",
            detail=(
                "The phase approval expired. "
                + (
                    "No GitHub write occurred."
                    if state is TaskState.DENIED
                    else (
                        "The previously created private repository remains "
                        "empty and no archive commit was created."
                    )
                )
            ),
            occurred_at=now,
        )
        updated = task.model_copy(
            update={
                "state": state,
                "approval": expired,
                "updated_at": now,
            }
        )
        self._tasks[task.task_id] = updated
        self._record_receipt(updated)
        return updated

    def _reject_phase(
        self,
        task: TaskView,
        context: _ArchiveTaskContext,
        now: datetime,
    ) -> TaskView:
        approval = task.approval
        if approval is None:
            raise ArchiveApprovalValidationError(
                "APPROVAL_CONTEXT_MISSING"
            )
        rejected = approval.model_copy(
            update={
                "status": ApprovalStatus.REJECTED,
                "approval_token": None,
            }
        )
        state = (
            TaskState.DENIED
            if context.phase == "repository_create"
            else TaskState.PARTIALLY_COMPLETED
        )
        detail = (
            "The repository creation phase was rejected. No GitHub write occurred."
            if state is TaskState.DENIED
            else (
                "Archive publication was rejected. The previously approved "
                "private repository remains empty; no commit was created."
            )
        )
        self._append_event(
            task.task_id,
            task.events,
            state=state,
            event_type=f"{context.phase}_approval_rejected",
            detail=detail,
            occurred_at=now,
        )
        updated = task.model_copy(
            update={
                "state": state,
                "approval": rejected,
                "updated_at": now,
            }
        )
        self._tasks[task.task_id] = updated
        self._record_receipt(updated)
        return updated.model_copy(deep=True)

    def _fail_phase(
        self,
        task_id: UUID,
        *,
        phase: str,
        exc: ConnectorError,
        partially_completed: bool,
    ) -> TaskView:
        now = datetime.now(UTC)
        with self._lock:
            task = self._tasks[task_id]
            step = (
                task.plan.steps[0]
                if phase == "repository_create"
                else task.plan.steps[1]
            )
            failure = CapabilityResult(
                step_id=step.step_id,
                capability_id=step.capability_id,
                status=StepStatus.FAILED,
                evidence=[
                    EvidenceRecord(
                        source="github:connector",
                        observed_at=now,
                        attributes={
                            "phase": phase,
                            "retryable": exc.retryable,
                            "safe_details": exc.safe_details,
                        },
                    )
                ],
                error_code=exc.code,
            )
            state = (
                TaskState.PARTIALLY_COMPLETED
                if partially_completed
                else TaskState.FAILED
            )
            self._append_event(
                task_id,
                task.events,
                state=state,
                event_type=f"{phase}_failed_closed",
                detail=(
                    f"{exc.code}: {exc.message}. Nexuss did not retry an "
                    "ambiguous external write."
                ),
                occurred_at=now,
            )
            updated = task.model_copy(
                update={
                    "state": state,
                    "results": [*task.results, failure],
                    "updated_at": now,
                }
            )
            self._tasks[task_id] = updated
            self._record_receipt(updated)
            return updated.model_copy(deep=True)

    @staticmethod
    def _repository_create_approval(
        task_id: UUID,
        session_id: UUID,
        step: PlanStep,
        prepared: PreparedRepositoryCreate,
        receipt: ArchiveIntakeReceipt,
        now: datetime,
    ) -> ApprovalRequest:
        exact_payload = {
            "capability_id": step.capability_id,
            "account_login": prepared.owner_login,
            "repository_name": prepared.repository_name,
            "private": True,
            "auto_init": False,
            "description": prepared.description,
            "archive_name": receipt.archive_name,
            "archive_sha256": receipt.archive_sha256,
            "manifest_sha256": receipt.manifest_sha256,
            "file_count_waiting_for_phase_two": receipt.file_count,
            "phase": 1,
            "phase_count": 2,
        }
        return ApprovalRequest(
            approval_id=uuid5(
                NAMESPACE_URL,
                (
                    f"nexuss:archive-approval:{task_id}:create:"
                    f"{prepared.payload_sha256}"
                ),
            ),
            task_id=task_id,
            capability_id=step.capability_id,
            status=ApprovalStatus.PENDING,
            action_title="Create private empty GitHub repository",
            action_summary=(
                "Phase 1 of 2: create one private repository without a "
                "README, license, .gitignore, template, branch, or commit."
            ),
            exact_preview=json.dumps(
                exact_payload,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            ),
            destination_label=(
                f"GitHub · {prepared.owner_login}/"
                f"{prepared.repository_name}"
            ),
            payload_sha256=prepared.payload_sha256,
            approval_token=secrets.token_urlsafe(32),
            session_id=session_id,
            expires_at=now + _APPROVAL_LIFETIME,
            risk_tier=RiskTier.HIGH,
            reversible=False,
            approval_channel=ApprovalChannel.PHONE,
        )

    @staticmethod
    def _archive_publish_approval(
        task_id: UUID,
        session_id: UUID,
        step: PlanStep,
        prepared: PreparedArchivePublish,
        now: datetime,
    ) -> ApprovalRequest:
        exact_payload = {
            "capability_id": step.capability_id,
            "account_login": prepared.owner_login,
            "repository_name": prepared.repository_name,
            "repository_id": prepared.repository_id,
            "branch": prepared.branch,
            "commit_message": prepared.commit_message,
            "archive_sha256": prepared.archive_sha256,
            "manifest_sha256": prepared.manifest_sha256,
            "files": [
                {
                    "path": item.path,
                    "sha256": item.sha256,
                    "git_blob_sha1": item.git_blob_sha1,
                    "size_bytes": item.size_bytes,
                    "git_mode": item.git_mode,
                }
                for item in prepared.files
            ],
            "force_push": False,
            "workflow_files_changed": False,
            "phase": 2,
            "phase_count": 2,
        }
        return ApprovalRequest(
            approval_id=uuid5(
                NAMESPACE_URL,
                (
                    f"nexuss:archive-approval:{task_id}:publish:"
                    f"{prepared.payload_sha256}"
                ),
            ),
            task_id=task_id,
            capability_id=step.capability_id,
            status=ApprovalStatus.PENDING,
            action_title="Publish verified ZIP archive to GitHub",
            action_summary=(
                "Phase 2 of 2: create the root commit from the exact "
                f"{len(prepared.files)}-file manifest shown below."
            ),
            exact_preview=json.dumps(
                exact_payload,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            ),
            destination_label=(
                f"GitHub · {prepared.owner_login}/"
                f"{prepared.repository_name}:{prepared.branch}"
            ),
            payload_sha256=prepared.payload_sha256,
            approval_token=secrets.token_urlsafe(32),
            session_id=session_id,
            expires_at=now + _APPROVAL_LIFETIME,
            risk_tier=RiskTier.HIGH,
            reversible=False,
            approval_channel=ApprovalChannel.PHONE,
        )

    @staticmethod
    def _validate_decision(
        decision: ApprovalDecision,
        approval: ApprovalRequest,
        *,
        approval_channel: ApprovalChannel,
        now: datetime,
    ) -> None:
        if (
            decision.decision is ApprovalDecisionKind.APPROVE
            and approval_channel is not ApprovalChannel.PHONE
        ):
            raise ArchiveApprovalValidationError(
                "PHONE_APPROVAL_REQUIRED"
            )
        if now >= approval.expires_at:
            raise ArchiveApprovalValidationError("APPROVAL_EXPIRED")
        if approval.status is not ApprovalStatus.PENDING:
            raise ArchiveApprovalValidationError(
                "APPROVAL_ALREADY_CONSUMED"
            )
        if decision.approval_id != approval.approval_id:
            raise ArchiveApprovalValidationError(
                "APPROVAL_ID_MISMATCH"
            )
        if not secrets.compare_digest(
            decision.approval_token,
            approval.approval_token or "",
        ):
            raise ArchiveApprovalValidationError(
                "APPROVAL_TOKEN_MISMATCH"
            )
        if not secrets.compare_digest(
            decision.payload_sha256,
            approval.payload_sha256,
        ):
            raise ArchiveApprovalValidationError(
                "APPROVAL_PAYLOAD_HASH_MISMATCH"
            )

    @staticmethod
    def _validate_authenticated_session(
        session: IdentitySession,
    ) -> None:
        if not session.authenticated:
            raise ArchiveSessionError("SESSION_NOT_AUTHENTICATED")

    @staticmethod
    def _validate_task_session(
        session: IdentitySession,
        expected_session_id: UUID,
    ) -> None:
        if (
            not session.authenticated
            or session.session_id != expected_session_id
        ):
            raise ArchiveSessionError(
                "Authenticated session does not match the archive task"
            )

    @staticmethod
    def _normalize_repository_name(value: str) -> str:
        normalized = value.strip()
        if not _REPOSITORY_NAME.fullmatch(normalized):
            raise ArchiveWorkflowError(
                "ARCHIVE_REPOSITORY_NAME_INVALID",
                "Use a GitHub-safe repository name containing only letters, "
                "numbers, dots, underscores, or hyphens.",
                status_code=422,
            )
        return normalized

    @staticmethod
    def _normalize_archive_name(value: str) -> str:
        decoded = unquote(value).strip()
        normalized = Path(decoded.replace("\\", "/")).name
        if (
            not normalized
            or len(normalized) > 255
            or not normalized.casefold().endswith(".zip")
        ):
            raise ArchiveWorkflowError(
                "ARCHIVE_NAME_INVALID",
                "The attached file must have a .zip filename.",
                status_code=422,
            )
        return normalized

    @staticmethod
    def _validate_content_type(value: str) -> None:
        media_type = value.split(";", 1)[0].strip().casefold()
        if media_type not in {
            "application/zip",
            "application/x-zip-compressed",
            "application/octet-stream",
        }:
            raise ArchiveWorkflowError(
                "ARCHIVE_CONTENT_TYPE_INVALID",
                "The upload must use a ZIP-compatible content type.",
                status_code=415,
            )

    @staticmethod
    def _workflow_error(exc: ConnectorError) -> ArchiveWorkflowError:
        status_code = 503 if exc.retryable else 409
        if exc.code in {
            "GITHUB_REAUTH_REQUIRED",
            "GITHUB_NOT_CONNECTED",
        }:
            status_code = 409
        return ArchiveWorkflowError(
            exc.code,
            exc.message,
            status_code=status_code,
            safe_details=exc.safe_details,
        )

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
                    (
                        f"nexuss:archive-event:{task_id}:"
                        f"{sequence}:{event_type}:{state}"
                    ),
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
        version = 1 if previous is None else previous.receipt_version + 1
        verified = (
            task.state is TaskState.COMPLETED
            and len(task.results) >= 2
            and all(
                result.status is StepStatus.VERIFIED
                and bool(result.evidence)
                for result in task.results[-2:]
            )
        )
        self._ledger.append(
            ActionReceipt(
                receipt_id=uuid5(
                    NAMESPACE_URL,
                    f"nexuss:archive-receipt:{task.task_id}",
                ),
                receipt_version=version,
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
                reversible=False,
            )
        )

    def _cleanup_stale_storage(self) -> None:
        cutoff = datetime.now(UTC).timestamp() - _RETENTION_LIFETIME.total_seconds()
        for category in ("staging", "tasks"):
            parent = self._root / category
            if not parent.exists():
                continue
            for child in parent.iterdir():
                try:
                    if child.stat().st_mtime < cutoff:
                        shutil.rmtree(child, ignore_errors=True)
                except OSError:
                    continue
