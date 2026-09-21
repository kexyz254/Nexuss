from pathlib import Path


def test_desktop_left_rail_reserves_chat_history_space() -> None:
    css = Path("src/nexuss/ui/styles.css").read_text(encoding="utf-8")
    html = Path("src/nexuss/ui/index.html").read_text(encoding="utf-8")

    assert "/* P6.22 LEFT-RAIL BALANCE */" in css
    assert "minmax(190px, 38vh)" in css
    assert ".chat-list" in css
    assert "overflow-y: auto;" in css
    assert ".nav-list" in css
    assert "P6.22" in html
    assert "?v=p622" in html


def test_missing_progress_registration_cannot_poll_forever() -> None:
    script = Path("src/nexuss/ui/app.js").read_text(encoding="utf-8")

    assert "let notFoundCount = 0;" in script
    assert "response.status === 404" in script
    assert "notFoundCount >= 6" in script
    assert "panel.remove();" in script
    assert "stopProgress(completedInteraction);" in script
    assert "setTimeout(poll, 150)" in script
