"""Live, read-only local workspace evidence collection for Nexuss P2."""

from __future__ import annotations

import platform
import shutil

# Security review: subprocess is limited to bounded, read-only Git metadata.
import subprocess  # nosec B404
import sys
from datetime import UTC, datetime
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_MAX_GIT_OUTPUT = 16_384
_GIT_TIMEOUT_SECONDS = 4


class LocalWorkspaceEvidenceError(RuntimeError):
    """Raised when local workspace evidence cannot be collected safely."""


def _run_git(repository_root: Path, *arguments: str) -> str:
    git_executable = shutil.which("git")
    if git_executable is None:
        raise LocalWorkspaceEvidenceError("Git executable is unavailable")

    command = [git_executable, "-C", str(repository_root), *arguments]
    try:
        # Security review: fixed Git executable, no shell, allowlisted arguments.
        completed = subprocess.run(  # nosec B603
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise LocalWorkspaceEvidenceError("Git metadata collection failed") from exc

    output = completed.stdout.strip()
    if len(output.encode("utf-8")) > _MAX_GIT_OUTPUT:
        raise LocalWorkspaceEvidenceError("Git metadata exceeded the safe output limit")
    return output


def collect_local_workspace_status(
    observed_at: datetime | None = None,
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, object]:
    """Collect bounded metadata without reading user file contents or modifying the system."""

    timestamp = observed_at or datetime.now(UTC)
    root = repository_root.resolve()
    if not root.is_dir() or not (root / ".git").exists():
        raise LocalWorkspaceEvidenceError("Configured Nexuss repository is not a Git workspace")

    branch = _run_git(root, "branch", "--show-current") or "detached"
    commit = _run_git(root, "rev-parse", "HEAD")
    porcelain = _run_git(root, "status", "--porcelain=v1")
    changed_entries = [line for line in porcelain.splitlines() if line.strip()]
    disk = shutil.disk_usage(root)

    return {
        "source_mode": "live_local_readonly",
        "observed_at": timestamp.isoformat(),
        "hostname": platform.node() or "unknown",
        "operating_system": platform.system() or "unknown",
        "operating_system_release": platform.release() or "unknown",
        "machine": platform.machine() or "unknown",
        "python_version": platform.python_version(),
        "python_executable_name": Path(sys.executable).name,
        "repository_name": root.name,
        "repository_path": str(root),
        "git_branch": branch,
        "git_commit": commit,
        "git_clean": not changed_entries,
        "git_changed_entries": len(changed_entries),
        "disk_total_bytes": disk.total,
        "disk_free_bytes": disk.free,
        "api_mode": "p3_approved_actions",
    }
