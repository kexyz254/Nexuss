"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary."""

from pathlib import Path
from uuid import UUID

import pytest

from nexuss.device_node.browser_executor import WindowsChromeExecutor
from nexuss.device_node.executor import NodeExecutionError
from tests.fakes import FakeBrowserRunner

TASK_ID = UUID("00000000-0000-0000-0000-000000000970")
COMMAND_ID = UUID("00000000-0000-0000-0000-000000000971")


def test_browser_executor_uses_fixed_executable_and_approved_url(
    tmp_path: Path,
) -> None:
    executable = (tmp_path / "chrome.exe").resolve()
    runner = FakeBrowserRunner()
    executor = WindowsChromeExecutor(
        executable=executable,
        runner=runner,
    )
    launch_url = "https://www.google.com/search?q=forex"

    evidence = executor.launch(
        task_id=TASK_ID,
        command_id=COMMAND_ID,
        target_node_id="windows-primary",
        launch_url=launch_url,
    )

    assert runner.calls == [(executable, launch_url)]
    assert evidence.capability_id == "device.open_web_search"
    assert evidence.verified_running is True


def test_browser_executor_rejects_unapproved_host(tmp_path: Path) -> None:
    executor = WindowsChromeExecutor(
        executable=(tmp_path / "chrome.exe").resolve(),
        runner=FakeBrowserRunner(),
    )

    with pytest.raises(NodeExecutionError, match="WEB_URL_NOT_ALLOWLISTED"):
        executor.launch(
            task_id=TASK_ID,
            command_id=COMMAND_ID,
            target_node_id="windows-primary",
            launch_url="https://evil.example/steal",
        )
