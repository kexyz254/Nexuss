from __future__ import annotations

import asyncio
import hashlib
import zipfile
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest

import nexuss.archive.workflow as workflow_module
from nexuss.archive.workflow import (
    ArchiveApprovalValidationError,
    ArchiveImportCoordinator,
)
from nexuss.connectors.contracts import (
    ConnectorHealth,
    ConnectorIdentity,
    ConnectorStatus,
)
from nexuss.connectors.github.archive_publisher import (
    GitHubArchivePublisher,
    GitTreeEntryEvidence,
    PreparedArchivePublish,
    VerifiedArchivePublish,
)
from nexuss.connectors.github.models import (
    GitHubRepository,
    PreparedRepositoryCreate,
    RepositoryCreateApproval,
    VerifiedRepositoryCreate,
    canonical_payload_bytes,
)
from nexuss.domain.models import (
    ApprovalChannel,
    ApprovalDecision,
    ApprovalDecisionKind,
    ApprovalStatus,
    AssuranceLevel,
    IdentitySession,
    TaskState,
)
from nexuss.engineering.archive_intake import ArchiveIntakeReceipt
from nexuss.engineering.archive_publication import (
    ArchiveRepositoryImportProposal,
)


class FakeGitHubService:
    def __init__(self) -> None:
        self.create_calls = 0
        self.publish_calls = 0

    def health(
        self,
        *,
        now: datetime | None = None,
    ) -> ConnectorHealth:
        checked_at = now or datetime.now(UTC)
        return ConnectorHealth(
            connector_id="github",
            status=ConnectorStatus.CONNECTED,
            configured=True,
            identity=ConnectorIdentity(
                connector_id="github",
                external_account_id="158442432",
                account_label="kexyz254",
                account_type="User",
                verified=True,
                observed_at=checked_at,
            ),
            detail="connected",
            checked_at=checked_at,
        )

    def prepare_private_repository(
        self,
        requested_name: str,
        *,
        description: str = "",
        now: datetime | None = None,
    ) -> PreparedRepositoryCreate:
        payload: dict[str, object] = {
            "name": requested_name,
            "private": True,
            "auto_init": False,
        }
        digest = hashlib.sha256(
            canonical_payload_bytes(payload)
        ).hexdigest()
        return PreparedRepositoryCreate(
            owner_login="kexyz254",
            requested_name=requested_name,
            repository_name=requested_name,
            private=True,
            auto_init=False,
            description=description,
            payload=payload,
            payload_sha256=digest,
            prepared_at=now or datetime.now(UTC),
        )

    def create_private_repository(
        self,
        prepared: PreparedRepositoryCreate,
        approval: RepositoryCreateApproval,
        *,
        now: datetime | None = None,
    ) -> VerifiedRepositoryCreate:
        assert approval.request_id == prepared.request_id
        assert approval.payload_sha256 == prepared.payload_sha256
        self.create_calls += 1
        repository = GitHubRepository(
            repository_id=999,
            node_id="R_999",
            name=prepared.repository_name,
            full_name=f"kexyz254/{prepared.repository_name}",
            owner_login="kexyz254",
            private=True,
            html_url=(
                f"https://github.com/kexyz254/"
                f"{prepared.repository_name}"
            ),
            api_url=(
                f"https://api.github.com/repos/kexyz254/"
                f"{prepared.repository_name}"
            ),
        )
        return VerifiedRepositoryCreate(
            request_id=prepared.request_id,
            approval_id=approval.approval_id,
            payload_sha256=prepared.payload_sha256,
            repository=repository,
            private_verified=True,
            empty_repository_verified=True,
            owner_verified=True,
            name_verified=True,
            verified_at=now or datetime.now(UTC),
        )

    def prepare_archive_publication(
        self,
        receipt: ArchiveIntakeReceipt,
        proposal: ArchiveRepositoryImportProposal,
        verified_repository: VerifiedRepositoryCreate,
        *,
        now: datetime | None = None,
    ) -> PreparedArchivePublish:
        return GitHubArchivePublisher().prepare(
            receipt,
            proposal,
            verified_repository,
            now=now,
        )

    def publish_archive_to_empty_repository(
        self,
        prepared: PreparedArchivePublish,
        approval,
        *,
        now: datetime | None = None,
    ) -> VerifiedArchivePublish:
        assert approval.request_id == prepared.request_id
        assert approval.payload_sha256 == prepared.payload_sha256
        self.publish_calls += 1
        commit_sha = "c" * 40
        tree_sha = "d" * 40
        return VerifiedArchivePublish(
            request_id=prepared.request_id,
            approval_id=approval.approval_id,
            payload_sha256=prepared.payload_sha256,
            repository_id=prepared.repository_id,
            owner_login=prepared.owner_login,
            repository_name=prepared.repository_name,
            branch=prepared.branch,
            commit_sha=commit_sha,
            tree_sha=tree_sha,
            reference_sha=commit_sha,
            file_count=len(prepared.files),
            total_bytes=sum(
                item.size_bytes for item in prepared.files
            ),
            files=tuple(
                GitTreeEntryEvidence(
                    path=item.path,
                    mode=item.git_mode,
                    object_type="blob",
                    sha=item.git_blob_sha1,
                    size=item.size_bytes,
                )
                for item in prepared.files
            ),
            repository_private_verified=True,
            repository_owner_verified=True,
            repository_name_verified=True,
            repository_was_empty_verified=True,
            branch_verified=True,
            commit_verified=True,
            tree_verified=True,
            all_files_verified=True,
            initial_commit_verified=True,
            default_branch_verified=True,
            visible_branch_created=True,
            force_push_used=False,
            workflow_files_changed=False,
            credentials_exposed=False,
            verified_at=now or datetime.now(UTC),
        )


