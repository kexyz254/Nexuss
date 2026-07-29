from __future__ import annotations

import base64
import hashlib
import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from nexuss.connectors.errors import ConnectorError
from nexuss.connectors.github.archive_publisher import (
    ArchivePublishApproval,
    GitHubArchivePublisher,
    git_blob_sha1,
)
from nexuss.connectors.github.models import (
    GitHubAccount,
    GitHubRepository,
    VerifiedRepositoryCreate,
)
from nexuss.engineering.archive_intake import SecureArchiveIntake
from nexuss.engineering.archive_publication import (
    ArchiveRepositoryImportPlanner,
)


class FakeApi:
    def __init__(self, repository: GitHubRepository) -> None:
        self.repository = repository
        self.blobs: dict[str, bytes] = {}
        self.tree_entries: list[dict[str, object]] = []
        self.tree_sha = "a" * 40
        self.commit_sha = "b" * 40
        self.reference_sha: str | None = None
        self.fail_ref_retryable = False

    def authenticated_user(self) -> GitHubAccount:
        return GitHubAccount(
            account_id=1,
            login="kexyz254",
            account_type="User",
            html_url="https://github.com/kexyz254",
        )

    def get_repository(self, owner: str, repository: str):
        return self.repository.model_copy(
            update={
                "default_branch": (
                    "main" if self.reference_sha else None
                )
            }
        )

    def repository_is_empty(self, owner: str, repository: str):
        return self.reference_sha is None

    def create_git_blob(
        self,
        owner: str,
        repository: str,
        content_base64: str,
    ):
        content = base64.b64decode(content_base64)
        sha = git_blob_sha1(content)
        self.blobs[sha] = content
        return sha

    def create_git_tree(
        self,
        owner: str,
        repository: str,
        entries: list[dict[str, object]],
    ):
        self.tree_entries = entries
        return self.tree_sha

    def create_git_commit(
        self,
        owner: str,
        repository: str,
        *,
        message: str,
        tree_sha: str,
        parents: list[str],
    ):
        assert parents == []
        return self.commit_sha

    def get_git_reference(
        self,
        owner: str,
        repository: str,
        reference: str,
    ):
        return self.reference_sha

    def create_git_reference(
        self,
        owner: str,
        repository: str,
        *,
        reference: str,
        commit_sha: str,
    ):
        self.reference_sha = commit_sha
        if self.fail_ref_retryable:
            raise ConnectorError(
                "GITHUB_API_UNAVAILABLE",
                "ambiguous",
                retryable=True,
            )
        return commit_sha

    def get_git_commit(
        self,
        owner: str,
        repository: str,
        commit_sha: str,
    ):
        return {
            "sha": commit_sha,
            "tree": {"sha": self.tree_sha},
            "parents": [],
        }

    def get_git_tree(
        self,
        owner: str,
        repository: str,
        tree_sha: str,
        *,
        recursive: bool,
    ):
        return {
            "sha": tree_sha,
            "truncated": False,
            "tree": [
                {
                    **entry,
                    "size": len(
                        self.blobs[str(entry["sha"])]
                    ),
                }
                for entry in self.tree_entries
            ],
        }


def _fixture(tmp_path: Path):
    archive_path = tmp_path / "project.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("project/a.txt", "alpha")
        archive.writestr("project/b.txt", "beta")
    receipt = SecureArchiveIntake().intake(
        archive_path,
        tmp_path / "quarantine",
    )
    proposal = (
        ArchiveRepositoryImportPlanner
        .prepare_new_private_repository(
            receipt,
            account_login="kexyz254",
            repository_name="fenril-task",
        )
    )
    repository = GitHubRepository(
        repository_id=7,
        node_id="R7",
        name="fenril-task",
        full_name="kexyz254/fenril-task",
        owner_login="kexyz254",
        private=True,
        html_url="https://github.com/kexyz254/fenril-task",
        api_url="https://api.github.com/repos/kexyz254/fenril-task",
    )
    payload = {
        "name": "fenril-task",
        "private": True,
        "auto_init": False,
    }
    verified = VerifiedRepositoryCreate(
        request_id=uuid4(),
        approval_id=uuid4(),
        payload_sha256=hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
        repository=repository,
        private_verified=True,
        empty_repository_verified=True,
        owner_verified=True,
        name_verified=True,
    )
    publisher = GitHubArchivePublisher()
    prepared = publisher.prepare(receipt, proposal, verified)
    now = datetime.now(UTC)
    approval = ArchivePublishApproval(
        approval_id=uuid4(),
        request_id=prepared.request_id,
        account_login=prepared.owner_login,
        repository_name=prepared.repository_name,
        payload_sha256=prepared.payload_sha256,
        approved_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    return publisher, prepared, approval, repository, now


def test_publish_verifies_every_file(tmp_path: Path) -> None:
    publisher, prepared, approval, repository, now = _fixture(
        tmp_path
    )
    api = FakeApi(repository)

    verified = publisher.publish(
        api,
        prepared,
        approval,
        now=now,
    )

    assert verified.file_count == 2
    assert verified.all_files_verified is True
    assert verified.initial_commit_verified is True
    assert verified.default_branch_verified is True
    assert verified.visible_branch_created is True
    assert verified.force_push_used is False
    assert verified.credentials_exposed is False


def test_source_change_after_approval_is_refused(
    tmp_path: Path,
) -> None:
    publisher, prepared, approval, repository, now = _fixture(
        tmp_path
    )
    source = Path(prepared.source_root) / prepared.files[0].path
    source.write_text("changed", encoding="utf-8")

    with pytest.raises(ConnectorError) as captured:
        publisher.publish(
            FakeApi(repository),
            prepared,
            approval,
            now=now,
        )

    assert captured.value.code == "GITHUB_ARCHIVE_SOURCE_CHANGED"


def test_wrong_payload_approval_is_refused(
    tmp_path: Path,
) -> None:
    publisher, prepared, approval, repository, now = _fixture(
        tmp_path
    )
    wrong = approval.model_copy(
        update={"payload_sha256": "0" * 64}
    )

    with pytest.raises(ConnectorError) as captured:
        publisher.publish(
            FakeApi(repository),
            prepared,
            wrong,
            now=now,
        )

    assert captured.value.code == (
        "GITHUB_ARCHIVE_APPROVAL_PAYLOAD_MISMATCH"
    )


def test_ambiguous_reference_write_is_reconciled(
    tmp_path: Path,
) -> None:
    publisher, prepared, approval, repository, now = _fixture(
        tmp_path
    )
    api = FakeApi(repository)
    api.fail_ref_retryable = True

    verified = publisher.publish(
        api,
        prepared,
        approval,
        now=now,
    )

    assert verified.branch_verified is True
    assert verified.reference_sha == api.commit_sha


def test_existing_branch_is_never_overwritten(
    tmp_path: Path,
) -> None:
    publisher, prepared, approval, repository, now = _fixture(
        tmp_path
    )
    api = FakeApi(repository)
    api.reference_sha = "c" * 40

    with pytest.raises(ConnectorError) as captured:
        publisher.publish(
            api,
            prepared,
            approval,
            now=now,
        )

    assert captured.value.code in {
        "GITHUB_ARCHIVE_REPOSITORY_NOT_EMPTY",
        "GITHUB_ARCHIVE_BRANCH_ALREADY_EXISTS",
    }
