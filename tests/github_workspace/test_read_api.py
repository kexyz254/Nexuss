from __future__ import annotations

import io
import zipfile

import httpx

from nexuss.connectors.github.client import GitHubApiClient
from nexuss.connectors.github.read_api import GitHubReadOnlyApi


def _zip_bytes() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("root/README.md", "# demo")
    return output.getvalue()


def test_read_api_parses_repository_surfaces() -> None:
    archive = _zip_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/user":
            return httpx.Response(
                200,
                json={
                    "id": 1,
                    "login": "kexyz254",
                    "type": "User",
                    "html_url": "https://github.com/kexyz254",
                },
            )
        if path == "/user/repos":
            return httpx.Response(200, json=[])
        if path == "/user/orgs":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 2,
                        "login": "example-org",
                        "html_url": "https://github.com/example-org",
                        "description": "Example",
                    }
                ],
            )
        if path == "/user/installations":
            return httpx.Response(
                200,
                json={
                    "installations": [
                        {
                            "id": 3,
                            "account": {"login": "kexyz254", "type": "User"},
                            "repository_selection": "selected",
                            "permissions": {"contents": "read"},
                            "suspended_at": None,
                        }
                    ]
                },
            )
        if path.endswith("/commits/main"):
            return httpx.Response(
                200,
                json={
                    "sha": "a" * 40,
                    "html_url": "https://github.com/kexyz254/demo/commit/a",
                    "author": {"login": "kexyz254"},
                    "commit": {
                        "message": "initial",
                        "author": {
                            "name": "Peter",
                            "date": "2026-07-29T12:00:00Z",
                        },
                    },
                },
            )
        if path.endswith("/branches"):
            return httpx.Response(
                200,
                json=[
                    {
                        "name": "main",
                        "commit": {"sha": "a" * 40},
                        "protected": True,
                    }
                ],
            )
        if path.endswith("/tags"):
            return httpx.Response(200, json=[])
        if path.endswith("/commits"):
            return httpx.Response(200, json=[])
        if path.endswith("/pulls"):
            return httpx.Response(200, json=[])
        if path.endswith("/issues"):
            return httpx.Response(200, json=[])
        if path.endswith("/actions/workflows"):
            return httpx.Response(200, json={"workflows": []})
        if path.endswith("/actions/runs"):
            return httpx.Response(200, json={"workflow_runs": []})
        if "/actions/runs/" in path and path.endswith("/jobs"):
            return httpx.Response(200, json={"jobs": []})
        if "/zipball/" in path:
            return httpx.Response(200, content=archive)
        raise AssertionError(f"Unexpected request: {request.method} {path}")

    api = GitHubReadOnlyApi(
        GitHubApiClient(
            "token",
            transport=httpx.MockTransport(handler),
        )
    )

    assert api.authenticated_user().login == "kexyz254"
    assert api.list_organizations()[0].login == "example-org"
    assert api.list_user_installations()[0].permissions == {"contents": "read"}
    assert api.resolve_commit("kexyz254", "demo", "main").sha == "a" * 40
    assert api.list_branches("kexyz254", "demo")[0].protected is True
    assert api.list_tags("kexyz254", "demo") == ()
    assert api.list_pull_requests("kexyz254", "demo") == ()
    assert api.list_issues("kexyz254", "demo") == ()
    assert api.list_workflows("kexyz254", "demo") == ()
    assert api.list_workflow_runs("kexyz254", "demo") == ()
    assert api.download_repository_zipball(
        "kexyz254",
        "demo",
        "a" * 40,
        max_bytes=1_000_000,
    ) == archive
