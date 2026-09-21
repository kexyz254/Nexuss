from __future__ import annotations

from pathlib import Path


def test_agent_supervisor_ui_contract() -> None:
    html = Path("src/nexuss/ui/index.html").read_text(encoding="utf-8")
    script = Path("src/nexuss/ui/app.js").read_text(encoding="utf-8")
    styles = Path("src/nexuss/ui/styles.css").read_text(encoding="utf-8")

    assert 'id="agent-supervisor-card"' in html
    assert 'id="supervisor-agent-list"' in html
    assert 'id="supervisor-event-list"' in html
    assert '"/v1/supervisor/snapshot?event_limit=8"' in script
    assert "renderSupervisorSnapshot" in script
    assert "SUPERVISOR_REFRESH_MS = 5000" in script
    assert "P6.16A AGENT SUPERVISOR" in styles
    assert ".supervisor-agent-status.busy" in styles


def test_supervisor_ui_preserves_existing_action_control() -> None:
    html = Path("src/nexuss/ui/index.html").read_text(encoding="utf-8")
    supervisor = html.index('id="agent-supervisor-card"')
    tabs = html.index('class="inspector-tabs"')
    assert supervisor < tabs
    assert 'id="action-control-app"' in html
    assert 'id="verification-badge"' in html
