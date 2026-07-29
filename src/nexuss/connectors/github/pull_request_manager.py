"""Read-only pull-request and issue inspection for P6.6A."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from nexuss.connectors.github.operation_models import (
    GitHubIssueSummary,
    GitHubPullRequestSummary,
)


class PullRequestReadApi(Protocol):
    def list_pull_requests(
        self,
        owner: str,
        repository: str,
        *,
        state: str = "open",
        limit: int = 50,
    ) -> tuple[GitHubPullRequestSummary, ...]: ...

    def list_issues(
        self,
        owner: str,
        repository: str,
        *,
        state: str = "open",
        limit: int = 50,
    ) -> tuple[GitHubIssueSummary, ...]: ...


class PullRequestInspection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_full_name: str
    state_filter: str
    pull_requests: tuple[GitHubPullRequestSummary, ...]
    github_write_performed: bool = False
    observed_at: datetime


class IssueInspection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_full_name: str
    state_filter: str
    issues: tuple[GitHubIssueSummary, ...]
    github_write_performed: bool = False
    observed_at: datetime


class GitHubPullRequestManager:
    """P6.6A is deliberately inspection-only despite the manager name."""

    def inspect_pull_requests(
        self,
        api: PullRequestReadApi,
        repository_full_name: str,
        *,
        state: str = "open",
        now: datetime | None = None,
    ) -> PullRequestInspection:
        owner, repository = repository_full_name.split("/", 1)
        return PullRequestInspection(
            repository_full_name=repository_full_name,
            state_filter=state,
            pull_requests=api.list_pull_requests(
                owner,
                repository,
                state=state,
                limit=50,
            ),
            observed_at=now or datetime.now(UTC),
        )

    def inspect_issues(
        self,
        api: PullRequestReadApi,
        repository_full_name: str,
        *,
        state: str = "open",
        now: datetime | None = None,
    ) -> IssueInspection:
        owner, repository = repository_full_name.split("/", 1)
        return IssueInspection(
            repository_full_name=repository_full_name,
            state_filter=state,
            issues=api.list_issues(
                owner,
                repository,
                state=state,
                limit=50,
            ),
            observed_at=now or datetime.now(UTC),
        )
