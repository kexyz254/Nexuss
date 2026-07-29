from __future__ import annotations

from pathlib import Path


def test_workspace_routes_registered_in_app_source() -> None:
    root = Path(__file__).resolve().parents[2]
    app_source = (root / "src/nexuss/api/app.py").read_text(encoding="utf-8")

    assert "register_github_workspace_routes" in app_source
    assert "/v1/github-workspace" in (
        root / "src/nexuss/connectors/github/workspace_api.py"
    ).read_text(encoding="utf-8")


def test_modification_and_webhook_activation_remain_disabled() -> None:
    root = Path(__file__).resolve().parents[2]
    change_source = (
        root / "src/nexuss/connectors/github/change_manager.py"
    ).read_text(encoding="utf-8")
    webhook_source = (
        root / "src/nexuss/connectors/github/webhook_receiver.py"
    ).read_text(encoding="utf-8")

    assert "GitHubModificationDisabled" in change_source
    assert "enabled = False" in webhook_source
    assert "webhook_route_registered\": False" in webhook_source
