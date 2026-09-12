from __future__ import annotations

from pathlib import Path


def test_authoritative_media_and_approval_bridge_migration_is_complete() -> None:
    """P6.10C is superseded by P6.10D and P6.11, not silently restored."""
    text = Path("src/nexuss/ui/app.js").read_text(encoding="utf-8")

    assert "P6.10C MEDIA AND APPROVAL PRESENTATION BRIDGE" not in text
    assert "P6.10D AUTHORITATIVE PRESENTATION SYNCHRONIZER" in text
    assert "P6.11 REMOVED OBSOLETE P6.10C PRESENTATION BRIDGE" in text
    assert "async function p610DPresentCoreTask" in text
    assert "renderTask(task, receipt)" in text
    assert "await showApproval(task.approval)" in text
    assert "Nexuss is not claiming playback." in text
    assert "isP610DLocalMediaCommand" in text
