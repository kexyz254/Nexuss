from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from nexuss.local_control.repository import (
    GitRepositoryManager,
    LocalRepositoryError,
)

BRANCH = "feature/p5-knowledge-media-mobile"


def _git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _repository_pair(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )

    local = tmp_path / "local"
    subprocess.run(
        ["git", "clone", str(remote), str(local)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(local, "config", "user.email", "nexuss@example.invalid")
    _git(local, "config", "user.name", "Nexuss Test")
    _git(local, "checkout", "-b", BRANCH)
    (local / "README.md").write_text("base\n", encoding="utf-8")
    _git(local, "add", "README.md")
    _git(local, "commit", "-m", "base")
    _git(local, "push", "-u", "origin", BRANCH)

    publisher = tmp_path / "publisher"
    subprocess.run(
        ["git", "clone", str(remote), str(publisher)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(publisher, "config", "user.email", "nexuss@example.invalid")
    _git(publisher, "config", "user.name", "Nexuss Test")
    _git(publisher, "checkout", BRANCH)
    (publisher / "README.md").write_text(
        "base\nremote update\n",
        encoding="utf-8",
    )
    _git(publisher, "add", "README.md")
    _git(publisher, "commit", "-m", "remote update")
    _git(publisher, "push", "origin", BRANCH)

    return local, publisher


def test_inspect_reports_clean_fast_forward_update(tmp_path: Path) -> None:
    local, publisher = _repository_pair(tmp_path)
    manager = GitRepositoryManager(local)

    status = manager.inspect()

    assert status.clean_worktree is True
    assert status.update_available is True
    assert status.fast_forward_available is True
    assert status.ahead_by == 0
    assert status.behind_by == 1
    assert status.remote_sha == _git(publisher, "rev-parse", "HEAD")


def test_apply_is_exact_fast_forward_and_schedules_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local, _ = _repository_pair(tmp_path)
    manager = GitRepositoryManager(local)
    manager._powershell_executable = "powershell.exe"
    before = manager.inspect()
    helper = local / "scripts" / "restart_after_verified_update.ps1"
    helper.parent.mkdir(parents=True)
    helper.write_text("# test helper\n", encoding="utf-8")

    calls: list[list[str]] = []
    real_popen = subprocess.Popen

    class FakeProcess:
        pass

    def fake_popen(command, **kwargs):
        if next(iter(command)) == "powershell.exe":
            calls.append(list(command))
            return FakeProcess()
        return real_popen(command, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    accepted = manager.apply_fast_forward(
        expected_current_sha=before.current_sha,
        expected_target_sha=before.remote_sha,
    )

    assert _git(local, "rev-parse", "HEAD") == before.remote_sha
    assert accepted.previous_sha == before.current_sha
    assert accepted.target_sha == before.remote_sha
    assert accepted.restart_scheduled is True
    assert calls
    assert "restart_after_verified_update.ps1" in " ".join(calls[0])


def test_dirty_worktree_blocks_update(tmp_path: Path) -> None:
    local, _ = _repository_pair(tmp_path)
    manager = GitRepositoryManager(local)
    before = manager.inspect()
    (local / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(LocalRepositoryError) as captured:
        manager.apply_fast_forward(
            expected_current_sha=before.current_sha,
            expected_target_sha=before.remote_sha,
        )

    assert captured.value.code == "LOCAL_UPDATE_WORKTREE_DIRTY"
