"""Bounded Git repository operations for Nexuss self-update."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from uuid import uuid4

from nexuss.local_control.models import (
    LocalUpdateAccepted,
    LocalUpdateStatus,
)

_APPROVED_BRANCH = "feature/p5-knowledge-media-mobile"


class LocalRepositoryError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class GitRepositoryManager:
    def __init__(self, repository_root: Path | None = None) -> None:
        configured = os.getenv("NEXUSS_REPOSITORY_ROOT", "").strip()
        root = (
            repository_root
            or (Path(configured) if configured else Path.cwd())
        )
        self._root = root.resolve()

    @property
    def root(self) -> Path:
        return self._root

    @property
    def approved_branch(self) -> str:
        return _APPROVED_BRANCH

    def _git(
        self,
        *args: str,
        timeout: float = 30.0,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["git", *args],
                cwd=self._root,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=check,
            )
        except (
            FileNotFoundError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ) as exc:
            raise LocalRepositoryError(
                "LOCAL_GIT_OPERATION_FAILED",
                f"Git operation failed: {' '.join(args)}",
            ) from exc

    def inspect(self, *, branch: str = _APPROVED_BRANCH) -> LocalUpdateStatus:
        if branch != _APPROVED_BRANCH:
            raise LocalRepositoryError(
                "LOCAL_UPDATE_BRANCH_NOT_ALLOWED",
                "Only the approved Nexuss development branch may self-update.",
            )

        current_branch = self._git("branch", "--show-current").stdout.strip()
        if current_branch != branch:
            raise LocalRepositoryError(
                "LOCAL_UPDATE_BRANCH_MISMATCH",
                f"Repository is on {current_branch!r}, not {branch!r}.",
            )

        current_sha = self._git("rev-parse", "HEAD").stdout.strip()
        clean = not bool(
            self._git("status", "--porcelain").stdout.strip()
        )

        self._git("fetch", "origin", "--prune", timeout=60.0)
        remote_sha = self._git(
            "rev-parse",
            f"origin/{branch}",
        ).stdout.strip()

        counts = self._git(
            "rev-list",
            "--left-right",
            "--count",
            f"{current_sha}...{remote_sha}",
        ).stdout.strip().split()

        if len(counts) != 2:
            raise LocalRepositoryError(
                "LOCAL_UPDATE_REVISION_COUNT_INVALID",
                "Git did not return an ahead/behind count.",
            )

        ahead_by, behind_by = (int(counts[0]), int(counts[1]))
        ancestor = self._git(
            "merge-base",
            "--is-ancestor",
            current_sha,
            remote_sha,
            check=False,
        ).returncode == 0

        return LocalUpdateStatus(
            branch=branch,
            current_sha=current_sha,
            remote_sha=remote_sha,
            clean_worktree=clean,
            fast_forward_available=ancestor and behind_by > 0,
            update_available=current_sha != remote_sha,
            ahead_by=ahead_by,
            behind_by=behind_by,
            restart_required=current_sha != remote_sha,
        )

    def apply_fast_forward(
        self,
        *,
        expected_current_sha: str,
        expected_target_sha: str,
        branch: str = _APPROVED_BRANCH,
    ) -> LocalUpdateAccepted:
        status = self.inspect(branch=branch)

        if not status.clean_worktree:
            raise LocalRepositoryError(
                "LOCAL_UPDATE_WORKTREE_DIRTY",
                "Self-update requires a clean Nexuss worktree.",
            )
        if status.current_sha != expected_current_sha:
            raise LocalRepositoryError(
                "LOCAL_UPDATE_CURRENT_SHA_CHANGED",
                "The local revision changed after approval.",
            )
        if status.remote_sha != expected_target_sha:
            raise LocalRepositoryError(
                "LOCAL_UPDATE_TARGET_SHA_CHANGED",
                "The GitHub target changed after approval.",
            )
        if status.ahead_by != 0 or not status.fast_forward_available:
            raise LocalRepositoryError(
                "LOCAL_UPDATE_NOT_FAST_FORWARD",
                "Only a clean fast-forward update is permitted.",
            )

        self._git("merge", "--ff-only", f"origin/{branch}", timeout=60.0)
        verified = self._git("rev-parse", "HEAD").stdout.strip()
        if verified != expected_target_sha:
            raise LocalRepositoryError(
                "LOCAL_UPDATE_POST_MERGE_SHA_MISMATCH",
                "The applied local revision did not match the approved target.",
            )

        helper = self._root / "scripts" / "restart_after_verified_update.ps1"
        if not helper.is_file():
            raise LocalRepositoryError(
                "LOCAL_UPDATE_RESTART_HELPER_MISSING",
                "Verified restart helper is not installed.",
            )

        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(helper),
            "-PreviousSha",
            expected_current_sha,
            "-TargetSha",
            expected_target_sha,
        ]

        try:
            subprocess.Popen(
                command,
                cwd=self._root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=(
                    getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                    | getattr(subprocess, "DETACHED_PROCESS", 0)
                ),
            )
        except OSError as exc:
            self._git("reset", "--hard", expected_current_sha)
            raise LocalRepositoryError(
                "LOCAL_UPDATE_RESTART_SCHEDULING_FAILED",
                "Update was rolled back because restart could not be scheduled.",
            ) from exc

        return LocalUpdateAccepted(
            update_id=uuid4(),
            previous_sha=expected_current_sha,
            target_sha=expected_target_sha,
            branch=branch,
            restart_scheduled=True,
            rollback_on_failed_health=True,
        )
