"""P6.7A installed-worktree integration contract."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("NEXUSS_P67A_PRODUCTION_TEST") != "1",
    reason="Runs only against an installed Nexuss worktree.",
)


def test_mobile_fabric_routes_registry_runtime_and_companion_are_installed() -> None:
    root = Path.cwd()
    app = (root / "src/nexuss/api/app.py").read_text(encoding="utf-8-sig")
    registry = (root / "src/nexuss/core/registry.py").read_text(
        encoding="utf-8-sig"
    )
    start_script = (root / "scripts/start_p5.ps1").read_text(
        encoding="utf-8-sig"
    )
    manifest = (
        root
        / "apps/android-companion-native/app/src/main/AndroidManifest.xml"
    ).read_text(encoding="utf-8-sig")

    assert "register_mobile_fabric_routes(" in app
    assert '"mode": "p67a_trusted_mobile_communication_fabric"' in app
    assert "mobile.signals.ingest" in registry
    assert "mobile.signals.read" in registry
    assert "mobile.action.prepare" in registry
    assert "mobile.action.execute" in registry
    assert "p67a_trusted_mobile_communication_fabric" in start_script
    assert "BIND_NOTIFICATION_LISTENER_SERVICE" in manifest
    assert "AccessibilityService" not in manifest
