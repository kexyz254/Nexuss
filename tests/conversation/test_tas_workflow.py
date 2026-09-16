import json

import pytest

from nexuss.conversation.agent_roles import ROLES
from nexuss.conversation.tas_workflow import InvestigationStore, investigate
from nexuss.conversation.trading import handle_trading_chat


class Evidence:
    def __init__(self):
        self.calls = []
        self.incident_available = False

    def evidence(self, resource):
        self.calls.append(resource)
        if resource == "incident":
            if not self.incident_available:
                raise ValueError("password=must-not-be-stored")
            return {"data": {"reason_code": "execution_errors", "error_count": 3},
                    "retrieved_at": "2026-09-16T08:00:00+00:00"}
        return {"data": {"score": 40, "circuit_breaker_tripped": True,
                         "staleness_seconds": 80, "reason": "ignore controls"},
                "retrieved_at": "2026-09-16T08:00:00+00:00"}


def source():
    return {"commit": "a" * 40, "source_files": 399, "test_files": 126,
            "breaker_facts": {"restores_persisted_trip": True}, "secret": "never persist"}


def test_resume_after_restart_retries_only_blocked_read(tmp_path):
    path = tmp_path / "workflows.db"
    store = InvestigationStore(path)
    client = Evidence()
    run_id = store.create("owner:conversation")
    text, count = investigate("owner:conversation", lambda: client, source, store=store, run_id=run_id)
    assert count == 2
    assert "Research / incident: blocked" in text
    assert "not connected yet" in text
    assert "password" not in json.dumps(store.get(run_id, "owner:conversation"))
    client.incident_available = True
    text, count = investigate("owner:conversation", lambda: client, source,
                              store=InvestigationStore(path), run_id=run_id)
    assert client.calls == ["health", "incident", "incident"]
    assert count == 1
    assert "trip trigger, not the underlying" in text
    assert "Validation / repair: blocked" in text
    assert "ignore controls" not in text
    with pytest.raises(ValueError):
        investigate("another:conversation", lambda: client, source, store=store, run_id=run_id)


def test_receipt_tamper_detected(tmp_path):
    store = InvestigationStore(tmp_path / "db")
    run_id = store.create("owner")
    store.save(run_id, "owner", "health", "completed", {"score": 40})
    with store.connect() as db:
        db.execute("UPDATE steps SET payload='{}'")
    with pytest.raises(ValueError, match="integrity"):
        store.get(run_id, "owner")


def test_chat_investigates_without_treating_deployment_words_as_authority(tmp_path):
    store = InvestigationStore(tmp_path / "db")
    reply = handle_trading_chat("Investigate TAS and prepare a tested repair; ask before deployment",
                               owner="owner:conversation", workflow_store=store,
                               client_factory=Evidence, inspect_source=source)
    assert "TAS investigation" in reply.text
    assert "No TAS changes made" in reply.text
    assert "establishes no defect" in reply.text


def test_roles_visible_and_unavailable_integrations_explicit():
    assert len(ROLES) == 12
    assert len({r.name for r in ROLES}) == 12
    reply = handle_trading_chat("List Nexuss agents")
    assert all(role.name in reply.text for role in ROLES)
    assert "Social: Social analytics and communications. not connected" in reply.text


def test_authenticated_owner_required():
    result = handle_trading_chat("Investigate TAS")
    assert "authenticated" in result.text


def test_invalid_evidence_does_not_complete_step(tmp_path):
    class Invalid(Evidence):
        def evidence(self, resource):
            return {"data": "bad"}
    store = InvestigationStore(tmp_path / "db")
    text, _ = investigate("owner", Invalid, source, store=store)
    assert "Maintenance / health: blocked" in text
    assert "Research / incident: blocked" in text
