from __future__ import annotations

import json

from nexuss.local_control.repository import GitRepositoryManager


def test_update_result_defaults_to_unknown(tmp_path) -> None:
    manager = GitRepositoryManager(tmp_path)
    result = manager.update_result()
    assert result.status == "unknown"
    assert result.credentials_exposed is False


def test_update_result_reads_restart_receipt(tmp_path) -> None:
    runtime = tmp_path / ".nexuss-runtime"
    runtime.mkdir()
    previous = "a" * 40
    target = "b" * 40
    payload = {
        "status": "completed",
        "previous_sha": previous,
        "target_sha": target,
        "active_sha": target,
        "detail": "Verified update restarted successfully.",
        "completed_at": "2026-09-21T05:00:00+00:00",
    }
    (runtime / "update-result.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    result = GitRepositoryManager(tmp_path).update_result()
    assert result.status == "completed"
    assert result.previous_sha == previous
    assert result.target_sha == target
    assert result.active_sha == target
    assert result.credentials_exposed is False
