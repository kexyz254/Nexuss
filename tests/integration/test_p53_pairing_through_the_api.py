"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Device pairing driven the way a person drives it: as an instruction to Nexuss,
through the task API, rather than by calling the gateway directly.

These tests exist because the unit suite exercises the executor with a gateway
handed to it explicitly. That passes even when the running service has no
gateway wired at all, which is exactly the gap this file closes.
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


def _pair(session_id: UUID, label: str = "Primary phone") -> dict[str, object]:
    attributes = _first_evidence(_run(session_id, "Pair my phone"))
    response = client.post(
        "/v1/mobile/pair",
        json={
            "pairing_code": str(attributes["pairing_code"]),
            "device_label": label,
        },
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


def test_asking_nexuss_to_pair_returns_a_usable_challenge() -> None:
    task = _run(uuid4(), "Pair my phone")

    assert task["state"] == "completed"
    assert task["approval"] is None

    attributes = _first_evidence(task)
    code = str(attributes["pairing_code"])

    assert code.isdigit()
    assert len(code) == 8
    assert str(attributes["pair_url"]).endswith(f"?pair={code}")


def test_the_issued_code_actually_pairs_a_phone() -> None:
    """The challenge must be real, not merely well-formed."""
    session_id = uuid4()
    _pair(session_id)

    listed = client.get("/v1/mobile/devices", headers=_headers(session_id))
    assert listed.status_code == 200
    assert [device["device_label"] for device in listed.json()] == ["Primary phone"]


def test_a_reissued_code_retires_the_previous_one() -> None:
    """Rotation is what makes a displayed or scanned code safe to show."""
    session_id = uuid4()
    first = _first_evidence(_run(session_id, "Pair my phone"))
    second = _first_evidence(_run(session_id, "Pair my phone"))

    assert first["pairing_code"] != second["pairing_code"]

    stale = client.post(
        "/v1/mobile/pair",
        json={
            "pairing_code": str(first["pairing_code"]),
            "device_label": "Should not pair",
        },
    )
    assert stale.status_code == 409

    current = client.post(
        "/v1/mobile/pair",
        json={
            "pairing_code": str(second["pairing_code"]),
            "device_label": "Primary phone",
        },
    )
    assert current.status_code == 200


def test_listing_devices_by_instruction_reports_the_paired_phone() -> None:
    session_id = uuid4()
    _pair(session_id)

    task = _run(session_id, "show my paired devices")
    inventory = _first_evidence(task)

    assert task["state"] == "completed"
    assert inventory["device_count"] == 1
    assert "token_sha256" not in str(inventory)


def test_unpairing_stops_for_approval_before_revoking_anything() -> None:
    """Revocation is irreversible, so it must never run unattended."""
    session_id = uuid4()
    _pair(session_id)

    task = _run(session_id, "unpair Primary phone")

    assert task["state"] == "awaiting_approval"

    still_paired = client.get("/v1/mobile/devices", headers=_headers(session_id))
    assert len(still_paired.json()) == 1


def test_repeated_pairing_attempts_are_still_rate_limited() -> None:
    """Isolating the limiter per test must not disable it.

    The limiter is the reason a displayed pairing code is safe: it caps how
    many guesses an attacker on the LAN gets inside the ten-minute window.
    """
    session_id = uuid4()
    attributes = _first_evidence(_run(session_id, "Pair my phone"))
    real_code = str(attributes["pairing_code"])

    statuses = [
        client.post(
            "/v1/mobile/pair",
            json={"pairing_code": f"{index:08d}", "device_label": "Guess"},
        ).status_code
        for index in range(6)
    ]

    assert statuses[-1] == 429
    assert 429 not in statuses[:4]

    refused = client.post(
        "/v1/mobile/pair",
        json={"pairing_code": real_code, "device_label": "Primary phone"},
    )
    assert refused.status_code == 429
