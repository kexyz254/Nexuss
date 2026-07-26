"""Copyright ? kexyz254peter. Nexuss AI - Confidential and Proprietary."""

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from nexuss.api import app as app_module

client = TestClient(app_module.app)
_REMOTE_HOST = "192.168.50.25"


def _simulate_private_lan(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        app_module,
        "_client_host",
        lambda _request: _REMOTE_HOST,
    )


def test_private_lan_clients_cannot_use_desktop_control_endpoints(
    monkeypatch: MonkeyPatch,
) -> None:
    _simulate_private_lan(monkeypatch)

    assert client.get("/").status_code == 403
    assert client.get("/v1/capabilities").status_code == 403
    assert client.post(
        "/v1/mobile/pairing",
        headers={
            "X-Nexuss-Session-ID": (
                "00000000-0000-0000-0000-000000000799"
            ),
            "X-Nexuss-Session-Authenticated": "true",
        },
    ).status_code == 403


def test_private_lan_clients_can_load_only_mobile_safe_surfaces(
    monkeypatch: MonkeyPatch,
) -> None:
    _simulate_private_lan(monkeypatch)

    assert client.get("/mobile").status_code == 200
    assert client.get("/health/ready").status_code == 200
