from __future__ import annotations

from pathlib import Path

import pytest

from nexuss.engineering.errors import EngineeringError
from nexuss.engineering.workspace import IsolatedWorkspace


def test_workspace_blocks_path_escape(tmp_path: Path) -> None:
    workspace = IsolatedWorkspace(tmp_path / "work")
    with pytest.raises(EngineeringError) as raised:
        workspace.write_text("../outside.txt", "no")
    assert raised.value.code == "ENGINEERING_PATH_ESCAPE"


def test_workspace_requires_hash_for_overwrite(tmp_path: Path) -> None:
    workspace = IsolatedWorkspace(tmp_path / "work")
    digest = workspace.write_text("index.html", "first")
    with pytest.raises(EngineeringError) as raised:
        workspace.write_text("index.html", "second")
    assert raised.value.code == "ENGINEERING_OVERWRITE_REQUIRES_HASH"
    workspace.write_text("index.html", "second", expected_sha256=digest)
    assert workspace.read_text("index.html") == "second"


def test_workspace_blocks_secret_filename(tmp_path: Path) -> None:
    workspace = IsolatedWorkspace(tmp_path / "work")
    with pytest.raises(EngineeringError) as raised:
        workspace.write_text(".env", "SECRET=x")
    assert raised.value.code == "ENGINEERING_SECRET_FILE_DENIED"


def test_workspace_blocks_shell_and_git_write(tmp_path: Path) -> None:
    workspace = IsolatedWorkspace(tmp_path / "work")
    with pytest.raises(EngineeringError) as raised:
        workspace.run_command(["powershell", "-Command", "echo bad"])
    assert raised.value.code == "ENGINEERING_COMMAND_DENIED"

    with pytest.raises(EngineeringError) as raised_git:
        workspace.run_command(["git", "commit", "-m", "bad"])
    assert raised_git.value.code == "ENGINEERING_GIT_WRITE_DENIED"