def _zip_bytes() -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(
        output,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        archive.writestr(
            "fenril-task/README.md",
            "# Fenril Task\n",
        )
        archive.writestr(
            "fenril-task/src/main.cpp",
            "int main() { return 0; }\n",
        )
    return output.getvalue()


async def _chunks(content: bytes):
    midpoint = len(content) // 2
    yield content[:midpoint]
    yield content[midpoint:]


def _session() -> IdentitySession:
    return IdentitySession(
        session_id=uuid4(),
        authenticated=True,
        assurance_level=AssuranceLevel.BASIC,
    )


def _decision(task, kind: ApprovalDecisionKind) -> ApprovalDecision:
    approval = task.approval
    assert approval is not None
    assert approval.approval_token is not None
    return ApprovalDecision(
        approval_id=approval.approval_id,
        approval_token=approval.approval_token,
        payload_sha256=approval.payload_sha256,
        decision=kind,
    )


def _create_task(
    tmp_path: Path,
    service: FakeGitHubService,
    session: IdentitySession,
):
    content = _zip_bytes()
    coordinator = ArchiveImportCoordinator(
        github=service,
        root=tmp_path / "archive-workflows",
    )
    task = asyncio.run(
        coordinator.create_task_from_stream(
            _chunks(content),
            request_id=uuid4(),
            session=session,
            repository_name="fenril-task",
            archive_name="fenril-task.zip",
            content_type="application/zip",
            content_length=len(content),
        )
    )
    return coordinator, task


def test_one_phone_approval_publishes_and_verifies(
    tmp_path: Path,
) -> None:
    service = FakeGitHubService()
    session = _session()
    coordinator, task = _create_task(
        tmp_path,
        service,
        session,
    )

    assert task.state is TaskState.AWAITING_APPROVAL
    assert task.approval is not None
    assert task.approval.capability_id == (
        "github.repository.import_archive"
    )
    assert task.approval.approval_channel is ApprovalChannel.PHONE
    assert service.create_calls == 0
    assert service.publish_calls == 0

    completed = coordinator.approve_task(
        task.task_id,
        _decision(task, ApprovalDecisionKind.APPROVE),
        session,
        approval_channel=ApprovalChannel.PHONE,
    )

    assert completed.state is TaskState.COMPLETED
    assert service.create_calls == 1
    assert service.publish_calls == 1
    assert len(completed.results) == 2
    receipt = coordinator.get_receipt(completed.task_id)
    assert receipt.verified is True
    assert receipt.reversible is False
    assert receipt.state is TaskState.COMPLETED
    assert len(coordinator.get_receipt_history(completed.task_id)) >= 5

def test_desktop_cannot_approve_external_write(
    tmp_path: Path,
) -> None:
    service = FakeGitHubService()
    session = _session()
    coordinator, task = _create_task(
        tmp_path,
        service,
        session,
    )

    with pytest.raises(
        ArchiveApprovalValidationError,
        match="PHONE_APPROVAL_REQUIRED",
    ):
        coordinator.approve_task(
            task.task_id,
            _decision(task, ApprovalDecisionKind.APPROVE),
            session,
            approval_channel=ApprovalChannel.DESKTOP,
        )

    assert service.create_calls == 0


def test_rejecting_combined_approval_performs_no_github_write(
    tmp_path: Path,
) -> None:
    service = FakeGitHubService()
    session = _session()
    coordinator, task = _create_task(
        tmp_path,
        service,
        session,
    )

    rejected = coordinator.approve_task(
        task.task_id,
        _decision(task, ApprovalDecisionKind.REJECT),
        session,
        approval_channel=ApprovalChannel.PHONE,
    )

    assert rejected.state is TaskState.DENIED
    assert rejected.approval is not None
    assert rejected.approval.status is ApprovalStatus.REJECTED
    assert service.create_calls == 0
    assert service.publish_calls == 0
    assert coordinator.get_receipt(rejected.task_id).verified is False

def test_request_id_is_idempotent(tmp_path: Path) -> None:
    service = FakeGitHubService()
    session = _session()
    coordinator = ArchiveImportCoordinator(
        github=service,
        root=tmp_path / "archive-workflows",
    )
    content = _zip_bytes()
    request_id = uuid4()

    first = asyncio.run(
        coordinator.create_task_from_stream(
            _chunks(content),
            request_id=request_id,
            session=session,
            repository_name="fenril-task",
            archive_name="fenril-task.zip",
            content_type="application/zip",
            content_length=len(content),
        )
    )
    second = asyncio.run(
        coordinator.create_task_from_stream(
            _chunks(content),
            request_id=request_id,
            session=session,
            repository_name="fenril-task",
            archive_name="fenril-task.zip",
            content_type="application/zip",
            content_length=len(content),
        )
    )

    assert second.task_id == first.task_id
    assert second.approval == first.approval


def test_expired_combined_approval_performs_no_github_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ControlledDateTime(datetime):
        current = datetime(2026, 7, 29, 9, 0, tzinfo=UTC)

        @classmethod
        def now(cls, tz=None):
            del tz
            return cls.current

    monkeypatch.setattr(
        workflow_module,
        "datetime",
        ControlledDateTime,
    )
    service = FakeGitHubService()
    session = _session()
    coordinator, task = _create_task(
        tmp_path,
        service,
        session,
    )
    ControlledDateTime.current += timedelta(minutes=31)

    pending = coordinator.list_pending_phone_approvals(
        session.session_id
    )

    assert pending == ()
    expired = coordinator.get_task(task.task_id)
    assert expired.state is TaskState.DENIED
    assert expired.approval is not None
    assert expired.approval.status is ApprovalStatus.EXPIRED
    assert service.create_calls == 0
    assert service.publish_calls == 0


# NEXUSS_PROFESSIONAL_ARCHIVE_RECOVERY_TESTS_V2
from nexuss.connectors.errors import ConnectorError as _RecoveryConnectorError


class _FlakyRecoveryPublishService(FakeGitHubService):
    def __init__(self) -> None:
        super().__init__()
        self.fail_publication = True

    def publish_archive_to_empty_repository(
        self,
        prepared,
        approval,
        *,
        now=None,
    ):
        if self.fail_publication:
            self.fail_publication = False
            raise _RecoveryConnectorError(
                "GITHUB_TRANSIENT_TEST_FAILURE",
                "simulated publication interruption",
            )
        return super().publish_archive_to_empty_repository(
            prepared,
            approval,
            now=now,
        )


class _UnexpectedRecoveryCreateService(FakeGitHubService):
    def create_private_repository(self, prepared, approval, *, now=None):
        raise RuntimeError("unexpected create crash")


def test_resume_consumed_partial_transaction(tmp_path: Path) -> None:
    service = _FlakyRecoveryPublishService()
    session = _session()
    coordinator, task = _create_task(tmp_path, service, session)

    partial = coordinator.approve_task(
        task.task_id,
        _decision(task, ApprovalDecisionKind.APPROVE),
        session,
        approval_channel=ApprovalChannel.PHONE,
    )
    assert partial.state is TaskState.PARTIALLY_COMPLETED

    recovered = coordinator.resume_interrupted_task(task.task_id)
    assert recovered.state is TaskState.COMPLETED
    assert any(
        event.event_type == "archive_transaction_recovery_started"
        for event in recovered.events
    )


def test_unexpected_create_exception_becomes_failed_receipt(
    tmp_path: Path,
) -> None:
    service = _UnexpectedRecoveryCreateService()
    session = _session()
    coordinator, task = _create_task(tmp_path, service, session)

    failed = coordinator.approve_task(
        task.task_id,
        _decision(task, ApprovalDecisionKind.APPROVE),
        session,
        approval_channel=ApprovalChannel.PHONE,
    )

    assert failed.state is TaskState.FAILED
    assert failed.results[-1].error_code == (
        "ARCHIVE_UNEXPECTED_EXECUTION_ERROR"
    )
