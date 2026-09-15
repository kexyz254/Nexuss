from __future__ import annotations

from pathlib import Path


def test_multi_chat_controls_are_present() -> None:
    html = Path(
        "src/nexuss/ui/index.html"
    ).read_text(encoding="utf-8")

    script = Path(
        "src/nexuss/ui/app.js"
    ).read_text(encoding="utf-8")

    styles = Path(
        "src/nexuss/ui/styles.css"
    ).read_text(encoding="utf-8")

    assert 'id="new-chat-button"' in html
    assert 'id="chat-list"' in html
    assert 'id="conversation-title"' in html

    assert "selectPersistentConversation" in script
    assert "renamePersistentConversation" in script
    assert "deletePersistentConversation" in script
    assert 'method: "PATCH"' in script
    assert 'method: "DELETE"' in script

    assert (
        "startNewPersistentConversation({"
        in script
    )

    assert ".chat-list-row.is-active" in styles


def test_chat_layer_uses_server_conversation_index() -> None:
    script = Path(
        "src/nexuss/ui/app.js"
    ).read_text(encoding="utf-8")

    api = Path(
        "src/nexuss/conversation/api.py"
    ).read_text(encoding="utf-8")

    assert '"/v1/conversations"' in script
    assert '@app.get("/v1/conversations")' in api
    assert "@app.patch(" in api
    assert "@app.delete(" in api
