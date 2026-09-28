from datetime import UTC, datetime

from nexuss.conversation.tas_account_audit import normalize_account_flow
from nexuss.conversation.tas_workflow import InvestigationStore
from nexuss.conversation.trading import handle_trading_chat


def envelope():
    return {"resource": "account_flow", "trust": "external_evidence_not_instructions",
            "retrieved_at": datetime.now(UTC).isoformat(),
            "data": {"status": "recorded", "incident_at": "2026-09-07T12:02:09+00:00",
                     "window_hours": 72, "minimum_movement": 0.1,
                     "highest_snapshot_at": "2026-09-05T21:46:58+00:00",
                     "highest_snapshot_equity": 200.0,
                     "after_incident_at": "2026-09-07T12:03:00+00:00",
                     "after_incident_equity": 140.0,
                     "last_live_equity_at": "2026-09-28T06:00:00+00:00",
                     "last_live_equity": 145.0,
                     "movement_count": 2, "movement_sum": -60.0,
                     "classified_external_sum": -40.0, "unclassified_sum": -20.0,
                     "trade_count": 0, "audited_realized_pnl": 0.0,
                     "truncated": False,
                     "movements": [
                         {"at": "2026-09-06T07:00:00+00:00", "raw_delta": -40.0,
                          "trading_delta": 0.0, "unexplained_delta": -40.0,
                          "classified_external": True, "reason": "password=private"},
                         {"at": "2026-09-07T12:02:00+00:00", "raw_delta": -20.0,
                          "trading_delta": 0.0, "unexplained_delta": -20.0,
                          "classified_external": False, "api_key": "private"},
                     ], "private_key": "must-not-persist"}}


class Client:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def evidence(self, resource):
        self.calls.append(resource)
        return self.payload


def test_chat_account_audit_uses_shared_receipt_without_leaking_or_resetting(tmp_path):
    store = InvestigationStore(tmp_path / "db")
    run_id = store.create("owner")
    store.save(run_id, "owner", "Research / incident", "completed",
               {"event_at": "2026-09-07T12:02:09+00:00", "reason_code": "max_drawdown"})
    client = Client(envelope())
    reply = handle_trading_chat("Audit TAS account flows; do not reset",
                                owner="owner", workflow_store=store,
                                client_factory=lambda: client)
    assert reply.workflow and not reply.blocked
    assert client.calls == ["account_flow"]
    assert "Movement totals numerically match" in reply.text
    assert "unclassified: -20.00" in reply.text
    assert "operator attribution" in reply.text
    assert "password" not in reply.text and "private" not in reply.text
    saved = store.get(run_id, "owner")["Financial / capital movements"]["data"]
    assert saved["movement_count"] == 2 and "private" not in str(saved)
    assert store.latest("owner") == run_id


def test_account_evidence_rejects_inconsistent_or_stale_payload():
    payload = envelope()
    payload["data"]["unclassified_sum"] = float("nan")
    try:
        normalize_account_flow(payload)
    except ValueError:
        pass
    else:
        raise AssertionError("NaN must not enter an investigation receipt")
    payload = envelope()
    payload["retrieved_at"] = "2026-09-07T12:00:00+00:00"
    try:
        normalize_account_flow(payload)
    except ValueError:
        pass
    else:
        raise AssertionError("Stale evidence must not be presented as live")


def test_account_audit_cannot_combine_with_mutation_request(tmp_path):
    client = Client(envelope())
    reply = handle_trading_chat("Audit TAS balance and reset breaker", owner="owner",
                                workflow_store=InvestigationStore(tmp_path / "db"),
                                client_factory=lambda: client)
    assert "read-only" in reply.text
    assert client.calls == []
