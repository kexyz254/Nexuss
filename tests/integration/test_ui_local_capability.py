"""End-to-end UI and live local read-only capability tests for P2."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from nexuss.api.app import app

client = TestClient(app)
SESSION_ID = UUID("00000000-0000-0000-0000-000000000401")


def _payload(request_id: str, utterance: str) -> dict[str, object]:
    return {
        "request_id": request_id,
        "channel": "text",
        "utterance": utterance,
        "user_session_id": str(SESSION_ID),
        "target_devices": [],
        "requested_at": datetime(2026, 7, 25, 15, 0, tzinfo=UTC).isoformat(),
        "client_context": {"interface": "p2-test"},
    }


def _headers() -> dict[str, str]:
    return {
        "X-Nexuss-Session-ID": str(SESSION_ID),
        "X-Nexuss-Session-Authenticated": "true",
    }


def test_ui_and_assets_are_served_same_origin() -> None:
    page = client.get("/")
    script = client.get("/assets/app.js")
    stylesheet = client.get("/assets/styles.css")

    assert page.status_code == 200
    assert "NEXUSS" in page.text
    assert "command-form" in page.text
    assert script.status_code == 200
    assert "SpeechRecognition" in script.text
    assert stylesheet.status_code == 200


def test_workspace_status_runs_live_readonly_lifecycle() -> None:
    response = client.post(
        "/v1/tasks",
        json=_payload(
            "00000000-0000-0000-0000-000000000402",
            "Check my workspace and system status",
        ),
        headers=_headers(),
    )

    assert response.status_code == 202
    task = response.json()
    assert task["state"] == "completed"
    assert task["intent"]["kind"] == "local_workspace_status"
    assert [step["capability_id"] for step in task["plan"]["steps"]] == [
        "workspace.read_status"
    ]
    assert task["policy_decisions"][0]["outcome"] == "allow"

    result = task["results"][0]
    assert result["status"] == "verified"
    assert result["evidence"][0]["source"] == "local:workspace"
    attributes = result["evidence"][0]["attributes"]
    assert attributes["source_mode"] == "live_local_readonly"
    assert attributes["repository_name"]
    assert len(attributes["git_commit"]) == 40

    receipt = client.get(f"/v1/tasks/{task['task_id']}/receipt")
    assert receipt.status_code == 200
    assert receipt.json()["verified"] is True
