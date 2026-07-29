from __future__ import annotations

import asyncio
import hashlib
import tempfile
import zipfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from nexuss.archive.workflow import ArchiveImportCoordinator
from nexuss.connectors.contracts import (
    ConnectorHealth,
    ConnectorIdentity,
    ConnectorStatus,
)
from nexuss.connectors.github.archive_publisher import (
    GitHubArchivePublisher,
    GitTreeEntryEvidence,
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
    AssuranceLevel,
    IdentitySession,
)
from nexuss.engineering.archive_intake import ArchiveIntakeReceipt
from nexuss.engineering.archive_publication import (
    ArchiveRepositoryImportProposal,
)


class MockGitHub:
    def __init__(self) -> None:
        self.created = False
        self.published = False

    def health(
        self,
        *,
        now: datetime | None = None,
    ) -> ConnectorHealth:
        observed = now or datetime.now(UTC)
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
                observed_at=observed,
            ),
            detail="mock connected",
            checked_at=observed,
        )

    def prepare_private_repository(
        self,
        requested_name: str,
        *,
        description: str = "",
        now: datetime | None = None,
    ) -> PreparedRepositoryCreate:
        payload = {
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
        self.created = True
        repository = GitHubRepository(
            repository_id=999,
            node_id="R_mock",
            name=prepared.repository_name,
            full_name=f"kexyz254/{prepared.repository_name}",
            owner_login="kexyz254",
            private=True,
            html_url=f"https://github.com/kexyz254/{prepared.repository_name}",
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
    ):
        return GitHubArchivePublisher().prepare(
            receipt,
            proposal,
            verified_repository,
            now=now,
        )

    def publish_archive_to_empty_repository(
        self,
        prepared,
        approval,
        *,
        now: datetime | None = None,
    ) -> VerifiedArchivePublish:
        self.published = True
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
            total_bytes=sum(item.size_bytes for item in prepared.files),
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


def archive_bytes() -> bytes:
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


async def chunks(content: bytes):
    yield content


def decision(task) -> ApprovalDecision:
    approval = task.approval
    assert approval is not None
    assert approval.approval_token is not None
    return ApprovalDecision(
        approval_id=approval.approval_id,
        approval_token=approval.approval_token,
        payload_sha256=approval.payload_sha256,
        decision=ApprovalDecisionKind.APPROVE,
    )


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="nexuss-p65f-mock-"))
    github = MockGitHub()
    coordinator = ArchiveImportCoordinator(
        github=github,
        root=root / "workflow",
    )
    session = IdentitySession(
        session_id=uuid4(),
        authenticated=True,
        assurance_level=AssuranceLevel.BASIC,
    )
    content = archive_bytes()
    first = asyncio.run(
        coordinator.create_task_from_stream(
            chunks(content),
            request_id=uuid4(),
            session=session,
            repository_name="fenril-task",
            archive_name="fenril-task.zip",
            content_type="application/zip",
            content_length=len(content),
        )
    )
    second = coordinator.approve_task(
        first.task_id,
        decision(first),
        session,
        approval_channel=ApprovalChannel.PHONE,
    )
    completed = coordinator.approve_task(
        second.task_id,
        decision(second),
        session,
        approval_channel=ApprovalChannel.PHONE,
    )
    receipt = coordinator.get_receipt(completed.task_id)
    publish = next(
        result
        for result in completed.results
        if result.capability_id
        == "github.repository.publish_archive"
    )
    evidence = publish.evidence[0].attributes

    print()
    print("=" * 72)
    print("NEXUSS P6.5F NATIVE ZIP WORKFLOW MOCK")
    print("=" * 72)
    print("Phase 1 approved:      True")
    print(f"Repository created:    {github.created}")
    print("Repository private:    True")
    print("Repository initialized: False")
    print("Phase 2 approved:      True")
    print(f"Archive published:     {github.published}")
    print(f"Files verified:        {evidence['file_count']}")
    print(f"Branch verified:       {evidence['branch_verified']}")
    print(f"Initial commit verified: {evidence['initial_commit_verified']}")
    print(f"Action Receipt verified: {receipt.verified}")
    print("Force push used:       False")
    print("Workflow files changed: False")
    print("Credentials exposed:   False")
    print("Live GitHub contacted: False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
