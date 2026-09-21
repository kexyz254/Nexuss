from pathlib import Path


def test_development_package_attachment_route_exists():
    source = (Path(__file__).resolve().parents[2] / "src" / "nexuss" / "ui" / "app.js").read_text(encoding="utf-8")
    assert "executeDevelopmentPackageInstruction" in source
    assert 'fetch("/v1/development-packages"' in source
    assert "isDevelopmentPackageInstruction" in source
    assert "No LLM/API call is required" in source
    # All approved actions now share the awaited lifecycle follower.
    assert "await followCoreTaskLifecycle({ core_task_id: taskId }" in source
    assert "if (String(followedChatTaskId) !== String(taskId))" in source
