"""Typed read-only repository metadata inspection."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from nexuss.connectors.github.models import GitHubRepository
from nexuss.connectors.github.operation_models import (
    GitHubBranchSummary,
    GitHubCommitSummary,
    GitHubTagSummary,
    RepositorySelection,
)


class RepositoryReaderApi(Protocol):
    def get_repository(self, owner: str, repository: str) -> GitHubRepository: ...

    def resolve_commit(
        self,
        owner: str,
        repository: str,
        ref: str,
    ) -> GitHubCommitSummary: ...

    def list_branches(
        self,
        owner: str,
        repository: str,
    ) -> tuple[GitHubBranchSummary, ...]: ...

    def list_tags(
        self,
        owner: str,
        repository: str,
    ) -> tuple[GitHubTagSummary, ...]: ...

    def list_commits(
        self,
        owner: str,
        repository: str,
        *,
        ref: str | None = None,
        limit: int = 50,
    ) -> tuple[GitHubCommitSummary, ...]: ...


class RepositoryReadReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_login: str
    repository: GitHubRepository
    selection: RepositorySelection
    resolved_commit: GitHubCommitSummary
    branches: tuple[GitHubBranchSummary, ...]
    tags: tuple[GitHubTagSummary, ...]
    recent_commits: tuple[GitHubCommitSummary, ...]
    read_only: bool = True
    github_write_performed: bool = False
    observed_at: datetime


class GitHubRepositoryReader:
    def inspect(
        self,
        api: RepositoryReaderApi,
        selection: RepositorySelection,
        *,
        account_login: str,
        now: datetime | None = None,
    ) -> RepositoryReadReport:
        owner, repository_name = selection.repository_full_name.split("/", 1)
        repository = api.get_repository(owner, repository_name)
        if repository.full_name.casefold() != selection.repository_full_name.casefold():
            raise ValueError("GitHub returned a different repository than selected")
        if repository.disabled:
            raise ValueError("Disabled repositories cannot enter a managed workspace")
        resolved = api.resolve_commit(
            owner,
            repository_name,
            selection.requested_ref,
        )
        branches = api.list_branches(owner, repository_name)
        tags = api.list_tags(owner, repository_name)
        commits = api.list_commits(
            owner,
            repository_name,
            ref=resolved.sha,
            limit=50,
        )
        return RepositoryReadReport(
            account_login=account_login,
            repository=repository,
            selection=selection,
            resolved_commit=resolved,
            branches=branches,
            tags=tags,
            recent_commits=commits,
            observed_at=now or datetime.now(UTC),
        )
