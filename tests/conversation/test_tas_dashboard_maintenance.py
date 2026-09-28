from typing import ClassVar

import pytest

from nexuss.connectors.trading import TradingClient
from nexuss.conversation.trading import handle_trading_chat


class Client:
    calls: ClassVar[list[str]] = []

    def maintenance(self, operation):
        self.calls.append(operation)
        return {"request_id": "a" * 32, "operation": operation,
                "status": "restarted_verified" if operation == "restart_dashboard" else "healthy",
                "verified": True, "replayed": False}


def test_explicit_dashboard_recovery_uses_fixed_operation():
    Client.calls = []
    reply = handle_trading_chat("Please restore TAS dashboard", owner="owner",
                                client_factory=Client)
    assert Client.calls == ["restart_dashboard"]
    assert "readiness passed" in reply.text
    assert reply.workflow and not reply.blocked


def test_diagnostics_do_not_restart():
    Client.calls = []
    reply = handle_trading_chat("Diagnose ATS dashboard", owner="owner", client_factory=Client)
    assert Client.calls == ["diagnostics"]
    assert "No restart" in reply.text


def test_prohibition_and_engine_boundary():
    Client.calls = []
    handle_trading_chat("Check TAS dashboard; do not restart it", owner="owner",
                        client_factory=Client)
    handle_trading_chat("Restart TAS engine and dashboard", owner="owner",
                        client_factory=Client)
    assert Client.calls == []


def test_client_rejects_unknown_operations():
    client = TradingClient("http://127.0.0.1:8300", b"a" * 32)
    with pytest.raises(ValueError):
        client.maintenance("restart_engine")
