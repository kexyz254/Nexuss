"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary."""

from nexuss.api.app import health_live, health_ready


def test_health_live() -> None:
    assert health_live() == {
        "status": "alive",
        "service": "nexuss-core-api",
        "version": "0.2.0",
    }


def test_health_ready() -> None:
    assert health_ready() == {"status": "ready", "mode": "p2_ui_local_readonly"}
