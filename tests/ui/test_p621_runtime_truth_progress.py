from pathlib import Path


def test_ui_exposes_exact_running_build_identity() -> None:
    html = Path("src/nexuss/ui/index.html").read_text(encoding="utf-8")
    script = Path("src/nexuss/ui/app.js").read_text(encoding="utf-8")

    assert 'id="runtime-build-chip"' in html
    assert 'id="runtime-build-sha"' in html
    assert "?v=p621" in html
    assert "async function refreshRuntimeBuildIdentity()" in script
    assert 'fetch("/v1/runtime/build"' in script
    assert "· CURRENT" in script
    assert "· STALE" in script


def test_chat_task_panel_consumes_real_engineering_telemetry() -> None:
    script = Path("src/nexuss/ui/app.js").read_text(encoding="utf-8")

    assert "/v1/tasks/" in script and "/status" in script
    assert "/v1/engineering/prompt-build/progress" in script
    assert "engineering.core_task_id" in script
    assert "engineering.changed_file_count" in script
    assert "engineering.events" in script
    assert "round \${round}" in script
    assert "workflow-progress-meter" in script
    assert "setTimeout(resolve, 750)" in script
