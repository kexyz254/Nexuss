"""Tests for the bounded live local workspace evidence provider."""

from datetime import UTC, datetime
from pathlib import Path

from pytest import MonkeyPatch

from nexuss.core import local_workspace


def test_collect_local_workspace_status_returns_bounded_metadata(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    responses: dict[tuple[str, ...], str] = {
        ("branch", "--show-current"): "feature/test",
        ("rev-parse", "HEAD"): "a" * 40,
        ("status", "--porcelain=v1"): " M README.md\n?? local.txt",
    }

    def fake_run_git(repository_root: Path, *arguments: str) -> str:
        assert repository_root == tmp_path.resolve()
        return responses[arguments]

    monkeypatch.setattr(local_workspace, "_run_git", fake_run_git)
    observed_at = datetime(2026, 7, 25, 15, 0, tzinfo=UTC)

    result = local_workspace.collect_local_workspace_status(
        observed_at,
        repository_root=tmp_path,
    )

    assert result["source_mode"] == "live_local_readonly"
    assert result["git_branch"] == "feature/test"
    assert result["git_commit"] == "a" * 40
    assert result["git_clean"] is False
    assert result["git_changed_entries"] == 2
    assert result["observed_at"] == observed_at.isoformat()
    assert result["api_mode"] == "p3_approved_actions"
    assert "environment" not in result
    assert "file_contents" not in result
