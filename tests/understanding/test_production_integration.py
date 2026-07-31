"""Copyright © kexyz254peter.
Nexuss AI - Confidential and Proprietary.
Unauthorized copying, redistribution or disclosure is prohibited.

Post-install production integration contract.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("NEXUSS_P66B_PRODUCTION_TEST") != "1",
    reason="Runs only against an installed Nexuss worktree.",
)


def test_understanding_routes_and_ui_are_registered() -> None:
    root = Path.cwd()
    app = (root / "src/nexuss/api/app.py").read_text(encoding="utf-8-sig")
    ui = (root / "src/nexuss/ui/app.js").read_text(encoding="utf-8-sig")
    styles = (root / "src/nexuss/ui/styles.css").read_text(encoding="utf-8-sig")

    assert "register_understanding_routes(app, _require_local_control)" in app
    assert '"mode": "p66b_goal_understanding_clarification"' in app
    assert "NEXUSS_P66B_GOAL_UNDERSTANDING_UI" in ui
    assert "P66B_LEGACY_DELEGATION_OPTIONS" in ui
    assert "options = {}" in ui
    assert "options.userAlreadyAdded" in ui
    assert "void understandAndExecute(utterance, channel);" in ui
    assert "NEXUSS_P66B_GOAL_UNDERSTANDING_UI" in styles
