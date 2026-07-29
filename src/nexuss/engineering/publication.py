"""Exact, approval-bound GitHub publication preparation."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from nexuss.engineering.errors import EngineeringError
from nexuss.engineering.lifecycle import EngineeringReviewBundle

_GITHUB_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_GIT_BRANCH = re.compile(
    r"^(?!/|.*(?:^|/)\.|.*\.\.|.*//|.*@\{|.*\\)"
    r"(?!.*[~^:?*\[\]\s])"
    r"(?!.*\.$).{1,255}$"
)


class EngineeringPublicationFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1, max_length=1_000)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)


class EngineeringPublicationProposal(BaseModel):
    """A non-executing publication payload for exact phone approval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    review_id: UUID
    account_login: str = Field(min_length=1, max_length=100)
    repository_name: str = Field(min_length=1, max_length=100)
    branch: str = Field(min_length=1, max_length=255)
    commit_message: str = Field(min_length=1, max_length=500)
    provider_id: str
    provider_model: str
    files: tuple[EngineeringPublicationFile, ...]
    validation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    diff_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_required: bool = True
    approval_channel: str = "phone"
    force_push: bool = False
    workflow_files_changed: bool = False
    github_changed: bool = False
    published: bool = False
    credentials_exposed: bool = False
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )


class EngineeringPublicationPlanner:
    """Prepare exact publication intent without performing any write."""

    @staticmethod
    def prepare_github(
        review: EngineeringReviewBundle,
        *,
        account_login: str,
        repository_name: str,
        branch: str,
        commit_message: str,
    ) -> EngineeringPublicationProposal:
        if not review.validation.passed:
            raise EngineeringError(
                "ENGINEERING_PUBLICATION_VALIDATION_REQUIRED",
                "Publication cannot be prepared for unvalidated artifacts.",
            )
        if not review.publication_allowed:
            raise EngineeringError(
                "ENGINEERING_PUBLICATION_PROHIBITED",
                "The review bundle prohibits publication.",
            )
        if not _GITHUB_NAME.fullmatch(account_login):
            raise EngineeringError(
                "ENGINEERING_GITHUB_ACCOUNT_INVALID",
                "The GitHub account login is invalid.",
            )
        if not _GITHUB_NAME.fullmatch(repository_name):
            raise EngineeringError(
                "ENGINEERING_GITHUB_REPOSITORY_INVALID",
                "The GitHub repository name is invalid.",
            )
        if not _GIT_BRANCH.fullmatch(branch):
            raise EngineeringError(
                "ENGINEERING_GIT_BRANCH_INVALID",
                "The Git branch name is invalid.",
            )

        files = tuple(
            EngineeringPublicationFile(
                path=artifact.path,
                sha256=artifact.sha256,
                size_bytes=artifact.size_bytes,
            )
            for artifact in review.artifacts
        )
        workflow_files_changed = any(
            item.path.startswith(".github/workflows/")
            for item in files
        )
        if workflow_files_changed:
            raise EngineeringError(
                "ENGINEERING_WORKFLOW_WRITE_PROHIBITED",
                "Workflow-file publication is prohibited in this stage.",
            )

        payload = {
            "task_id": str(review.task_id),
            "review_id": str(review.review_id),
            "account_login": account_login,
            "repository_name": repository_name,
            "branch": branch,
            "commit_message": commit_message,
            "provider_id": review.provider_id,
            "provider_model": review.provider_model,
            "files": [
                item.model_dump(mode="json")
                for item in files
            ],
            "validation_sha256": (
                review.validation.report_sha256
            ),
            "diff_sha256": review.diff_sha256,
            "force_push": False,
            "workflow_files_changed": False,
        }
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        payload_sha256 = hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest()

        return EngineeringPublicationProposal(
            task_id=review.task_id,
            review_id=review.review_id,
            account_login=account_login,
            repository_name=repository_name,
            branch=branch,
            commit_message=commit_message,
            provider_id=review.provider_id,
            provider_model=review.provider_model,
            files=files,
            validation_sha256=(
                review.validation.report_sha256
            ),
            diff_sha256=review.diff_sha256,
            payload_sha256=payload_sha256,
            approval_required=True,
            approval_channel="phone",
            force_push=False,
            workflow_files_changed=False,
            github_changed=False,
            published=False,
            credentials_exposed=False,
        )
