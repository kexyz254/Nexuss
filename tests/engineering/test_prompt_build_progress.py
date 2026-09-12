from __future__ import annotations

import json
from pathlib import Path

from nexuss.engineering.models import ToolName
from nexuss.engineering.prompt_build import (
    _BuildProgress,
    _allowed_tools,
    latest_prompt_build_progress,
)


def test_write_required_is_mechanically_write_only() -> None:
    assert _allowed_tools("write_required") == (ToolName.WRITE_FILE,)


def test_progress_projection_is_local_and_terminal(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    run_root = tmp_path / "Nexuss" / "engineering-runs" / "prompt-build-20260828-010101"
    run_root.mkdir(parents=True)
    progress = _BuildProgress(run_root, "add a diagnostics badge")
    progress.emit(
        actor="DeepSeek",
        phase="writing",
        message="Writing src/nexuss/ui/p5.js.",
        round_number=3,
        changed_file_count=1,
    )
    current = latest_prompt_build_progress()
    assert current["active"] is True
    assert current["actor"] == "DeepSeek"
    assert current["round"] == 3
    assert current["changed_file_count"] == 1
    assert "api_key" not in json.dumps(current).lower()

    progress.emit(
        actor="Nexuss",
        phase="completed",
        message="Build complete.",
        changed_file_count=1,
        terminal=True,
        code="ENGINEERING_BUILD_SUCCESS",
    )
    completed = latest_prompt_build_progress()
    assert completed["active"] is False
    assert completed["terminal"] is True
    assert completed["code"] == "ENGINEERING_BUILD_SUCCESS"


def test_ui_contract_contains_progress_endpoint() -> None:
    root = Path(__file__).resolve().parents[2]
    app = (root / "src/nexuss/api/app.py").read_text(encoding="utf-8")
    p5 = (root / "src/nexuss/ui/p5.js").read_text(encoding="utf-8")
    css = (root / "src/nexuss/ui/styles.css").read_text(encoding="utf-8")
    assert "/v1/engineering/prompt-build/progress" in app
    assert "/v1/engineering/prompt-build/progress" in p5
    assert "engineering-progress-card" in css
