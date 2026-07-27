"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Memory driven the way a person drives it: as instructions through the task
API, against the same wiring production uses.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from nexuss.api.app import app

client = TestClient(app)


def _headers(session_id: UUID) -> dict[str, str]:
    return {
        "X-Nexuss-Session-ID": str(session_id),
        "X-Nexuss-Session-Authenticated": "true",
    }


def _run(session_id: UUID, utterance: str) -> dict[str, object]:
    response = client.post(
        "/v1/tasks",
        headers=_headers(session_id),
        json={
            "request_id": str(uuid4()),
            "channel": "text",
            "utterance": utterance,
            "user_session_id": str(session_id),
            "target_devices": [],
            "requested_at": datetime.now(UTC).isoformat(),
            "client_context": {"interface": "p53-test"},
        },
    )
    assert response.status_code == 202
    return dict(response.json())


def _first_evidence(task: dict[str, object]) -> dict[str, object]:
    results = list(task["results"])  # type: ignore[call-overload]
    evidence = list(results[0]["evidence"])
    return dict(evidence[0]["attributes"])


def test_remember_then_recall_round_trips_with_provenance() -> None:
    session_id = uuid4()

    stored = _run(session_id, "remember that maker fees are lower than taker fees")
    assert stored["state"] == "completed"
    assert stored["approval"] is None
    assert _first_evidence(stored)["source_trust"] == "user_asserted"

    recalled = _run(session_id, "what do you remember about maker fees")
    attributes = _first_evidence(recalled)

    assert recalled["state"] == "completed"
    assert attributes["match_count"] >= 1
    top = dict(next(iter(attributes["matches"])))
    assert "maker fees" in str(top["statement"])
    assert top["source_trust"] == "user_asserted"
    assert float(str(top["confidence"])) > 0.9


def test_recall_with_nothing_stored_reports_zero_matches() -> None:
    task = _run(uuid4(), "recall quantum basket weaving")

    assert task["state"] == "completed"
    assert _first_evidence(task)["match_count"] == 0


def test_forgetting_a_topic_requires_desktop_approval_first() -> None:
    """Deletion is irreversible; it must never run unattended."""
    session_id = uuid4()
    _run(session_id, "remember that my staging folder is Downloads p5.2")

    task = _run(session_id, "forget about my staging folder")

    assert task["state"] == "awaiting_approval"

    recalled = _run(session_id, "what do you remember about staging folder")
    assert _first_evidence(recalled)["match_count"] >= 1


def test_credential_shaped_statements_are_refused_through_the_api() -> None:
    session_id = uuid4()
    secret = "remember that my api key is AIzaSyA" + "x" * 33

    task = _run(session_id, secret)
    results = list(task["results"])  # type: ignore[call-overload]

    assert task["state"] == "failed"
    assert results[0]["error_code"] == "MEMORY_WRITE_REFUSED_CREDENTIAL_SHAPED"

    recalled = _run(session_id, "recall api key")
    assert _first_evidence(recalled)["match_count"] == 0


def test_forget_this_device_still_means_unpair_not_memory() -> None:
    """The collision that must never regress: device revocation and memory
    deletion share the verb 'forget'."""
    task = _run(uuid4(), "forget this device")
    results = list(task["results"])  # type: ignore[call-overload]

    capability_ids = {str(result["capability_id"]) for result in results} | {
        str(step["capability_id"])
        for step in dict(task.get("plan") or {}).get("steps", [])
    }
    assert "memory.forget" not in capability_ids
