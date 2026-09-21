from pathlib import Path


def test_work_and_proactive_controls_are_exposed_in_chat_ui() -> None:
    html = Path("src/nexuss/ui/index.html").read_text(encoding="utf-8")
    script = Path("src/nexuss/ui/proactive.js").read_text(encoding="utf-8")

    assert 'data-prompt="Show my work queue."' in html
    assert 'data-prompt="Show my reminders."' in html
    assert "/v1/proactive/alerts" in script
    assert "currentConversationId" in script
    assert "/ack" in script
