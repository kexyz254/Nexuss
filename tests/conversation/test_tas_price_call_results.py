from typing import ClassVar

from nexuss.conversation.trading import handle_trading_chat


class Client:
    calls: ClassVar[list[str]] = []

    def evidence(self, resource):
        self.calls.append(resource)
        return {"resource": resource, "data": {"symbol": "BTC/USDT", "status": "available",
            "horizons": {
                "5m": {"open": 1, "voided": 2, "last_24h": {
                    "hits": 3, "directional": 5, "sample_sufficient": False}},
                "15m": {"open": 0, "voided": 0, "last_24h": {
                    "hits": 0, "directional": 0, "sample_sufficient": False}},
            }}}


def test_authenticated_chat_reads_and_labels_recorded_paper_results():
    Client.calls = []
    reply = handle_trading_chat("Show TAS BTC price call results for 5m and 15m",
                                owner="owner", client_factory=Client)
    assert Client.calls == ["btc_price_results"]
    assert "3/5" in reply.text and "60.0%" in reply.text
    assert "15m" in reply.text and "unavailable" in reply.text
    assert "not realized returns" in reply.text
    assert reply.workflow and not reply.blocked


def test_unauthenticated_user_cannot_read_results():
    Client.calls = []
    reply = handle_trading_chat("Show TAS BTC price call accuracy", client_factory=Client)
    assert "authenticated" in reply.text
    assert Client.calls == []


def test_invalid_outcome_counts_are_not_reported():
    class Invalid(Client):
        def evidence(self, resource):
            result = super().evidence(resource)
            result["data"]["horizons"]["5m"]["last_24h"]["hits"] = 7
            return result
    reply = handle_trading_chat("Show TAS BTC price call results", owner="owner",
                                client_factory=Invalid)
    assert reply.blocked and "could not be verified" in reply.text
