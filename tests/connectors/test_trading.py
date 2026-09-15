import hashlib
import hmac
import json

import httpx
import pytest

from nexuss.connectors.trading import TradingClient

SECRET = b"test-only-bridge-key-do-not-use-live-12345"


def test_signed_evidence_and_feedback():
    seen = []
    def respond(request):
        target = request.url.raw_path.decode()
        digest = hashlib.sha256(request.content).hexdigest()
        message = (f"v1\n{request.method}\n{target}\n{request.headers['x-nexuss-time']}\n"
                   f"{request.headers['x-nexuss-nonce']}\n{digest}").encode()
        assert request.headers['x-nexuss-signature'] == hmac.new(SECRET, message, hashlib.sha256).hexdigest()
        seen.append(target)
        return httpx.Response(200, json={"ok": True})
    client = TradingClient("http://100.93.64.23:8300", SECRET, httpx.MockTransport(respond))
    assert client.evidence("decisions", "BTC/USDT") == {"ok": True}
    assert seen == ["/agent/v1/evidence/decisions?symbol=BTC%2FUSDT"]
    assert client.request("POST", "/agent/v1/feedback", {"execution_requested": False})["ok"]


@pytest.mark.parametrize("url", ["http://example.com", "https://user:password@example.com",
                                  "https://example.com/?token=x", "file:///etc/passwd"])
def test_unsafe_origins_rejected(url):
    with pytest.raises(ValueError):
        TradingClient(url, SECRET)


def test_no_execution_transport():
    client = TradingClient("http://127.0.0.1:8300", SECRET)
    with pytest.raises(ValueError):
        client.request("POST", "/agent/v1/execute", {})
    with pytest.raises(ValueError):
        client.evidence("shell")


def test_observation_cursor_is_signed_and_validated():
    def respond(request):
        assert request.url.raw_path == b"/agent/v1/observations?after=7&limit=20"
        assert request.headers["x-nexuss-signature"]
        return httpx.Response(200, json={"events": [], "next_cursor": 7})
    client = TradingClient("http://127.0.0.1:8300", SECRET, httpx.MockTransport(respond))
    assert client.observations(7, 20)["next_cursor"] == 7
    with pytest.raises(ValueError):
        client.observations(-1)
    with pytest.raises(ValueError):
        client.observations(0, 101)
