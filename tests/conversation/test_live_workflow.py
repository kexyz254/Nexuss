from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from nexuss.conversation.trading import TradingReply, handle_trading_chat
from nexuss.interactions.progress import ProgressHub, emit, reporting, recording


def test_information_question_does_not_call_tas():
    reply = handle_trading_chat("Explain TAS's circuit breaker", client_factory=lambda: pytest.fail("Unexpected read"))
    assert "explanation" in reply.text
    assert reply.workflow is False


def test_progress_owner_capacity_and_context_cleanup():
    hub = ProgressHub(capacity=1)
    hub.start("request", "owner", "conversation")
    with pytest.raises(RuntimeError):
        hub.start("request", "owner", "conversation")
    with pytest.raises(PermissionError):
        hub.start("request", "other", "conversation")
    with pytest.raises(LookupError):
        hub.get("request", "other")
    captured = []
    with reporting(lambda *args: hub.append("request", *args)), recording(lambda *args: captured.append(args)):
        emit("workflow_step", "running", "Reading health")
    emit("workflow_step", "running", "Outside request")
    assert len(captured) == 1
    assert len(hub.get("request", "owner")["events"]) == 1
    hub.finish("request", "blocked")
    hub.start("next", "owner", "conversation")
    with pytest.raises(LookupError):
        hub.get("request", "owner")


def test_authenticated_progress_is_visible_before_post_finishes(tmp_path, monkeypatch):
    import nexuss.interactions.api as api
    import nexuss.interactions.service as runtime
    from nexuss.conversation.store import SQLiteConversationStore
    from nexuss.interactions.store import SQLiteInteractionStore
    conversations = SQLiteConversationStore(tmp_path / "chat.db")
    interactions = SQLiteInteractionStore(tmp_path / "interactions.db")
    owner, cid, rid = uuid4(), uuid4(), uuid4()
    conversations.create(conversation_id=cid, user_session_id=owner, title="Investigation",
        provider_id="deepseek", model="test", continuation_token="x" * 64)
    monkeypatch.setattr(api, "SQLiteConversationStore", lambda: conversations)
    monkeypatch.setattr(api, "SQLiteInteractionStore", lambda: interactions)
    monkeypatch.setattr(api, "AIProviderConnectionResolver", lambda: None)
    started, release = Event(), Event()
    def investigate(text, **kwargs):
        emit("workflow_plan", "planned", "Read health, then inspect incident evidence")
        emit("workflow_step", "running", "Maintenance: reading health")
        started.set()
        assert release.wait(5), "Test did not release workflow"
        emit("workflow_step", "blocked", "Bridge unreachable")
        return TradingReply("Restore the bridge connection before retrying.", workflow=True, blocked=True)
    monkeypatch.setattr(runtime, "handle_trading_chat", investigate)
    app = FastAPI()
    api.register_interaction_routes(app, require_local_control=lambda request: None, core_service=None)
    headers = {"X-Nexuss-Session-ID": str(owner), "X-Nexuss-Session-Authenticated": "true"}
    body = {"request_id": str(rid), "conversation_id": str(cid), "user_session_id": str(owner), "text": "Investigate TAS"}
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, "/v1/interactions", json=body, headers=headers)
        try:
            assert started.wait(3)
            live = client.get(f"/v1/interactions/progress/{rid}", headers=headers)
            assert live.status_code == 200
            assert live.json()["state"] == "running"
            assert any(event["detail"] == "Maintenance: reading health" for event in live.json()["events"])
            stranger = {**headers, "X-Nexuss-Session-ID": str(uuid4())}
            assert client.get(f"/v1/interactions/progress/{rid}", headers=stranger).status_code == 404
            assert client.post("/v1/interactions", json=body, headers=headers).status_code == 409
        finally:
            release.set()
        response = future.result(timeout=5)
        assert response.status_code == 200, response.text
        final = response.json()
        assert final["kind"] == "workflow"
        assert final["state"] == "blocked"
        assert any(event["event_type"] == "workflow_step" for event in final["events"])
        assert client.get(f"/v1/interactions/progress/{rid}", headers=headers).json()["state"] == "blocked"
        cached = client.post("/v1/interactions", json=body, headers=headers)
        assert cached.json() == final
        assert len(conversations.messages(cid)) == 2
