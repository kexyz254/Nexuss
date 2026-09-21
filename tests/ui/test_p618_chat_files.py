from pathlib import Path


def test_chat_composer_has_modern_file_attachment_control() -> None:
    html = Path("src/nexuss/ui/index.html").read_text(encoding="utf-8")
    script = Path("src/nexuss/ui/file_workspace.js").read_text(encoding="utf-8")
    styles = Path("src/nexuss/ui/file_workspace.css").read_text(encoding="utf-8")

    assert 'id="file-attach-button"' in html
    assert 'id="file-input"' in html
    assert 'id="file-attachment-tray"' in html
    assert ">+</button>" in html
    assert "/attachments" in script
    assert "/artifacts/package" in script
    assert "attachment_ids" in script
    assert ".message-artifact-card" in styles


def test_chat_file_outputs_render_downloadable_artifacts() -> None:
    script = Path("src/nexuss/ui/app.js").read_text(encoding="utf-8")
    assert 'className = "message-artifact-card"' in script
    assert "/v1/artifacts/" in script
    assert "response.blob()" in script
