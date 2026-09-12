from __future__ import annotations

from pathlib import Path


MARKER = "P6.10F PROFESSIONAL MULTITASKING WORKSPACE"


def test_professional_workspace_assets_are_installed() -> None:
    index = Path("src/nexuss/ui/index.html").read_text(
        encoding="utf-8-sig"
    )
    javascript = Path(
        "src/nexuss/ui/nexuss_ui_platform.js"
    ).read_text(encoding="utf-8-sig")
    stylesheet = Path(
        "src/nexuss/ui/nexuss_ui_platform.css"
    ).read_text(encoding="utf-8-sig")

    assert "nexuss_ui_platform.css?v=1.0.0" in index
    assert "nexuss_ui_platform.js?v=1.0.0" in index
    assert MARKER in javascript
    assert MARKER in stylesheet


def test_workspace_contract_covers_required_surfaces() -> None:
    javascript = Path(
        "src/nexuss/ui/nexuss_ui_platform.js"
    ).read_text(encoding="utf-8-sig")

    required = (
        "installApprovalHardening",
        "enhanceActivity",
        "showCommandPalette",
        "renderApprovalCenter",
        "renderReceiptCenter",
        "renderNotifications",
        "runDiagnostics",
        "nexuss.ui.platform.layout.v1",
        "NexussProfessionalWorkspace",
        "Approval Center",
        "Receipt Center",
        "Diagnostics Center",
    )
    for token in required:
        assert token in javascript


def test_local_layout_storage_excludes_sensitive_payloads() -> None:
    javascript = Path(
        "src/nexuss/ui/nexuss_ui_platform.js"
    ).read_text(encoding="utf-8-sig")

    write_start = javascript.index("function writeLayout()")
    write_end = javascript.index("function writeSettings()")
    layout_writer = javascript[write_start:write_end]

    assert "approval_token" not in layout_writer
    assert "payload_sha256" not in layout_writer
    assert "receipt_id" not in layout_writer
    assert "api_key" not in layout_writer.lower()
    assert "message" not in layout_writer.lower()
    assert "left" in layout_writer
    assert "top" in layout_writer
    assert "width" in layout_writer
    assert "height" in layout_writer
    assert "mode" in layout_writer


def test_approval_overlay_has_high_authority_z_index() -> None:
    stylesheet = Path(
        "src/nexuss/ui/nexuss_ui_platform.css"
    ).read_text(encoding="utf-8-sig")

    assert ".approval-overlay" in stylesheet
    assert "--nx-approval-z" in stylesheet
    assert "10000" in Path(
        "src/nexuss/ui/nexuss_ui_platform.js"
    ).read_text(encoding="utf-8-sig")


def test_responsive_and_accessible_contracts_are_present() -> None:
    javascript = Path(
        "src/nexuss/ui/nexuss_ui_platform.js"
    ).read_text(encoding="utf-8-sig")
    stylesheet = Path(
        "src/nexuss/ui/nexuss_ui_platform.css"
    ).read_text(encoding="utf-8-sig")

    assert 'aria-label' in javascript
    assert 'role", "dialog' in javascript
    assert "Ctrl+K" in javascript
    assert "@media (max-width: 760px)" in stylesheet
    assert "prefers-reduced-motion" in stylesheet
    assert "focus-visible" in stylesheet
