"""Read-only GitHub account and installation intelligence."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from nexuss.connectors.errors import ConnectorError
from nexuss.connectors.github.models import (
    GitHubAccount,
    GitHubRepositoryInventory,
)
from nexuss.connectors.github.operation_models import (
    GitHubInstallationSummary,
    GitHubOrganizationSummary,
)


class AccountIntelligenceApi(Protocol):
    def authenticated_user(self) -> GitHubAccount: ...

    def list_repositories(self, *, max_pages: int = 10): ...

    def list_organizations(self) -> tuple[GitHubOrganizationSummary, ...]: ...

    def list_user_installations(self) -> tuple[GitHubInstallationSummary, ...]: ...


class GitHubAccountIntelligenceReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account: GitHubAccount
    repository_inventory: GitHubRepositoryInventory
    organizations: tuple[GitHubOrganizationSummary, ...]
    installations: tuple[GitHubInstallationSummary, ...]
    available_layers: tuple[str, ...]
    permission_notes: tuple[str, ...]
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    github_write_performed: bool = False
    credentials_exposed: bool = False
    observed_at: datetime


class GitHubAccountIntelligence:
    def inspect(
        self,
        api: AccountIntelligenceApi,
        *,
        now: datetime | None = None,
    ) -> GitHubAccountIntelligenceReport:
        observed_at = now or datetime.now(UTC)
        account = api.authenticated_user()
        repositories = tuple(api.list_repositories())
        inventory = GitHubRepositoryInventory(
            account_login=account.login,
            total=len(repositories),
            private_count=sum(item.private for item in repositories),
            public_count=sum(not item.private for item in repositories),
            archived_count=sum(item.archived for item in repositories),
            disabled_count=sum(item.disabled for item in repositories),
            fork_count=sum(item.fork for item in repositories),
            repositories=repositories,
            observed_at=observed_at,
        )

        notes: list[str] = []
        try:
            organizations = api.list_organizations()
        except ConnectorError as exc:  # permission-dependent, surfaced safely
            organizations = ()
            notes.append(f"Organizations unavailable: {type(exc).__name__}")

        try:
            installations = api.list_user_installations()
        except ConnectorError as exc:  # permission/token-type dependent
            installations = ()
            notes.append(f"Installations unavailable: {type(exc).__name__}")

        evidence_payload = {
            "account_id": account.account_id,
            "account_login": account.login,
            "repositories": [
                {
                    "id": item.repository_id,
                    "full_name": item.full_name,
                    "private": item.private,
                    "archived": item.archived,
                    "disabled": item.disabled,
                    "fork": item.fork,
                    "default_branch": item.default_branch,
                    "permissions": item.permissions,
                    "updated_at": (
                        item.updated_at.isoformat() if item.updated_at else None
                    ),
                }
                for item in repositories
            ],
            "organizations": [item.model_dump(mode="json") for item in organizations],
            "installations": [item.model_dump(mode="json") for item in installations],
            "observed_at": observed_at.isoformat(),
        }
        evidence_sha256 = hashlib.sha256(
            json.dumps(
                evidence_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()

        return GitHubAccountIntelligenceReport(
            account=account,
            repository_inventory=inventory,
            organizations=organizations,
            installations=installations,
            available_layers=(
                "authenticated_account",
                "repository_inventory",
                "selected_repository_read",
                "pull_request_read",
                "issue_read",
                "actions_read",
            ),
            permission_notes=tuple(notes),
            evidence_sha256=evidence_sha256,
            observed_at=observed_at,
        )
