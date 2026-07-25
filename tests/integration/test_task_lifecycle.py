"""End-to-end API lifecycle tests retained across P1-P3."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from nexuss.api.app import app

client = TestClient(app)
SESSION_ID = UUID("00000000-0000-0000-0000-000000000201")


def _payload(request_id: str, utterance: str) -> dict[str, object]:
    return {
        "request_id": request_id,
        "channel": "text",
        "utterance": utterance,
        "user_session_id": str(SESSION_ID),
        "target_devices": [],
        "requested_at": datetime(2026, 7, 25, 12, 0, tzinfo=UTC).isoformat(),
        "client_context": {},
    }


def _headers(authenticated: bool = True) -> dict[str, str]:
    return {
        "X-Nexuss-Session-ID": str(SESSION_ID),
        "X-Nexuss-Session-Authenticated": str(authenticated).lower(),
    }


def test_daily_briefing_completes_with_verified_receipt() -> None:
    payload = _payload("00000000-0000-0000-0000-000000000301", "daily briefing")

    response = client.post("/v1/tasks", json=payload, headers=_headers())

    assert response.status_code == 202
    body = response.json()
    assert body["state"] == "completed"
    assert len(body["results"]) == 4
    assert all(result["status"] == "verified" for result in body["results"])

    receipt = client.get(f"/v1/tasks/{body['task_id']}/receipt")
    assert receipt.status_code == 200
    assert receipt.json()["verified"] is True
    assert receipt.json()["receipt_version"] == 1


def test_duplicate_request_is_idempotent() -> None:
    payload = _payload("00000000-0000-0000-0000-000000000302", "Check system health")

    first = client.post("/v1/tasks", json=payload, headers=_headers())
    second = client.post("/v1/tasks", json=payload, headers=_headers())

    assert first.status_code == second.status_code == 202
    assert first.json()["task_id"] == second.json()["task_id"]
    assert first.json()["events"] == second.json()["events"]


def test_prohibited_ats_write_is_denied_without_results() -> None:
    payload = _payload("00000000-0000-0000-0000-000000000303", "ATS buy BTC")

    response = client.post("/v1/tasks", json=payload, headers=_headers())

    assert response.status_code == 202
    assert response.json()["state"] == "denied"
    assert response.json()["results"] == []


def test_unreleased_workspace_preparation_is_denied() -> None:
    payload = _payload("00000000-0000-0000-0000-000000000304", "Prepare my workspace")

    response = client.post("/v1/tasks", json=payload, headers=_headers())

    assert response.status_code == 202
    assert response.json()["state"] == "denied"
    assert response.json()["results"] == []


def test_unauthenticated_session_is_rejected() -> None:
    payload = _payload("00000000-0000-0000-0000-000000000305", "daily briefing")

    response = client.post("/v1/tasks", json=payload, headers=_headers(authenticated=False))

    assert response.status_code == 401


def test_identity_question_returns_normal_verified_response() -> None:
    payload = _payload("00000000-0000-0000-0000-000000000306", "Who are you?")

    response = client.post("/v1/tasks", json=payload, headers=_headers())

    assert response.status_code == 202
    body = response.json()
    assert body["state"] == "completed"
    assert body["intent"]["kind"] == "assistant_identity"
    assert "personal cognitive control plane" in body["results"][0]["evidence"][0][
        "attributes"
    ]["response"]
