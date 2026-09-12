"""P6.12 browser polling and task-runtime contracts."""

from pathlib import Path


def test_desktop_polling_is_adaptive() -> None:
    text = Path("src/nexuss/ui/app.js").read_text(encoding="utf-8-sig")
    assert "P6.12 ADAPTIVE DESKTOP POLLING" in text
    assert "TASK_POLL_AWAITING_APPROVAL_MS = 3000" in text
    assert "TASK_POLL_BACKOFF_MAX_MS = 8000" in text
    assert "HEALTH_POLL_VISIBLE_MS = 60000" in text
    assert "setInterval(checkHealth, 30000)" not in text
    assert "setInterval(async () =>" not in text[
        text.index("P6.12 ADAPTIVE DESKTOP POLLING"):
        text.index("async function showApproval")
    ]


def test_mobile_polling_is_adaptive_and_battery_bounded() -> None:
    text = Path("src/nexuss/ui/mobile.js").read_text(encoding="utf-8-sig")
    assert "P6.12 ADAPTIVE MOBILE COMPANION POLLING" in text
    assert "POLL_PENDING_APPROVAL_MS = 1500" in text
    assert "POLL_ACTIVE_HANDOFF_MS = 2500" in text
    assert "POLL_IDLE_FOREGROUND_MS = 8000" in text
    assert "POLL_HIDDEN_MS = 20000" in text
    assert "POLL_BACKOFF_MAX_MS = 30000" in text
    assert "function syncWakeLock()" in text
    assert 'fetch("/v1/mobile/snapshot"' in text
    poll_region = text[text.index("async function poll() {"):text.index("async function decide")]
    assert 'fetch("/v1/mobile/pending"' not in poll_region
    assert 'fetch("/v1/mobile/handoffs"' not in poll_region
    assert "Android developer mode" not in text


def test_professional_workspace_exposes_task_runtime() -> None:
    text = Path(
        "src/nexuss/ui/nexuss_ui_platform.js"
    ).read_text(encoding="utf-8-sig")
    assert "P6.12 TASK RUNTIME CENTER" in text
    assert 'id: "tasks"' in text
    assert 'title: "Task Runtime"' in text
    assert "currentTask" in text
    assert "renderTaskCenter" in text
