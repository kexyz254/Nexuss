from __future__ import annotations

from pathlib import Path


def test_system_centers_default_hidden_and_layout_migrates_safely() -> None:
    source = Path(
        "src/nexuss/ui/nexuss_ui_platform.js"
    ).read_text(encoding="utf-8-sig")

    assert 'nexuss.ui.platform.layout.v2' in source
    assert 'nexuss.ui.platform.layout.v1' in source
    assert 'initialMode = "hidden"' in source
    assert "legacy.activity ? { activity: legacy.activity }" in source


def test_existing_topbar_status_is_reused() -> None:
    source = Path(
        "src/nexuss/ui/nexuss_ui_platform.js"
    ).read_text(encoding="utf-8-sig")
    bridge = source[source.index("function installStatusBridge()") :]
    bridge = bridge[: bridge.index("function handleResize()")]

    assert 'document.getElementById("system-state-label")' in bridge
    assert "existingState.dataset.nxProfessionalWorkspace" in bridge
    assert bridge.index("if (existingState)") < bridge.index(
        'document.createElement("div")'
    )
