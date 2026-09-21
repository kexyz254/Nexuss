import pytest

from nexuss.connectors.trading_events import TradingEventStore, plan_repairs


def test_ingestion_is_durable_idempotent_and_advances_cursor(tmp_path):
    store = TradingEventStore(tmp_path / "tas.sqlite3")
    events = [
        {"id": "h-1", "cursor": 1, "kind": "health.transition", "breaker": True},
        {"id": "d-1", "cursor": 2, "kind": "decision", "symbol": "BTC/USDT"},
    ]
    assert store.ingest_page(events, 2) == 2
    assert store.cursor() == 2
    assert store.ingest_page(events, 2) == 0
    assert len(store.recent()) == 2
    reopened = TradingEventStore(tmp_path / "tas.sqlite3")
    assert reopened.cursor() == 2


def test_cursor_cannot_regress(tmp_path):
    store = TradingEventStore(tmp_path / "tas.sqlite3")
    store.ingest_page([], 7)
    with pytest.raises(ValueError):
        store.ingest_page([], 6)


def test_invalid_event_does_not_advance_cursor(tmp_path):
    store = TradingEventStore(tmp_path / "tas.sqlite3")
    with pytest.raises(ValueError):
        store.ingest_page([{"id": "bad", "cursor": 9}], 2)
    assert store.cursor() == 0
    assert store.recent() == []


def test_repair_planner_is_proposal_only():
    proposals = plan_repairs(
        {"breaker": True, "reasons": ["circuit breaker tripped"], "recent_error_rate": 0.4},
        {"stale": True, "backlog_full": True},
    )
    actions = {item.action for item in proposals}
    assert actions == {
        "drain_observation_backlog",
        "restart_observer_worker",
        "diagnose_circuit_breaker",
        "investigate_error_rate",
    }
    assert all(item.approval_required for item in proposals)
    assert not ({"execute_trade", "reset_breaker", "shell", "deploy"} & actions)
