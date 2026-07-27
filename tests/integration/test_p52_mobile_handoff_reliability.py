"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

P5.2 regression tests for the two silent failure modes that made the paired
phone appear connected while never receiving a handoff.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from nexuss.api.app import app
from nexuss.core.service import CoreSimulatorService
from nexuss.domain.models import (
    AssuranceLevel,
    Channel,
    IdentitySession,
    TaskRequest,
    TaskState,
)

client = TestClient(app)


def _desktop_headers(session_id: UUID) -> dict[str, str]:
    return {
        "X-Nexuss-Session-ID": str(session_id),
        "X-Nexuss-Session-Authenticated": "true",
    }


def _mobile_headers(phone: dict[str, object]) -> dict[str, str]:
    return {
        "X-Nexuss-Mobile-Device-ID": str(phone["device_id"]),
        "X-Nexuss-Mobile-Token": str(phone["device_token"]),
    }


def _payload(session_id: UUID) -> dict[str, object]:
    return {
        "request_id": str(uuid4()),
        "channel": "text",
        "utterance": "Open YouTube on my phone and search Silence by Popcaan",
        "user_session_id": str(session_id),
        "target_devices": [],
        "requested_at": datetime.now(UTC).isoformat(),
        "client_context": {"interface": "p52-test"},
    }


def _pair_phone(session_id: UUID) -> dict[str, object]:
    challenge = client.post(
        "/v1/mobile/pairing",
        headers=_desktop_headers(session_id),
        json={},
    )
    assert challenge.status_code == 200
    paired = client.post(
        "/v1/mobile/pair",
        json={
            "pairing_code": challenge.json()["pairing_code"],
            "device_label": "Primary phone",
        },
    )
    assert paired.status_code == 200
    return paired.json()


def test_stale_handoffs_are_not_replayed_to_a_phone() -> None:
    """A phone must never auto-open a link the desktop sent hours earlier.

    Driven against a service instance this test owns. Reaching into the
    module-level singleton in nexuss.api.app couples the assertion to whatever
    else has touched that object during the run, which is a property of the
    harness rather than of the behaviour under test.
    """
    own_service = CoreSimulatorService()
    session_id = uuid4()

    view = own_service.create_task(
        TaskRequest(
            request_id=uuid4(),
            channel=Channel.TEXT,
            utterance="Open YouTube on my phone and search Silence by Popcaan",
            user_session_id=session_id,
            target_devices=[],
            requested_at=datetime.now(UTC),
            client_context={"interface": "p52-test"},
        ),
        IdentitySession(
            session_id=session_id,
            authenticated=True,
            assurance_level=AssuranceLevel.BASIC,
        ),
    )
    assert view.state is TaskState.COMPLETED

    fresh = own_service.list_phone_handoffs(session_id)
    assert len(fresh) == 1
    assert fresh[0].query == "Silence by Popcaan"

    later = datetime.now(UTC) + timedelta(minutes=30)
    assert own_service.list_phone_handoffs(session_id, now=later) == ()


def test_handoffs_survive_a_new_desktop_session_after_rebind() -> None:
    """The exact failure the diagnostic bundle showed.

    The phone pairs against one desktop identity. The browser tab is replaced
    and a new identity appears. Before rebinding, the phone polls forever and
    receives nothing while still reporting itself as paired.
    """
    first_session = uuid4()
    phone = _pair_phone(first_session)

    second_session = uuid4()
    task = client.post(
        "/v1/tasks",
        headers=_desktop_headers(second_session),
        json=_payload(second_session),
    )
    assert task.status_code == 202

    orphaned = client.get("/v1/mobile/handoffs", headers=_mobile_headers(phone))
    assert orphaned.status_code == 200
    assert orphaned.json() == []

    rebind = client.post(
        "/v1/mobile/devices/rebind",
        headers=_desktop_headers(second_session),
        json={},
    )
    assert rebind.status_code == 200
    assert rebind.json()["rebound_devices"] >= 1

    recovered = client.get("/v1/mobile/handoffs", headers=_mobile_headers(phone))
    assert recovered.status_code == 200
    handoffs = recovered.json()
    assert len(handoffs) == 1
    assert handoffs[0]["query"] == "Silence by Popcaan"
    assert handoffs[0]["launch_url"].startswith("https://www.youtube.com/results?search_query=")


def test_rebind_requires_an_authenticated_local_session() -> None:
    response = client.post(
        "/v1/mobile/devices/rebind",
        headers={
            "X-Nexuss-Session-ID": str(uuid4()),
            "X-Nexuss-Session-Authenticated": "false",
        },
        json={},
    )
    assert response.status_code == 401


def test_handoff_is_still_claimed_only_once() -> None:
    """Freshness must not weaken the existing single-claim guarantee."""
    session_id = uuid4()
    phone = _pair_phone(session_id)
    client.post("/v1/tasks", headers=_desktop_headers(session_id), json=_payload(session_id))

    first = client.get("/v1/mobile/handoffs", headers=_mobile_headers(phone))
    second = client.get("/v1/mobile/handoffs", headers=_mobile_headers(phone))

    assert len(first.json()) == 1
    assert second.json() == []
