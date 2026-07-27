"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Allowlisted Chrome handoff for the trusted Windows device node.
"""

from __future__ import annotations

import os
import socket
import subprocess  # nosec B404
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from nexuss.core.web_actions import (
    WebActionValidationError,
    validate_handoff_url,
)
from nexuss.device.models import DeviceCommandEvidence
from nexuss.device_node.executor import NodeExecutionError, ProcessHandle


class BrowserRunner(Protocol):
    def start(self, executable: Path, launch_url: str) -> ProcessHandle: ...


class ChromeSubprocessRunner:
    def start(self, executable: Path, launch_url: str) -> ProcessHandle:
        # Fixed executable and argument shape; URL is allowlist-validated.
        return subprocess.Popen(  # nosec B603
            [str(executable), "--new-tab", launch_url],
            close_fds=True,
        )


def _chrome_candidates() -> tuple[Path, ...]:
    roots = (
        os.getenv("PROGRAMFILES"),
        os.getenv("PROGRAMFILES(X86)"),
        os.getenv("LOCALAPPDATA"),
    )
    return tuple(
        Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe"
        for root in roots
        if root
    )


class WindowsChromeExecutor:
    """Open one validated URL through a fixed Chrome executable."""

    def __init__(
        self,
        *,
        node_id: str = "windows-primary",
        executable: Path | None = None,
        runner: BrowserRunner | None = None,
    ) -> None:
        self._node_id = node_id
        self._executable = executable or next(
            (candidate for candidate in _chrome_candidates() if candidate.is_file()),
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        )
        self._runner = runner or ChromeSubprocessRunner()

    def launch(
        self,
        *,
        task_id: UUID,
        command_id: UUID,
        target_node_id: str,
        launch_url: str,
    ) -> DeviceCommandEvidence:
        del task_id
        if target_node_id != self._node_id:
            raise NodeExecutionError("TARGET_NODE_ID_MISMATCH")
        try:
            validated_url = validate_handoff_url(launch_url)
        except WebActionValidationError as exc:
            raise NodeExecutionError(str(exc)) from exc
        if not self._executable.is_absolute():
            raise NodeExecutionError("CHROME_EXECUTABLE_NOT_ABSOLUTE")
        if (
            isinstance(self._runner, ChromeSubprocessRunner)
            and not self._executable.is_file()
        ):
            raise NodeExecutionError("CHROME_EXECUTABLE_NOT_FOUND")

        process = self._runner.start(self._executable, validated_url)
        if process.pid <= 0:
            raise NodeExecutionError("DEVICE_PROCESS_ID_INVALID")
        return DeviceCommandEvidence(
            command_id=command_id,
            node_id=self._node_id,
            node_hostname=socket.gethostname(),
            capability_id="device.open_web_search",
            executable=str(self._executable),
            process_id=process.pid,
            started_at=datetime.now(UTC),
            verified_running=process.poll() is None,
        )
