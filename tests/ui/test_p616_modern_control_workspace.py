from __future__ import annotations

from pathlib import Path


def test_modern_workspace_has_25_75_structure() -> None:
    html = Path("src/nexuss/ui/index.html").read_text(
        encoding="utf-8"
    )
    css = Path("src/nexuss/ui/styles.css").read_text(
        encoding="utf-8"
    )

    assert 'class="action-workspace"' in html
    assert 'id="conversation-app"' in html
    assert 'id="action-control-app"' in html

    assert "P6.16 MODERN 25/75 CONTROL WORKSPACE" in css
    assert "minmax(260px, 25vw)" in css
    assert "grid-template-columns:" in css
    assert ".action-workspace" in css
    assert ".navigation" in css


def test_chat_and_action_control_remain_inside_action_workspace() -> None:
    html = Path("src/nexuss/ui/index.html").read_text(
        encoding="utf-8"
    )

    workspace = html.index('class="action-workspace"')
    conversation = html.index('id="conversation-app"')
    inspector = html.index('id="action-control-app"')
    shell_end = html.index("</main>")

    assert workspace < conversation < inspector < shell_end


def test_existing_multi_chat_contract_remains_intact() -> None:
    html = Path("src/nexuss/ui/index.html").read_text(
        encoding="utf-8"
    )

    assert 'id="new-chat-button"' in html
    assert 'id="chat-list"' in html
    assert 'id="conversation-title"' in html
