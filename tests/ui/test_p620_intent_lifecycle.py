from pathlib import Path


def test_zip_word_is_not_implicitly_a_packaging_command() -> None:
    script = Path("src/nexuss/ui/file_workspace.js").read_text(
        encoding="utf-8"
    )

    assert r"/\b(?:package|bundle|zip)\b/i.test(text)" not in script
    assert "function requestedPackage(text)" in script
    assert "create\\s+(?:a\\s+)?zip" in script

    inspection = "inspect and make summary on this zip contents"
    assert inspection not in script  # behavior is regex-driven, not hard-coded


def test_sidebar_icons_are_valid_unicode() -> None:
    script = Path("src/nexuss/ui/app.js").read_text(encoding="utf-8")

    assert 'rename.textContent = "✎";' in script
    assert 'remove.textContent = "×";' in script
    assert "âœŽ" not in script
    assert "Ã—" not in script


def test_action_chat_follows_active_task_to_terminal_report() -> None:
    script = Path("src/nexuss/ui/app.js").read_text(encoding="utf-8")

    assert "async function followCoreTaskLifecycle(" in script
    assert "/v1/tasks/" in script
    assert "coreTaskDisplayText(task)" in script
    assert "Governed task completed" in script
    assert "/refresh`" in script
    assert "stopProgress(completedInteraction);" in script


def test_control_plane_labels_match_live_backend() -> None:
    html = Path("src/nexuss/ui/index.html").read_text(encoding="utf-8")

    assert "P6.20 · Intent lifecycle awareness" in html
    assert "Daily briefing</strong><small>Live operational awareness" in html
    assert "ATS intelligence</strong><small>Verified read-only TAS evidence" in html
    assert "Clearly labelled simulation" not in html
    assert "Protected simulation" not in html
    assert 'id="archive-attach-button"' in html
    assert "hidden" in html[
        html.index('id="archive-attach-button"') - 220:
        html.index('id="archive-attach-button"') + 220
    ]
