from __future__ import annotations

import httpx

from nexuss.connectors.github.client import GitHubApiClient


def test_git_database_client_contract() -> None:
    calls: list[tuple[str, str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = None
        if request.content:
            import json

            payload = json.loads(request.content)
        calls.append((request.method, request.url.path, payload))

        path = request.url.path
        if path.endswith("/git/blobs"):
            return httpx.Response(201, json={"sha": "1" * 40})
        if path.endswith("/git/trees") and request.method == "POST":
            return httpx.Response(201, json={"sha": "2" * 40})
        if path.endswith("/git/commits") and request.method == "POST":
            return httpx.Response(201, json={"sha": "3" * 40})
        if path.endswith("/git/refs"):
            return httpx.Response(
                201,
                json={"object": {"sha": "3" * 40}},
            )
        if "/git/ref/heads/main" in path:
            return httpx.Response(
                200,
                json={"object": {"sha": "3" * 40}},
            )
        if "/git/commits/" in path:
            return httpx.Response(
                200,
                json={
                    "sha": "3" * 40,
                    "tree": {"sha": "2" * 40},
                    "parents": [],
                },
            )
        if "/git/trees/" in path:
            return httpx.Response(
                200,
                json={
                    "sha": "2" * 40,
                    "truncated": False,
                    "tree": [],
                },
            )
        raise AssertionError(path)

    client = GitHubApiClient(
        "token",
        transport=httpx.MockTransport(handler),
    )
    assert client.create_git_blob(
        "owner",
        "repo",
        "YQ==",
    ) == "1" * 40
    assert client.create_git_tree(
        "owner",
        "repo",
        [
            {
                "path": "a.txt",
                "mode": "100644",
                "type": "blob",
                "sha": "1" * 40,
            }
        ],
    ) == "2" * 40
    assert client.create_git_commit(
        "owner",
        "repo",
        message="initial",
        tree_sha="2" * 40,
        parents=[],
    ) == "3" * 40
    assert client.create_git_reference(
        "owner",
        "repo",
        reference="refs/heads/main",
        commit_sha="3" * 40,
    ) == "3" * 40
    assert client.get_git_reference(
        "owner",
        "repo",
        "heads/main",
    ) == "3" * 40
    assert client.get_git_commit(
        "owner",
        "repo",
        "3" * 40,
    )["sha"] == "3" * 40
    assert client.get_git_tree(
        "owner",
        "repo",
        "2" * 40,
        recursive=True,
    )["sha"] == "2" * 40

    commit_call = next(
        item for item in calls if item[1].endswith("/git/commits")
    )
    assert commit_call[2]["parents"] == []
    assert commit_call[2]["tree"] == "2" * 40
