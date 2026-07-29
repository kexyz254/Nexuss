"""Exact two-phase GitHub repository-import preparation."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from nexuss.engineering.archive_intake import (
    ArchiveIntakeReceipt,
)
from nexuss.engineering.errors import EngineeringError

_GITHUB_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_GIT_BRANCH = re.compile(
    r"^(?!/|.*(?:^|/)\.|.*\.\.|.*//|.*@\{|.*\\)"
    r"(?!.*[~^:?*\[\]\s])"
    r"(?!.*\.$).{1,255}$"
)


class ArchivePublicationFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1, max_length=1_000)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    git_mode: str = Field(pattern=r"^100(?:644|755)$")


class ArchiveRepositoryImportProposal(BaseModel):
    """Non-executing, non-atomic two-approval import proposal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: UUID = Field(default_factory=uuid4)
    intake_id: UUID
    account_login: str = Field(min_length=1, max_length=100)
    repository_name: str = Field(min_length=1, max_length=100)
    private: bool = True
    auto_init: bool = False
    branch: str = Field(min_length=1, max_length=255)
    commit_message: str = Field(min_length=1, max_length=500)
    archive_name: str
    archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    files: tuple[ArchivePublicationFile, ...]
    archive_contains_readme: bool
    repository_create_payload_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    archive_publish_payload_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    approval_phases: tuple[str, str] = (
        "github.repository.create",
        "github.repository.publish_archive",
    )
    approval_channel: str = "phone"
    requires_two_approvals: bool = True
    non_atomic: bool = True
    automatic_rollback_available: bool = False
    force_push: bool = False
    workflow_files_changed: bool = False
    github_changed: bool = False
    published: bool = False
    credentials_exposed: bool = False
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )


class ArchiveRepositoryImportPlanner:
    """Prepare a new private repository plus archive publication."""

    @staticmethod
    def prepare_new_private_repository(
        receipt: ArchiveIntakeReceipt,
        *,
        account_login: str,
        repository_name: str,
        branch: str = "main",
        commit_message: str = "feat: import repository archive",
    ) -> ArchiveRepositoryImportProposal:
        if not receipt.publication_allowed:
            raise EngineeringError(
                "ARCHIVE_PUBLICATION_PROHIBITED",
                "The archive failed security validation and cannot be published.",
                safe_details={
                    "finding_count": len(
                        receipt.security_findings
                    )
                },
            )
        if not _GITHUB_NAME.fullmatch(account_login):
            raise EngineeringError(
                "ARCHIVE_GITHUB_ACCOUNT_INVALID",
                "The GitHub account login is invalid.",
            )
        if not _GITHUB_NAME.fullmatch(repository_name):
            raise EngineeringError(
                "ARCHIVE_GITHUB_REPOSITORY_INVALID",
                "The GitHub repository name is invalid.",
            )
        if not _GIT_BRANCH.fullmatch(branch):
            raise EngineeringError(
                "ARCHIVE_GIT_BRANCH_INVALID",
                "The Git branch name is invalid.",
            )

        files = tuple(
            ArchivePublicationFile(
                path=entry.repository_path,
                sha256=entry.sha256,
                size_bytes=entry.size_bytes,
                git_mode=entry.git_mode,
            )
            for entry in receipt.entries
        )
        workflow_files_changed = any(
            item.path.casefold().startswith(
                ".github/workflows/"
            )
            for item in files
        )
        if workflow_files_changed:
            raise EngineeringError(
                "ARCHIVE_WORKFLOW_WRITE_PROHIBITED",
                "Workflow publication is prohibited in this stage.",
            )

        create_payload = {
            "account_login": account_login,
            "repository_name": repository_name,
            "private": True,
            "auto_init": False,
        }
        publish_payload = {
            "account_login": account_login,
            "repository_name": repository_name,
            "branch": branch,
            "commit_message": commit_message,
            "archive_sha256": receipt.archive_sha256,
            "manifest_sha256": receipt.manifest_sha256,
            "files": [
                item.model_dump(mode="json")
                for item in files
            ],
            "force_push": False,
            "workflow_files_changed": False,
        }
        return ArchiveRepositoryImportProposal(
            intake_id=receipt.intake_id,
            account_login=account_login,
            repository_name=repository_name,
            private=True,
            auto_init=False,
            branch=branch,
            commit_message=commit_message,
            archive_name=receipt.archive_name,
            archive_sha256=receipt.archive_sha256,
            manifest_sha256=receipt.manifest_sha256,
            files=files,
            archive_contains_readme=any(
                item.path.casefold()
                in {"readme", "readme.md", "readme.txt"}
                for item in files
            ),
            repository_create_payload_sha256=(
                ArchiveRepositoryImportPlanner._hash_payload(
                    create_payload
                )
            ),
            archive_publish_payload_sha256=(
                ArchiveRepositoryImportPlanner._hash_payload(
                    publish_payload
                )
            ),
            approval_phases=(
                "github.repository.create",
                "github.repository.publish_archive",
            ),
            approval_channel="phone",
            requires_two_approvals=True,
            non_atomic=True,
            automatic_rollback_available=False,
            force_push=False,
            workflow_files_changed=False,
            github_changed=False,
            published=False,
            credentials_exposed=False,
        )

    @staticmethod
    def _hash_payload(payload: object) -> str:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest()
