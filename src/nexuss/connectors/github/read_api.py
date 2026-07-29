"""Read-only GitHub REST adapter layered on the existing authenticated client."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

import httpx

from nexuss.connectors.errors import ConnectorError
from nexuss.connectors.github.client import GitHubApiClient
from nexuss.connectors.github.operation_models import (
    GitHubBranchSummary,
    GitHubCommitSummary,
    GitHubInstallationSummary,
    GitHubIssueSummary,
    GitHubOrganizationSummary,
    GitHubPullRequestSummary,
    GitHubTagSummary,
    GitHubWorkflowJobSummary,
    GitHubWorkflowRunSummary,
    GitHubWorkflowSummary,
)


class GitHubReadOnlyApi:
    def __init__(self, client: GitHubApiClient) -> None:
        self._client = client

    def authenticated_user(self):
        return self._client.authenticated_user()

    def list_repositories(self, *, max_pages: int = 10):
        return self._client.list_repositories(max_pages=max_pages)

    def get_repository(self, owner: str, repository: str):
        return self._client.get_repository(owner, repository)

    def list_organizations(self) -> tuple[GitHubOrganizationSummary, ...]:
        payload = self._paginate("/user/orgs")
        return tuple(
            GitHubOrganizationSummary(
                organization_id=int(item["id"]),
                login=str(item["login"]),
                html_url=str(item.get("html_url", "")),
                description=(
                    str(item["description"])
                    if item.get("description") is not None
                    else None
                ),
            )
            for item in payload
        )

    def list_user_installations(self) -> tuple[GitHubInstallationSummary, ...]:
        payload = self._client._request_json(
            "GET",
            "/user/installations",
            expected={200},
            params={"per_page": 100, "page": 1},
        )
        if not isinstance(payload, dict):
            raise ConnectorError(
                "GITHUB_RESPONSE_INVALID",
                "GitHub returned invalid installation data.",
            )
        installations = payload.get("installations")
        if not isinstance(installations, list):
            raise ConnectorError(
                "GITHUB_RESPONSE_INVALID",
                "GitHub installation list is missing.",
            )
        result: list[GitHubInstallationSummary] = []
        for item in installations:
            if not isinstance(item, dict):
                continue
            account = item.get("account")
            permissions = item.get("permissions")
            if not isinstance(account, dict):
                continue
            result.append(
                GitHubInstallationSummary(
                    installation_id=int(item["id"]),
                    account_login=str(account.get("login", "")),
                    account_type=str(account.get("type", "Unknown")),
                    repository_selection=str(item.get("repository_selection", "selected")),
                    permissions=(
                        {str(key): str(value) for key, value in permissions.items()}
                        if isinstance(permissions, dict)
                        else {}
                    ),
                    suspended=item.get("suspended_at") is not None,
                )
            )
        return tuple(result)

    def resolve_commit(
        self,
        owner: str,
        repository: str,
        ref: str,
    ) -> GitHubCommitSummary:
        payload = self._client._request_json(
            "GET",
            self._repo_path(owner, repository, f"commits/{quote(ref, safe='')}"),
            expected={200},
        )
        return self._commit(payload)

    def list_branches(
        self,
        owner: str,
        repository: str,
    ) -> tuple[GitHubBranchSummary, ...]:
        payload = self._paginate(self._repo_path(owner, repository, "branches"))
        result: list[GitHubBranchSummary] = []
        for item in payload:
            commit = item.get("commit")
            if not isinstance(commit, dict):
                continue
            result.append(
                GitHubBranchSummary(
                    name=str(item.get("name", "")),
                    commit_sha=str(commit.get("sha", "")),
                    protected=bool(item.get("protected", False)),
                )
            )
        return tuple(result)

    def list_tags(
        self,
        owner: str,
        repository: str,
    ) -> tuple[GitHubTagSummary, ...]:
        payload = self._paginate(self._repo_path(owner, repository, "tags"))
        result: list[GitHubTagSummary] = []
        for item in payload:
            commit = item.get("commit")
            if not isinstance(commit, dict):
                continue
            result.append(
                GitHubTagSummary(
                    name=str(item.get("name", "")),
                    commit_sha=str(commit.get("sha", "")),
                )
            )
        return tuple(result)

    def list_commits(
        self,
        owner: str,
        repository: str,
        *,
        ref: str | None = None,
        limit: int = 50,
    ) -> tuple[GitHubCommitSummary, ...]:
        params: dict[str, object] = {"per_page": min(max(limit, 1), 100), "page": 1}
        if ref:
            params["sha"] = ref
        payload = self._client._request_json(
            "GET",
            self._repo_path(owner, repository, "commits"),
            expected={200},
            params=params,
        )
        if not isinstance(payload, list):
            raise ConnectorError(
                "GITHUB_RESPONSE_INVALID",
                "GitHub returned an invalid commit list.",
            )
        return tuple(self._commit(item) for item in payload if isinstance(item, dict))

    def list_pull_requests(
        self,
        owner: str,
        repository: str,
        *,
        state: str = "open",
        limit: int = 50,
    ) -> tuple[GitHubPullRequestSummary, ...]:
        payload = self._client._request_json(
            "GET",
            self._repo_path(owner, repository, "pulls"),
            expected={200},
            params={
                "state": state,
                "sort": "updated",
                "direction": "desc",
                "per_page": min(max(limit, 1), 100),
                "page": 1,
            },
        )
        if not isinstance(payload, list):
            raise ConnectorError(
                "GITHUB_RESPONSE_INVALID",
                "GitHub returned an invalid pull-request list.",
            )
        result: list[GitHubPullRequestSummary] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            head = item.get("head")
            base = item.get("base")
            user = item.get("user")
            requested = item.get("requested_reviewers")
            if not isinstance(head, dict) or not isinstance(base, dict):
                continue
            result.append(
                GitHubPullRequestSummary(
                    number=int(item["number"]),
                    title=str(item.get("title", "")),
                    state=str(item.get("state", "")),
                    draft=bool(item.get("draft", False)),
                    author_login=(
                        str(user.get("login")) if isinstance(user, dict) else None
                    ),
                    head_ref=str(head.get("ref", "")),
                    head_sha=str(head.get("sha", "")),
                    base_ref=str(base.get("ref", "")),
                    mergeable_state=(
                        str(item["mergeable_state"])
                        if item.get("mergeable_state") is not None
                        else None
                    ),
                    requested_reviewers=tuple(
                        str(reviewer.get("login", ""))
                        for reviewer in requested or []
                        if isinstance(reviewer, dict)
                    ),
                    review_comments=int(item.get("review_comments", 0)),
                    updated_at=self._datetime(item.get("updated_at")),
                    html_url=str(item.get("html_url", "")),
                )
            )
        return tuple(result)

    def list_issues(
        self,
        owner: str,
        repository: str,
        *,
        state: str = "open",
        limit: int = 50,
    ) -> tuple[GitHubIssueSummary, ...]:
        payload = self._client._request_json(
            "GET",
            self._repo_path(owner, repository, "issues"),
            expected={200},
            params={
                "state": state,
                "sort": "updated",
                "direction": "desc",
                "per_page": min(max(limit, 1), 100),
                "page": 1,
            },
        )
        if not isinstance(payload, list):
            raise ConnectorError(
                "GITHUB_RESPONSE_INVALID",
                "GitHub returned an invalid issue list.",
            )
        result: list[GitHubIssueSummary] = []
        for item in payload:
            if not isinstance(item, dict) or "pull_request" in item:
                continue
            labels = item.get("labels") or []
            assignees = item.get("assignees") or []
            milestone = item.get("milestone")
            user = item.get("user")
            result.append(
                GitHubIssueSummary(
                    number=int(item["number"]),
                    title=str(item.get("title", "")),
                    state=str(item.get("state", "")),
                    author_login=(
                        str(user.get("login")) if isinstance(user, dict) else None
                    ),
                    labels=tuple(
                        str(label.get("name", ""))
                        for label in labels
                        if isinstance(label, dict)
                    ),
                    assignees=tuple(
                        str(assignee.get("login", ""))
                        for assignee in assignees
                        if isinstance(assignee, dict)
                    ),
                    milestone=(
                        str(milestone.get("title"))
                        if isinstance(milestone, dict)
                        else None
                    ),
                    comments=int(item.get("comments", 0)),
                    updated_at=self._datetime(item.get("updated_at")),
                    html_url=str(item.get("html_url", "")),
                )
            )
        return tuple(result)

    def list_workflows(
        self,
        owner: str,
        repository: str,
    ) -> tuple[GitHubWorkflowSummary, ...]:
        payload = self._client._request_json(
            "GET",
            self._repo_path(owner, repository, "actions/workflows"),
            expected={200},
            params={"per_page": 100, "page": 1},
        )
        workflows = payload.get("workflows") if isinstance(payload, dict) else None
        if not isinstance(workflows, list):
            raise ConnectorError(
                "GITHUB_RESPONSE_INVALID",
                "GitHub returned invalid workflow data.",
            )
        return tuple(
            GitHubWorkflowSummary(
                workflow_id=int(item["id"]),
                name=str(item.get("name", "")),
                path=str(item.get("path", "")),
                state=str(item.get("state", "")),
                html_url=str(item.get("html_url", "")),
            )
            for item in workflows
            if isinstance(item, dict)
        )

    def list_workflow_runs(
        self,
        owner: str,
        repository: str,
        *,
        limit: int = 50,
    ) -> tuple[GitHubWorkflowRunSummary, ...]:
        payload = self._client._request_json(
            "GET",
            self._repo_path(owner, repository, "actions/runs"),
            expected={200},
            params={"per_page": min(max(limit, 1), 100), "page": 1},
        )
        runs = payload.get("workflow_runs") if isinstance(payload, dict) else None
        if not isinstance(runs, list):
            raise ConnectorError(
                "GITHUB_RESPONSE_INVALID",
                "GitHub returned invalid workflow-run data.",
            )
        result: list[GitHubWorkflowRunSummary] = []
        for item in runs:
            if not isinstance(item, dict):
                continue
            actor = item.get("actor")
            result.append(
                GitHubWorkflowRunSummary(
                    run_id=int(item["id"]),
                    workflow_id=(
                        int(item["workflow_id"])
                        if item.get("workflow_id") is not None
                        else None
                    ),
                    name=str(item.get("name", "")),
                    event=str(item.get("event", "")),
                    status=str(item.get("status", "")),
                    conclusion=(
                        str(item["conclusion"])
                        if item.get("conclusion") is not None
                        else None
                    ),
                    branch=(
                        str(item["head_branch"])
                        if item.get("head_branch") is not None
                        else None
                    ),
                    head_sha=str(item.get("head_sha", "")),
                    attempt=int(item.get("run_attempt", 1)),
                    actor_login=(
                        str(actor.get("login")) if isinstance(actor, dict) else None
                    ),
                    created_at=self._datetime(item.get("created_at")),
                    updated_at=self._datetime(item.get("updated_at")),
                    html_url=str(item.get("html_url", "")),
                )
            )
        return tuple(result)

    def list_workflow_jobs(
        self,
        owner: str,
        repository: str,
        run_id: int,
    ) -> tuple[GitHubWorkflowJobSummary, ...]:
        payload = self._client._request_json(
            "GET",
            self._repo_path(owner, repository, f"actions/runs/{run_id}/jobs"),
            expected={200},
            params={"filter": "latest", "per_page": 100, "page": 1},
        )
        jobs = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(jobs, list):
            raise ConnectorError(
                "GITHUB_RESPONSE_INVALID",
                "GitHub returned invalid workflow-job data.",
            )
        return tuple(
            GitHubWorkflowJobSummary(
                job_id=int(item["id"]),
                run_id=run_id,
                name=str(item.get("name", "")),
                status=str(item.get("status", "")),
                conclusion=(
                    str(item["conclusion"])
                    if item.get("conclusion") is not None
                    else None
                ),
                runner_name=(
                    str(item["runner_name"])
                    if item.get("runner_name") is not None
                    else None
                ),
                started_at=self._datetime(item.get("started_at")),
                completed_at=self._datetime(item.get("completed_at")),
                html_url=str(item.get("html_url", "")),
            )
            for item in jobs
            if isinstance(item, dict)
        )

    def download_repository_zipball(
        self,
        owner: str,
        repository: str,
        commit_sha: str,
        *,
        max_bytes: int,
    ) -> bytes:
        response = self._client._send(
            "GET",
            self._repo_path(owner, repository, f"zipball/{commit_sha}"),
        )
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("location")
            if not location:
                raise ConnectorError(
                    "GITHUB_RESPONSE_INVALID",
                    "GitHub archive redirect was missing its destination.",
                )
            try:
                with httpx.Client(timeout=60.0, follow_redirects=True) as client:
                    response = client.get(location)
            except httpx.HTTPError as exc:
                raise ConnectorError(
                    "GITHUB_API_UNAVAILABLE",
                    "GitHub archive download could not complete.",
                    retryable=True,
                ) from exc
        if response.status_code != 200:
            self._client._raise_for_response(response)
        content = response.content
        if len(content) > max_bytes:
            raise ConnectorError(
                "GITHUB_ARCHIVE_TOO_LARGE",
                "The repository archive exceeds the managed workspace limit.",
            )
        return content

    def _paginate(
        self,
        path: str,
        *,
        max_pages: int = 10,
    ) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for page in range(1, max_pages + 1):
            payload = self._client._request_json(
                "GET",
                path,
                expected={200},
                params={"per_page": 100, "page": page},
            )
            if not isinstance(payload, list):
                raise ConnectorError(
                    "GITHUB_RESPONSE_INVALID",
                    "GitHub returned an invalid paginated list.",
                )
            batch = [item for item in payload if isinstance(item, dict)]
            result.extend(batch)
            if len(payload) < 100:
                break
        return result

    @staticmethod
    def _repo_path(owner: str, repository: str, suffix: str) -> str:
        return (
            f"/repos/{quote(owner, safe='')}/{quote(repository, safe='')}/"
            f"{suffix.lstrip('/')}"
        )

    @classmethod
    def _commit(cls, payload: object) -> GitHubCommitSummary:
        if not isinstance(payload, dict):
            raise ConnectorError(
                "GITHUB_RESPONSE_INVALID",
                "GitHub returned an invalid commit object.",
            )
        commit = payload.get("commit")
        if not isinstance(commit, dict):
            raise ConnectorError(
                "GITHUB_RESPONSE_INVALID",
                "GitHub commit metadata is missing.",
            )
        author_record = commit.get("author")
        user_record = payload.get("author")
        return GitHubCommitSummary(
            sha=str(payload.get("sha", "")),
            message=str(commit.get("message", "")),
            author_name=(
                str(author_record.get("name"))
                if isinstance(author_record, dict) and author_record.get("name")
                else None
            ),
            author_login=(
                str(user_record.get("login"))
                if isinstance(user_record, dict) and user_record.get("login")
                else None
            ),
            authored_at=(
                cls._datetime(author_record.get("date"))
                if isinstance(author_record, dict)
                else None
            ),
            html_url=(
                str(payload.get("html_url"))
                if payload.get("html_url") is not None
                else None
            ),
        )

    @staticmethod
    def _datetime(value: object) -> datetime | None:
        if value in {None, ""}:
            return None
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value))
