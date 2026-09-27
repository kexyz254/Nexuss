from datetime import datetime, timezone

import httpx
import pytest

from nexuss.conversation.trading import handle_trading_chat
from nexuss.conversation.tas_connection import check_connection


class Client:
    calls = []
    def evidence(self, resource):
        self.calls.append(resource)
        assert resource == "health"
        return {"retrieved_at": datetime.now(timezone.utc).isoformat(),
                "data": {"score": 40, "circuit_breaker_tripped": True, "staleness_seconds": 20}}


def test_exact_reported_request_runs_both_read_checks(monkeypatch):
    import nexuss.conversation.tas_connection as module
    states = []
    def status():
        states.append("read")
        return {"state": "disabled"}
    monkeypatch.setattr(module.managed_tunnel, "status", status)
    Client.calls = []
    result = handle_trading_chat("Check the TAS connection status, then check TAS health. "
        "Report whether the connection is managed and whether live evidence is available. "
        "Do not restart TAS or reset its circuit breaker.", client_factory=Client)
    assert states == ["read"]
    assert Client.calls == ["health"]
    assert result.workflow and not result.blocked
    assert "Live bridge evidence: available" in result.text
    assert "40/100" in result.text
    assert "Managed SSH transport: disabled" in result.text
    assert "Start with" not in result.text


def test_health_read_with_negative_mutation_constraint():
    result = handle_trading_chat("Check TAS health. Don't restart or reset it.", client_factory=Client)
    assert "40/100" in result.text


@pytest.mark.parametrize("utterance", ["Don't check TAS health or reset it.", "Do not check TAS health."])
def test_prohibited_read_is_not_executed(utterance):
    result = handle_trading_chat(utterance,
                                client_factory=lambda: pytest.fail("Read prohibited"))
    assert result.tools_executed == 0


def test_transport_does_not_imply_live_bridge_access():
    def unavailable():
        raise httpx.ConnectError("password=must-not-leak")
    text, calls, blocked = check_connection(unavailable, status_reader=lambda: {"state": "forwarding"})
    assert blocked
    assert calls == 1
    assert "Live bridge evidence: unavailable" in text
    assert "must-not-leak" not in text


def test_connection_only_does_not_probe_health():
    text, calls, blocked = check_connection(lambda: pytest.fail("Health not requested"),
        health=False, status_reader=lambda: {"state": "external_listener"})
    assert "another process" in text
    assert calls == 1 and not blocked
