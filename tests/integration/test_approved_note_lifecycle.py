"""Full P3 approval, real write, evidence, receipt, and rollback API tests."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from nexuss.api.app import app

client = TestClient(app)
SESSION_ID = UUID("00000000-0000-0000-0000-000000000501")
OTHER_SESSION_ID = UUID("00000000-0000-0000-0000-000000000599")


def _headers(session_id: UUID = SESSION_ID) -> dict[str, str]:
    return {
        "X-Nexuss-Session-ID": str(session_id),
        "X-Nexuss-Session-Authenticated": "true",
    }


def _payload(request_id: str, utterance: str) -> dict[str, object]:
    return {
        "request_id": request_id,
        "channel": "text",
        "utterance": utterance,
        "user_session_id": str(SESSION_ID),
        "target_devices": [],
        "requested_at": datetime(2026, 7, 25, 16, 0, tzinfo=UTC).isoformat(),
        "client_context": {"interface": "p3-integration-test"},
    }


def _create_pending(request_id: str) -> dict[str, object]:
    response = client.post(
        "/v1/tasks",
        json=_payload(
            request_id,
            "Create a note called Nexuss launch checklist with the tasks: verify P3, "
            "review the Action Receipt, and test undo.",
        ),
        headers=_headers(),
    )
    assert response.status_code == 202
    task = response.json()
    assert task["state"] == "awaiting_approval"
    assert task["results"] == []
    assert task["approval"]["status"] == "pending"
    return task


def _decision(task: dict[str, object], decision: str = "approve") -> dict[str, str]:
    approval = task["approval"]
    assert isinstance(approval, dict)
    return {
        "approval_id": str(approval["approval_id"]),
        "approval_token": str(approval["approval_token"]),
        "payload_sha256": str(approval["payload_sha256"]),
        "decision": decision,
    }


def test_no_file_exists_before_approval_and_valid_approval_creates_verified_note() -> None:
    task = _create_pending("00000000-0000-0000-0000-000000000511")
    approval = task["approval"]
    assert isinstance(approval, dict)
    assert "# Nexuss launch checklist" in str(approval["exact_preview"])

    approved = client.post(
        f"/v1/tasks/{task['task_id']}/approval",
        json=_decision(task),
        headers=_headers(),
    )

    assert approved.status_code == 200
    body = approved.json()
    assert body["state"] == "completed"
    assert body["approval"]["approval_token"] is None
    evidence = body["results"][0]["evidence"][0]["attributes"]
    note_path = Path(evidence["managed_path"])
    assert note_path.is_file()
    assert evidence["source_mode"] == "live_local_controlled_write"
    assert evidence["verified"] is True
    assert len(evidence["sha256"]) == 64

    receipt = client.get(f"/v1/tasks/{task['task_id']}/receipt").json()
    assert receipt["verified"] is True
    assert receipt["reversible"] is True
    assert receipt["receipt_version"] == 2


def test_tampered_approval_hash_is_rejected_without_execution() -> None:
    task = _create_pending("00000000-0000-0000-0000-000000000512")
    decision = _decision(task)
    decision["payload_sha256"] = "0" * 64

    response = client.post(
        f"/v1/tasks/{task['task_id']}/approval",
        json=decision,
        headers=_headers(),
    )

    assert response.status_code == 409
    assert "APPROVAL_PAYLOAD_HASH_MISMATCH" in response.text
    current = client.get(f"/v1/tasks/{task['task_id']}").json()
    assert current["state"] == "awaiting_approval"
    assert current["results"] == []


def test_different_session_cannot_approve() -> None:
    task = _create_pending("00000000-0000-0000-0000-000000000513")

    response = client.post(
        f"/v1/tasks/{task['task_id']}/approval",
        json=_decision(task),
        headers=_headers(OTHER_SESSION_ID),
    )

    assert response.status_code == 401


def test_rejected_approval_creates_no_file() -> None:
    task = _create_pending("00000000-0000-0000-0000-000000000514")

    response = client.post(
        f"/v1/tasks/{task['task_id']}/approval",
        json=_decision(task, "reject"),
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json()["state"] == "denied"
    assert response.json()["results"] == []


def test_receipt_bound_rollback_removes_only_created_note() -> None:
    task = _create_pending("00000000-0000-0000-0000-000000000515")
    approved = client.post(
        f"/v1/tasks/{task['task_id']}/approval",
        json=_decision(task),
        headers=_headers(),
    ).json()
    note_path = Path(approved["results"][0]["evidence"][0]["attributes"]["managed_path"])
    assert note_path.exists()

    rollback = client.post(
        f"/v1/tasks/{task['task_id']}/rollback",
        json={"confirmation": "undo"},
        headers=_headers(),
    )

    assert rollback.status_code == 200
    body = rollback.json()
    assert body["state"] == "rolled_back"
    assert not note_path.exists()
    assert body["results"][-1]["capability_id"] == "workspace.rollback_create_note"
    receipt = client.get(f"/v1/tasks/{task['task_id']}/receipt").json()
    assert receipt["receipt_version"] == 3
    assert receipt["reversible"] is False


def test_path_traversal_note_is_denied_before_approval() -> None:
    response = client.post(
        "/v1/tasks",
        json=_payload(
            "00000000-0000-0000-0000-000000000516",
            "Create a note called ../escape with content forbidden",
        ),
        headers=_headers(),
    )

    assert response.status_code == 202
    task = response.json()
    assert task["state"] == "denied"
    assert task["approval"] is None
    assert task["policy_decisions"][0]["reason_code"] == "INVALID_MANAGED_NOTE_REQUEST"


def test_receipt_history_is_append_only() -> None:
    task = _create_pending("00000000-0000-0000-0000-000000000517")
    client.post(
        f"/v1/tasks/{task['task_id']}/approval",
        json=_decision(task, "reject"),
        headers=_headers(),
    )

    history = client.get(f"/v1/tasks/{task['task_id']}/receipts")

    assert history.status_code == 200
    assert [receipt["receipt_version"] for receipt in history.json()] == [1, 2]
    assert [receipt["state"] for receipt in history.json()] == [
        "awaiting_approval",
        "denied",
    ]
