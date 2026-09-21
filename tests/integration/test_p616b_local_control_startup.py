from __future__ import annotations

from pathlib import Path


def test_startup_launches_three_bounded_local_services() -> None:
    script = Path("scripts/start_p5.ps1").read_text(encoding="utf-8")
    assert "@(8100, 8200, 8300)" in script
    assert "nexuss.local_control.app:app" in script
    assert "--host 127.0.0.1 --port 8300" in script
    assert "p616b_trusted_local_control" in script
    assert "local_control_process_id = $LocalControlProcess.Id" in script
    assert "NEXUSS_LOCAL_CONTROL_SECRET" in script
    assert "API_KEY|TOKEN|PASSWORD|SECRET" in script


def test_stop_script_handles_local_control_and_stale_pids() -> None:
    script = Path("scripts/stop_p5.ps1").read_text(encoding="utf-8")
    assert "$Runtime.local_control_process_id" in script
    assert "Get-Process -Id $ProcessId -ErrorAction SilentlyContinue" in script
    assert "is already stopped" in script


def test_restart_helper_has_health_rollback_contract() -> None:
    script = Path(
        "scripts/restart_after_verified_update.ps1"
    ).read_text(encoding="utf-8")
    assert "git reset --hard $PreviousSha" in script
    assert 'Status "rolled_back"' in script
    assert 'Status "recovery_failed"' in script
