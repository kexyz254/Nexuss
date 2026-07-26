"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Allowlisted Windows command execution for the P4 trusted device node.
"""

from __future__ import annotations

import os
import socket
import subprocess  # nosec B404
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Protocol
from uuid import UUID

from nexuss.device.models import DeviceCommandEvidence, DeviceRollbackEvidence


class NodeExecutionError(RuntimeError):
    """Raised when the device node cannot safely execute or reverse a capability."""


class ProcessHandle(Protocol):
    pid: int

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


class ProcessRunner(Protocol):
    def start(self, executable: Path) -> ProcessHandle: ...


class SubprocessRunner:
    def start(self, executable: Path) -> ProcessHandle:
        # Fixed executable; no shell and no user-controlled arguments.
        return subprocess.Popen(  # nosec B603
            [str(executable)],
            close_fds=True,
        )


@dataclass(slots=True)
class _LaunchedProcess:
    task_id: UUID
    command_id: UUID
    executable: Path
    process: ProcessHandle
    started_at: datetime


class WindowsNotepadExecutor:
    """Launch and receipt-bind only the fixed Windows Notepad executable."""

    def __init__(
        self,
        *,
        node_id: str | None = None,
        executable: Path | None = None,
        runner: ProcessRunner | None = None,
    ) -> None:
        self._node_id: str = (
            node_id
            or os.getenv("NEXUSS_WINDOWS_NODE_ID")
            or "windows-primary"
        )
        windows_directory = Path(os.environ.get("WINDIR", r"C:\Windows"))
        self._executable = executable or windows_directory / "System32" / "notepad.exe"
        self._runner = runner or SubprocessRunner()
        self._launched: dict[UUID, _LaunchedProcess] = {}
        self._lock = RLock()

    @property
    def node_id(self) -> str:
        return self._node_id

    def launch(
        self,
        *,
        task_id: UUID,
        command_id: UUID,
        target_node_id: str,
    ) -> DeviceCommandEvidence:
        if os.name != "nt" and isinstance(self._runner, SubprocessRunner):
            raise NodeExecutionError("WINDOWS_NODE_REQUIRED")
        if target_node_id != self._node_id:
            raise NodeExecutionError("TARGET_NODE_ID_MISMATCH")
        if not self._executable.is_absolute():
            raise NodeExecutionError("NOTEPAD_EXECUTABLE_NOT_ABSOLUTE")
        if isinstance(self._runner, SubprocessRunner) and not self._executable.is_file():
            raise NodeExecutionError("NOTEPAD_EXECUTABLE_NOT_FOUND")

        with self._lock:
            existing = self._launched.get(command_id)
            if existing is not None:
                return self._evidence(existing)
            started_at = datetime.now(UTC)
            process = self._runner.start(self._executable)
            if process.pid <= 0:
                raise NodeExecutionError("DEVICE_PROCESS_ID_INVALID")
            record = _LaunchedProcess(
                task_id=task_id,
                command_id=command_id,
                executable=self._executable,
                process=process,
                started_at=started_at,
            )
            self._launched[command_id] = record
            return self._evidence(record)

    def _evidence(self, record: _LaunchedProcess) -> DeviceCommandEvidence:
        return DeviceCommandEvidence(
            command_id=record.command_id,
            node_id=self._node_id,
            node_hostname=socket.gethostname(),
            capability_id="device.launch_notepad",
            executable=str(record.executable),
            process_id=record.process.pid,
            started_at=record.started_at,
            verified_running=record.process.poll() is None,
        )

    def rollback(
        self,
        *,
        rollback_id: UUID,
        task_id: UUID,
        command_id: UUID,
        target_node_id: str,
    ) -> DeviceRollbackEvidence:
        if target_node_id != self._node_id:
            raise NodeExecutionError("TARGET_NODE_ID_MISMATCH")
        with self._lock:
            record = self._launched.get(command_id)
            if record is None:
                raise NodeExecutionError("RECEIPT_BOUND_COMMAND_NOT_FOUND")
            if record.task_id != task_id:
                raise NodeExecutionError("RECEIPT_BOUND_TASK_MISMATCH")
            was_running = record.process.poll() is None
            if was_running:
                record.process.terminate()
                try:
                    record.process.wait(timeout=3.0)
                except subprocess.TimeoutExpired as exc:
                    raise NodeExecutionError("DEVICE_PROCESS_TERMINATION_TIMEOUT") from exc
            verified_absent = record.process.poll() is not None
            if verified_absent:
                self._launched.pop(command_id, None)
            return DeviceRollbackEvidence(
                rollback_id=rollback_id,
                command_id=command_id,
                node_id=self._node_id,
                process_id=record.process.pid,
                terminated=was_running,
                verified_absent=verified_absent,
                observed_at=datetime.now(UTC),
            )
