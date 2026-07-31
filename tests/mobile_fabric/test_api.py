"""P6.7A API surface tests."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexuss.mobile.gateway import MobileApprovalGateway
from nexuss.mobile_fabric.api import register_mobile_fabric_routes
from nexuss.mobile_fabric.assertion import AssertionInput, DeviceAssertionVerifier


def _canonical(value: dict[str, object]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _paired() -> tuple[MobileApprovalGateway, str, str, str]:
    session_id = uuid4()
    gateway = MobileApprovalGateway()
    challenge = gateway.create_pairing(session_id)
    device = gateway.pair(challenge.pairing_code, "Pixel trusted")
    return gateway, str(session_id), str(device.device_id), device.device_token


def _mobile_headers(
    *,
    token: str,
    device_id: str,
    method: str,
    path: str,
    body: bytes,
) -> dict[str, str]:
    timestamp = datetime.now(UTC)
    nonce = secrets.token_hex(24)
    body_hash = hashlib.sha256(body).hexdigest()
    assertion = AssertionInput(
        method=method,
        path=path,
        timestamp=timestamp,
        nonce=nonce,
        body_sha256=body_hash,
    )
    signature = DeviceAssertionVerifier.sign(token, assertion)
    return {
        "X-Nexuss-Mobile-Device-ID": device_id,
        "X-Nexuss-Mobile-Token": token,
        "X-Nexuss-Mobile-Timestamp": timestamp.isoformat(),
        "X-Nexuss-Mobile-Nonce": nonce,
        "X-Nexuss-Mobile-Body-SHA256": body_hash,
        "X-Nexuss-Mobile-Assertion": signature,
    }


def test_authenticated_mobile_signal_ingress_and_local_read() -> None:
    gateway, session_id, device_id, token = _paired()
    app = FastAPI()
    register_mobile_fabric_routes(
        app,
        lambda request: None,
        mobile_gateway=gateway,
    )
    client = TestClient(app)
    payload = {
        "batch_id": str(uuid4()),
        "sequence": 1,
        "device_time": datetime.now(UTC).isoformat(),
        "batch_nonce": "n" * 32,
        "signals": [
            {
                "event_id": str(uuid4()),
                "source": "instagram",
                "package_name": "com.instagram.android",
                "kind": "message_received",
                "occurred_at": datetime.now(UTC).isoformat(),
                "sender_label": "Client",
                "conversation_label": "Client",
                "text": "Can you confirm tomorrow's meeting?",
                "notification_key": "instagram:1",
                "reply_supported": True,
                "sensitive": False,
                "metadata": {},
                "content_sha256": None,
            }
        ],
    }
    canonical = _canonical(payload)
    response = client.post(
        "/v1/mobile-fabric/signals",
        content=canonical,
        headers={
            **_mobile_headers(
                token=token,
                device_id=device_id,
                method="POST",
                path="/v1/mobile-fabric/signals",
                body=canonical,
            ),
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 200
    assert response.json()["accepted"] == 1

    feed = client.get(
        "/v1/mobile-fabric/feed",
        headers={
            "X-Nexuss-Session-ID": session_id,
            "X-Nexuss-Session-Authenticated": "true",
        },
    )
    assert feed.status_code == 200
    assert feed.json()["items"][0]["signal"]["source"] == "instagram"
    assert feed.json()["external_write_performed"] is False
