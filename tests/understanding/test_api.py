"""Copyright © kexyz254peter.
Nexuss AI - Confidential and Proprietary.
Unauthorized copying, redistribution or disclosure is prohibited.

FastAPI surface and session enforcement tests.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from nexuss.understanding.api import register_understanding_routes
from nexuss.understanding.models import GoalExecutionResult
from nexuss.understanding.service import GoalUnderstandingService


class FakeGitHubExecutor:
    def repositories(self):
        return (
            {
                "full_name": "kexyz254/GlyphSentry-Core-Final",
                "private": True,
                "default_branch": "main",
            },
        )

    def execute(self, interpretation):
        return GoalExecutionResult(
            operation=interpretation.goal.value,
            assistant_message="Read-only operation completed.",
            data={"ok": True},
            evidence_sha256="d" * 64,
        )


def _app() -> FastAPI:
    app = FastAPI()

    def local(request: Request) -> None:
        assert request.client is not None

    register_understanding_routes(
        app,
        local,
        service=GoalUnderstandingService(
            github_executor=FakeGitHubExecutor()
        ),
    )
    return app


def _headers(session_id=None, authenticated="true"):
    return {
        "X-Nexuss-Session-ID": str(session_id or uuid4()),
        "X-Nexuss-Session-Authenticated": authenticated,
    }


def test_health_contract() -> None:
    client = TestClient(_app())
    response = client.get("/v1/understanding/health")

    assert response.status_code == 200
    body = response.json()
    assert body["approval_authority_changed"] is False
    assert body["github_read_only_available"] is True
    assert body["github_write_authority_added"] is False


def test_unauthenticated_resolution_is_rejected() -> None:
    client = TestClient(_app())
    response = client.post(
        "/v1/understanding/resolve",
        headers=_headers(authenticated="false"),
        json={"utterance": "What can you do?"},
    )

    assert response.status_code == 401


def test_resolve_returns_clarification_contract() -> None:
    client = TestClient(_app())
    response = client.post(
        "/v1/understanding/resolve",
        headers=_headers(),
        json={"utterance": "Fix it."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "clarification_required"
    assert body["clarification"]["kind"] in {
        "yes_no",
        "single_select",
    }


def test_resolve_executes_safe_github_read() -> None:
    client = TestClient(_app())
    response = client.post(
        "/v1/understanding/resolve",
        headers=_headers(),
        json={
            "utterance": (
                "Inspect kexyz254/GlyphSentry-Core-Final. "
                "Do not modify anything."
            )
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["execution"]["github_write_performed"] is False
