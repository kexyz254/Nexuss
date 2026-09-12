"""P6.12 local runtime status API tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from nexuss.api.app import app


client = TestClient(app)


def _headers(session_id: str) -> dict[str, str]:
    return {
        "X-Nexuss-Session-ID": session_id,
        "X-Nexuss-Session-Authenticated": "true",
    }


def test_device_node_status_never_exposes_shared_secret() -> None:
    response = client.get("/v1/device-node/status")
    assert response.status_code == 200
    payload = response.json()
    flattened = str(payload).casefold()
    assert "nexuss_device_node_secret" not in flattened
    assert "shared_secret" not in flattened
    assert set(payload) == {
        "configured",
        "reachable",
        "reason_code",
        "node_url",
    }


def test_task_status_is_safe_projection() -> None:
    session_id = str(uuid4())
    request_id = str(uuid4())
    response = client.post(
        "/v1/tasks",
        headers=_headers(session_id),
        json={
            "request_id": request_id,
            "channel": "text",
            "utterance": "hello",
            "user_session_id": session_id,
            "target_devices": [],
            "requested_at": datetime.now(UTC).isoformat(),
            "client_context": {},
        },
    )
    assert response.status_code == 202, response.text
    task_id = response.json()["task_id"]

    status = client.get(
        f"/v1/tasks/{task_id}/status",
        headers=_headers(session_id),
    )
    assert status.status_code == 200, status.text
    payload = status.json()
    assert payload["phase"] == "done"
    assert payload["terminal"] is True

    flattened = str(payload).casefold()
    assert "approval_token" not in flattened
    assert "exact_preview" not in flattened
    assert "payload_sha256" not in flattened


def test_mobile_snapshot_route_is_registered_and_fails_closed_without_auth() -> None:
    assert any(route.path == "/v1/mobile/snapshot" for route in app.routes)
    response = client.get("/v1/mobile/snapshot")
    assert response.status_code == 401
    assert response.json()["detail"] == "MOBILE_AUTH_REQUIRED"
