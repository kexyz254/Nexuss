"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from nexuss.device.models import DeviceCommandEvidence, DeviceRollbackEvidence


class FakeDeviceNodeClient:
    def __init__(self) -> None:
        self.launches: list[tuple[UUID, str]] = []
        self.rollbacks: list[tuple[UUID, UUID, str]] = []
        self.web_searches: list[tuple[UUID, str, str]] = []

    def launch_notepad(
        self,
        task_id: UUID,
        target_node_id: str,
    ) -> DeviceCommandEvidence:
        self.launches.append((task_id, target_node_id))
        command_id = uuid5(
            NAMESPACE_URL,
            f"nexuss:fake-command:{task_id}:{target_node_id}",
        )
        return DeviceCommandEvidence(
            command_id=command_id,
            node_id=target_node_id,
            node_hostname="test-windows-node",
            capability_id="device.launch_notepad",
            executable=r"C:\Windows\System32\notepad.exe",
            process_id=4242,
            started_at=datetime.now(UTC),
            verified_running=True,
        )

    def open_web_search(
        self,
        task_id: UUID,
        target_node_id: str,
        launch_url: str,
    ) -> DeviceCommandEvidence:
        self.web_searches.append((task_id, target_node_id, launch_url))
        command_id = uuid5(
            NAMESPACE_URL,
            f"nexuss:fake-web:{task_id}:{launch_url}",
        )
        return DeviceCommandEvidence(
            command_id=command_id,
            node_id=target_node_id,
            node_hostname="test-windows-node",
            capability_id="device.open_web_search",
            executable=(
                r"C:\Program Files\Google\Chrome\Application\chrome.exe"
            ),
            process_id=4343,
            started_at=datetime.now(UTC),
            verified_running=True,
        )

    def rollback_command(
        self,
        task_id: UUID,
        command_id: UUID,
        target_node_id: str,
    ) -> DeviceRollbackEvidence:
        self.rollbacks.append((task_id, command_id, target_node_id))
        return DeviceRollbackEvidence(
            rollback_id=uuid5(
                NAMESPACE_URL,
                f"nexuss:fake-rollback:{task_id}:{command_id}",
            ),
            command_id=command_id,
            node_id=target_node_id,
            process_id=4242,
            terminated=True,
            verified_absent=True,
            observed_at=datetime.now(UTC),
        )


class FakeProcess:
    def __init__(self) -> None:
        self.pid = 9001
        self.return_code: int | None = None

    def poll(self) -> int | None:
        return self.return_code

    def terminate(self) -> None:
        self.return_code = 0

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self.return_code = 0
        return 0


class FakeRunner:
    def __init__(self) -> None:
        self.process = FakeProcess()
        self.executables: list[Path] = []

    def start(self, executable: Path) -> FakeProcess:
        self.executables.append(executable)
        return self.process


class FakeBrowserRunner:
    def __init__(self) -> None:
        self.process = FakeProcess()
        self.calls: list[tuple[Path, str]] = []

    def start(self, executable: Path, launch_url: str) -> FakeProcess:
        self.calls.append((executable, launch_url))
        return self.process
