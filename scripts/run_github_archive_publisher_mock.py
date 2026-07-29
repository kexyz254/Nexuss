from __future__ import annotations

import hashlib
import json
import tempfile
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

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


class MockGitHubArchiveApi:
    def __init__(self, repository: GitHubRepository) -> None:
        self.repository = repository
        self.blobs: dict[str, bytes] = {}
        self.tree_sha: str | None = None
        self.tree_entries: list[dict[str, object]] = []
        self.commit_sha: str | None = None
        self.reference_sha: str | None = None

    def authenticated_user(self) -> GitHubAccount:
        return GitHubAccount(
            account_id=158442432,
            login="kexyz254",
            account_type="User",
            html_url="https://github.com/kexyz254",
        )

    def get_repository(
        self,
        owner: str,
        repository: str,
    ) -> GitHubRepository:
        default = "main" if self.reference_sha else None
        return self.repository.model_copy(
            update={"default_branch": default}
        )

    def repository_is_empty(
        self,
        owner: str,
        repository: str,
    ) -> bool:
        return self.reference_sha is None

    def create_git_blob(
        self,
        owner: str,
        repository: str,
        content_base64: str,
    ) -> str:
        import base64

        content = base64.b64decode(content_base64)
        sha = git_blob_sha1(content)
        self.blobs[sha] = content
        return sha

    def create_git_tree(
        self,
        owner: str,
        repository: str,
        entries: list[dict[str, object]],
    ) -> str:
        self.tree_entries = entries
        self.tree_sha = hashlib.sha1(
            json.dumps(entries, sort_keys=True).encode(),
            usedforsecurity=False,
        ).hexdigest()
        return self.tree_sha

    def create_git_commit(
        self,
        owner: str,
        repository: str,
        *,
        message: str,
        tree_sha: str,
        parents: list[str],
    ) -> str:
        assert parents == []
        self.commit_sha = hashlib.sha1(
            f"{message}:{tree_sha}".encode(),
            usedforsecurity=False,
        ).hexdigest()
        return self.commit_sha

    def get_git_reference(
        self,
        owner: str,
        repository: str,
        reference: str,
    ) -> str | None:
        return self.reference_sha

    def create_git_reference(
        self,
        owner: str,
        repository: str,
        *,
        reference: str,
        commit_sha: str,
    ) -> str:
        assert reference == "refs/heads/main"
        self.reference_sha = commit_sha
        return commit_sha

    def get_git_commit(
        self,
        owner: str,
        repository: str,
        commit_sha: str,
    ) -> dict[str, object]:
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
    ) -> dict[str, object]:
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


def main() -> int:
    root = Path(
        tempfile.mkdtemp(prefix="nexuss-p65e-demo-")
    )
    archive_path = root / "fenril-task.zip"
    with zipfile.ZipFile(
        archive_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        archive.writestr(
            "fenril-task/index.html",
            "<!doctype html><title>Fenril</title><h1>Fenril</h1>",
        )
        archive.writestr(
            "fenril-task/styles.css",
            "body { font-family: system-ui; }",
        )

    receipt = SecureArchiveIntake().intake(
        archive_path,
        root / "quarantine",
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
        repository_id=999,
        node_id="R_demo",
        name="fenril-task",
        full_name="kexyz254/fenril-task",
        owner_login="kexyz254",
        private=True,
        html_url="https://github.com/kexyz254/fenril-task",
        api_url="https://api.github.com/repos/kexyz254/fenril-task",
    )
    create_payload = {
        "name": "fenril-task",
        "private": True,
        "auto_init": False,
    }
    verified_create = VerifiedRepositoryCreate(
        request_id=uuid4(),
        approval_id=uuid4(),
        payload_sha256=hashlib.sha256(
            json.dumps(
                create_payload,
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
    prepared = publisher.prepare(
        receipt,
        proposal,
        verified_create,
    )
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
    verified = publisher.publish(
        MockGitHubArchiveApi(repository),
        prepared,
        approval,
        now=now,
    )

    print()
    print("=" * 72)
    print("NEXUSS P6.5E ARCHIVE PUBLISHER MOCK")
    print("=" * 72)
    print(f"Repository:            {verified.owner_login}/{verified.repository_name}")
    print(f"Branch:                {verified.branch}")
    print(f"Files verified:        {verified.file_count}")
    print(f"Initial commit:        {verified.commit_sha}")
    print(f"Tree:                  {verified.tree_sha}")
    print(f"Branch verified:       {verified.branch_verified}")
    print(f"All files verified:    {verified.all_files_verified}")
    print(f"Initial commit verified: {verified.initial_commit_verified}")
    print(f"Visible branch created:  {verified.visible_branch_created}")
    print(f"Force push used:       {verified.force_push_used}")
    print(f"Workflow files changed: {verified.workflow_files_changed}")
    print("Credentials exposed:   False")
    print("Live GitHub contacted: False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
