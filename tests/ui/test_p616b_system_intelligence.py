from __future__ import annotations

from pathlib import Path


def test_system_intelligence_and_update_controls_are_visible() -> None:
    html = Path("src/nexuss/ui/index.html").read_text(encoding="utf-8")
    assert 'data-prompt="Run system diagnostics."' in html
    assert 'data-prompt="Check for Nexuss updates."' in html
    assert "System intelligence" in html
    assert "Nexuss updates" in html
    assert "GitHub ↔ trusted local control" in html


def test_modern_multi_chat_contract_remains_present() -> None:
    html = Path("src/nexuss/ui/index.html").read_text(encoding="utf-8")
    assert 'id="new-chat-button"' in html
    assert 'id="chat-list"' in html
    assert 'id="conversation-title"' in html
    assert 'id="agent-supervisor-card"' in html
