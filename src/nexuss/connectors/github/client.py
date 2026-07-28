"""Bounded GitHub REST API client."""

from __future__ import annotations

from urllib.parse import quote

import httpx

from nexuss.connectors.errors import ConnectorError
from nexuss.connectors.github.models import GitHubAccount, GitHubRepository

_API_VERSION = "2026-03-10"


class GitHubApiClient:
    def __init__(
        self,
        access_token: str,
        *,
        api_base: str = "https://api.github.com",
        timeout_seconds: float = 25.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not access_token:
            raise ValueError("access_token is required")
        self._access_token = access_token
        self._api_base = api_base.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    def authenticated_user(self) -> GitHubAccount:
        payload = self._request_json("GET", "/user", expected={200})
        if not isinstance(payload, dict):
            raise ConnectorError("GITHUB_RESPONSE_INVALID", "GitHub returned an invalid user object.")
        return GitHubAccount(
            account_id=int(payload["id"]),
            login=str(payload["login"]),
            account_type=str(payload.get("type", "User")),
            html_url=str(payload["html_url"]),
            avatar_url=payload.get("avatar_url"),
        )

    def list_repositories(self, *, max_pages: int = 10) -> tuple[GitHubRepository, ...]:
        repositories: list[GitHubRepository] = []
        for page in range(1, max_pages + 1):
            payload = self._request_json(
                "GET",
                "/user/repos",
                expected={200},
                params={
                    "visibility": "all",
                    "affiliation": "owner,collaborator,organization_member",
                    "sort": "updated",
                    "direction": "desc",
                    "per_page": 100,
                    "page": page,
                },
            )
            if not isinstance(payload, list):
                raise ConnectorError("GITHUB_RESPONSE_INVALID", "GitHub returned an invalid repository list.")
            batch = tuple(self._repository(item) for item in payload if isinstance(item, dict))
            repositories.extend(batch)
            if len(batch) < 100:
                break
        return tuple(repositories)

    def get_repository(self, owner: str, repository: str) -> GitHubRepository:
        payload = self._request_json(
            "GET",
            f"/repos/{quote(owner, safe='')}/{quote(repository, safe='')}",
            expected={200},
        )
        if not isinstance(payload, dict):
            raise ConnectorError("GITHUB_RESPONSE_INVALID", "GitHub returned an invalid repository object.")
        return self._repository(payload)

    def create_repository(self, payload: dict[str, object]) -> GitHubRepository:
        result = self._request_json("POST", "/user/repos", expected={201}, json_body=payload)
        if not isinstance(result, dict):
            raise ConnectorError("GITHUB_RESPONSE_INVALID", "GitHub returned an invalid created repository.")
        return self._repository(result)

    def repository_is_empty(self, owner: str, repository: str) -> bool:
        response = self._send(
            "GET",
            f"/repos/{quote(owner, safe='')}/{quote(repository, safe='')}/commits",
            params={"per_page": 1},
        )
        if response.status_code == 409:
            return True
        if response.status_code == 200:
            return False
        self._raise_for_response(response)
        raise AssertionError("unreachable")

    def repository_exists(self, owner: str, repository: str) -> bool:
        response = self._send(
            "GET",
            f"/repos/{quote(owner, safe='')}/{quote(repository, safe='')}",
        )
        if response.status_code == 200:
            return True
        if response.status_code == 404:
            return False
        self._raise_for_response(response)
        raise AssertionError("unreachable")

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        expected: set[int],
        params: dict[str, object] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> object:
        response = self._send(method, path, params=params, json_body=json_body)
        if response.status_code not in expected:
            self._raise_for_response(response)
        try:
            return response.json()
        except ValueError as exc:
            raise ConnectorError("GITHUB_RESPONSE_INVALID", "GitHub returned non-JSON content.") from exc

    def _send(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, object] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> httpx.Response:
        try:
            with httpx.Client(
                base_url=self._api_base,
                timeout=self._timeout_seconds,
                transport=self._transport,
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {self._access_token}",
                    "X-GitHub-Api-Version": _API_VERSION,
                    "User-Agent": "Nexuss-GitHub-Connector/1.0",
                },
            ) as client:
                return client.request(method, path, params=params, json=json_body)
        except httpx.HTTPError as exc:
            raise ConnectorError("GITHUB_API_UNAVAILABLE", "GitHub could not be reached.", retryable=True) from exc

    @staticmethod
    def _raise_for_response(response: httpx.Response) -> None:
        status = response.status_code
        if status == 401:
            raise ConnectorError("GITHUB_REAUTH_REQUIRED", "GitHub rejected the stored authorization.")
        if status == 403:
            if response.headers.get("X-RateLimit-Remaining") == "0":
                raise ConnectorError("GITHUB_RATE_LIMITED", "GitHub API rate limit was reached.", retryable=True)
            raise ConnectorError("GITHUB_PERMISSION_INSUFFICIENT", "The GitHub authorization lacks permission.")
        if status == 404:
            raise ConnectorError("GITHUB_RESOURCE_NOT_FOUND", "The requested GitHub resource was not found.")
        if status == 422:
            raise ConnectorError("GITHUB_VALIDATION_FAILED", "GitHub rejected the requested payload.")
        raise ConnectorError("GITHUB_API_FAILED", f"GitHub returned HTTP {status}.", retryable=status >= 500)

    @staticmethod
    def _repository(payload: dict[str, object]) -> GitHubRepository:
        owner = payload.get("owner")
        if not isinstance(owner, dict):
            raise ConnectorError("GITHUB_RESPONSE_INVALID", "Repository owner data is missing.")
        permissions = payload.get("permissions") or {}
        if not isinstance(permissions, dict):
            permissions = {}
        return GitHubRepository(
            repository_id=int(payload["id"]),
            node_id=str(payload.get("node_id", "")),
            name=str(payload["name"]),
            full_name=str(payload["full_name"]),
            owner_login=str(owner["login"]),
            private=bool(payload.get("private", False)),
            archived=bool(payload.get("archived", False)),
            disabled=bool(payload.get("disabled", False)),
            fork=bool(payload.get("fork", False)),
            html_url=str(payload["html_url"]),
            api_url=str(payload["url"]),
            default_branch=str(payload["default_branch"]) if payload.get("default_branch") else None,
            size_kb=int(payload.get("size", 0)),
            open_issues_count=int(payload.get("open_issues_count", 0)),
            created_at=payload.get("created_at"),
            updated_at=payload.get("updated_at"),
            pushed_at=payload.get("pushed_at"),
            permissions={str(key): bool(value) for key, value in permissions.items()},
        )
