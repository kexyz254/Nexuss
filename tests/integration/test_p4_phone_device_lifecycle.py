"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from nexuss.api.app import app
from tests.fakes import FakeDeviceNodeClient

client = TestClient(app)
SESSION_ID = "00000000-0000-0000-0000-000000000704"


def _headers() -> dict[str, str]:
    return {
        "X-Nexuss-Session-ID": SESSION_ID,
        "X-Nexuss-Session-Authenticated": "true",
    }


def _request_payload(request_id: str, utterance: str) -> dict[str, object]:
    return {
        "request_id": request_id,
        "channel": "text",
        "utterance": utterance,
        "user_session_id": SESSION_ID,
        "target_devices": ["windows-primary"],
        "requested_at": datetime.now(UTC).isoformat(),
        "client_context": {"interface": "p4-test"},
    }


def _pair_phone() -> dict[str, object]:
    challenge_response = client.post("/v1/mobile/pairing", headers=_headers(), json={})
    assert challenge_response.status_code == 200
    challenge = challenge_response.json()
    pair_response = client.post(
        "/v1/mobile/pair",
        json={"pairing_code": challenge["pairing_code"], "device_label": "Test phone"},
    )
    assert pair_response.status_code == 200
    return pair_response.json()


def _mobile_headers(phone: dict[str, object]) -> dict[str, str]:
    return {
        "X-Nexuss-Mobile-Device-ID": str(phone["device_id"]),
        "X-Nexuss-Mobile-Token": str(phone["device_token"]),
    }


def test_phone_approval_executes_and_rolls_back_trusted_device_command(
    fake_device_client: FakeDeviceNodeClient,
) -> None:
    response = client.post(
        "/v1/tasks",
        headers=_headers(),
        json=_request_payload(
            "00000000-0000-0000-0000-000000000741",
            "Open Notepad on this computer",
        ),
    )
    assert response.status_code == 202
    task = response.json()
    assert task["state"] == "awaiting_approval"
    assert task["intent"]["kind"] == "launch_notepad"
    assert task["approval"]["approval_channel"] == "phone"
    assert task["plan"]["steps"][0]["capability_id"] == "device.launch_notepad"
    assert fake_device_client.launches == []

    desktop_approval = client.post(
        f"/v1/tasks/{task['task_id']}/approval",
        headers=_headers(),
        json={
            "approval_id": task["approval"]["approval_id"],
            "approval_token": task["approval"]["approval_token"],
            "payload_sha256": task["approval"]["payload_sha256"],
            "decision": "approve",
        },
    )
    assert desktop_approval.status_code == 409
    assert "PHONE_APPROVAL_REQUIRED" in desktop_approval.text
    assert fake_device_client.launches == []

    phone = _pair_phone()
    pending_response = client.get(
        "/v1/mobile/pending",
        headers=_mobile_headers(phone),
    )
    assert pending_response.status_code == 200
    pending = pending_response.json()
    assert len(pending) == 1
    approval = pending[0]
    assert approval["task_id"] == task["task_id"]
    assert approval["exact_preview"].startswith("Capability: device.launch_notepad")

    decision_response = client.post(
        f"/v1/mobile/tasks/{task['task_id']}/decision",
        headers=_mobile_headers(phone),
        json={
            "approval_id": approval["approval_id"],
            "approval_token": approval["approval_token"],
            "payload_sha256": approval["payload_sha256"],
            "decision": "approve",
        },
    )
    assert decision_response.status_code == 200
    completed = decision_response.json()
    assert completed["state"] == "completed"
    assert completed["results"][0]["status"] == "verified"
    evidence = completed["results"][0]["evidence"][0]["attributes"]
    assert evidence["source_mode"] == "live_trusted_device_node"
    assert evidence["verified_running"] is True
    assert fake_device_client.launches == [(UUID(task["task_id"]), "windows-primary")]

    receipt_response = client.get(f"/v1/tasks/{task['task_id']}/receipt")
    assert receipt_response.status_code == 200
    receipt = receipt_response.json()
    assert receipt["verified"] is True
    assert receipt["reversible"] is True

    rollback_response = client.post(
        f"/v1/tasks/{task['task_id']}/rollback",
        headers=_headers(),
        json={"confirmation": "undo"},
    )
    assert rollback_response.status_code == 200
    rolled_back = rollback_response.json()
    assert rolled_back["state"] == "rolled_back"
    assert rolled_back["results"][-1]["capability_id"] == "device.rollback_launch_notepad"
    assert fake_device_client.rollbacks


def test_desktop_can_cancel_phone_approval_without_execution(
    fake_device_client: FakeDeviceNodeClient,
) -> None:
    task = client.post(
        "/v1/tasks",
        headers=_headers(),
        json=_request_payload(
            "00000000-0000-0000-0000-000000000742",
            "Launch Notepad",
        ),
    ).json()

    rejection = client.post(
        f"/v1/tasks/{task['task_id']}/approval",
        headers=_headers(),
        json={
            "approval_id": task["approval"]["approval_id"],
            "approval_token": task["approval"]["approval_token"],
            "payload_sha256": task["approval"]["payload_sha256"],
            "decision": "reject",
        },
    )
    assert rejection.status_code == 200
    assert rejection.json()["state"] == "denied"
    assert fake_device_client.launches == []


def test_mobile_ui_is_served_same_origin() -> None:
    page = client.get("/mobile")
    script = client.get("/assets/mobile.js")
    stylesheet = client.get("/assets/mobile.css")

    assert page.status_code == 200
    assert "Trusted phone approval" in page.text
    assert script.status_code == 200
    assert "X-Nexuss-Mobile-Token" in script.text
    assert stylesheet.status_code == 200
    assert "PHONE GUARD ACTIVE" not in stylesheet.text
