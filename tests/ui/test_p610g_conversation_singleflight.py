from __future__ import annotations

from pathlib import Path

STORE_MARKER = "P6.10G ATOMIC CONVERSATION CREATE OR REBIND"
API_CODE = "CONVERSATION_CONTINUATION_TOKEN_INVALID"


def test_frontend_uses_single_flight_initialization() -> None:
    app = Path("src/nexuss/ui/app.js").read_text(
        encoding="utf-8-sig"
    )

    assert "persistentConversationInitializationKey" in app
    assert "persistentConversationInitializationPromise" in app
    assert "resetPersistentConversationInitialization" in app

    start = app.index("async function ensurePersistentConversation()")
    end = app.index(
        "async function executeConversationTurn(",
        start,
    )
    initializer = app[start:end]

    assert initializer.count('"/v1/conversations"') == 1
    assert "return persistentConversationInitializationPromise" in initializer
    compact = " ".join(initializer.split())
    assert (
        "persistentConversationInitializationPromise "
        "=== initializationPromise"
    ) in compact


def test_new_conversation_invalidates_cached_initialization() -> None:
    app = Path("src/nexuss/ui/app.js").read_text(
        encoding="utf-8-sig"
    )

    start = app.index("function startNewPersistentConversation(options = {})")
    end = app.index(
        "async function ensurePersistentConversation()",
        start,
    )
    new_conversation = app[start:end]

    assert "resetPersistentConversationInitialization();" in new_conversation


def test_backend_atomic_and_security_contracts_are_present() -> None:
    store = Path(
        "src/nexuss/conversation/store.py"
    ).read_text(encoding="utf-8-sig")
    api = Path(
        "src/nexuss/conversation/api.py"
    ).read_text(encoding="utf-8-sig")

    assert STORE_MARKER in store
    assert 'connection.execute("BEGIN IMMEDIATE")' in store
    assert "continuation_token_sha256" in store
    assert "if connection.in_transaction" in store
    assert API_CODE in api
    assert "status.HTTP_403_FORBIDDEN" in api
