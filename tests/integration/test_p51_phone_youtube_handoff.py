"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from nexuss.api.app import app

client = TestClient(app)
SESSION_ID = "00000000-0000-0000-0000-000000000754"


def _headers() -> dict[str, str]:
    return {
        "X-Nexuss-Session-ID": SESSION_ID,
        "X-Nexuss-Session-Authenticated": "true",
    }


def _payload() -> dict[str, object]:
    return {
        "request_id": "00000000-0000-0000-0000-000000000755",
        "channel": "text",
        "utterance": (
            "Open YouTube on my phone and search Silence by Popcaan"
        ),
        "user_session_id": SESSION_ID,
        "target_devices": [],
        "requested_at": datetime.now(UTC).isoformat(),
        "client_context": {"interface": "p51-test"},
    }


def _pair_phone() -> dict[str, object]:
    challenge_response = client.post(
        "/v1/mobile/pairing",
        headers=_headers(),
        json={},
    )
    assert challenge_response.status_code == 200
    challenge = challenge_response.json()
    pair_response = client.post(
        "/v1/mobile/pair",
        json={
            "pairing_code": challenge["pairing_code"],
            "device_label": "Primary phone",
        },
    )
    assert pair_response.status_code == 200
    return pair_response.json()


def _mobile_headers(phone: dict[str, object]) -> dict[str, str]:
    return {
        "X-Nexuss-Mobile-Device-ID": str(phone["device_id"]),
        "X-Nexuss-Mobile-Token": str(phone["device_token"]),
    }


def test_paired_phone_claims_allowlisted_youtube_handoff_without_approval() -> None:
    phone = _pair_phone()
    task_response = client.post(
        "/v1/tasks",
        headers=_headers(),
        json=_payload(),
    )

    assert task_response.status_code == 202
    task = task_response.json()
    assert task["state"] == "completed"
    assert task["approval"] is None
    assert task["policy_decisions"][0]["outcome"] == "allow"

    first = client.get(
        "/v1/mobile/handoffs",
        headers=_mobile_headers(phone),
    )
    second = client.get(
        "/v1/mobile/handoffs",
        headers=_mobile_headers(phone),
    )

    assert first.status_code == 200
    handoffs = first.json()
    assert len(handoffs) == 1
    assert handoffs[0]["query"] == "Silence by Popcaan"
    assert handoffs[0]["launch_url"].startswith(
        "https://www.youtube.com/results?search_query="
    )
    assert second.status_code == 200
    assert second.json() == []
