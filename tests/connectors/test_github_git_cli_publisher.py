from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from nexuss.connectors.github.archive_publisher import (
    ArchivePublishFile,
    PreparedArchivePublish,
    canonical_archive_publish_bytes,
    git_blob_sha1,
)
from nexuss.connectors.github.git_cli_publisher import (
    GitCliArchivePublisher,
)


@pytest.mark.skipif(
    shutil.which("git") is None,
    reason="Git is required",
)
def test_git_cli_creates_one_exact_root_commit(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_bytes(b"alpha\n")
    (source / "run.sh").write_bytes(b"#!/bin/sh\necho ok\n")

    files = []
    for path, mode in (
        ("a.txt", "100644"),
        ("run.sh", "100755"),
    ):
        content = (source / path).read_bytes()
        files.append(
            ArchivePublishFile(
                path=path,
                sha256=hashlib.sha256(content).hexdigest(),
                git_blob_sha1=git_blob_sha1(content),
                size_bytes=len(content),
                git_mode=mode,
            )
        )

    provisional = PreparedArchivePublish.model_construct(
        request_id=uuid4(),
        intake_id=uuid4(),
        repository_creation_request_id=uuid4(),
        repository_creation_approval_id=uuid4(),
        repository_id=1,
        owner_login="owner",
        repository_name="repo",
        branch="main",
        commit_message="feat: exact root commit",
        archive_sha256="1" * 64,
        manifest_sha256="2" * 64,
        source_root=str(source),
        files=tuple(files),
        payload_sha256="0" * 64,
        approval_required=True,
        approval_channel="phone",
        force_push=False,
        workflow_files_changed=False,
    )
    prepared = PreparedArchivePublish(
        **provisional.model_dump(exclude={"payload_sha256"}),
        payload_sha256=hashlib.sha256(
            canonical_archive_publish_bytes(provisional)
        ).hexdigest(),
    )

    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "--quiet", str(remote)],
        check=True,
    )

    pushed = GitCliArchivePublisher()._push_root_commit(
        prepared,
        access_token="",
        remote_url=str(remote),
    )

    observed = subprocess.run(
        [
            "git",
            "--git-dir",
            str(remote),
            "rev-parse",
            "refs/heads/main",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert observed == pushed.commit_sha

    commit = subprocess.run(
        [
            "git",
            "--git-dir",
            str(remote),
            "cat-file",
            "-p",
            pushed.commit_sha,
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "\nparent " not in "\n" + commit

    tree = subprocess.run(
        [
            "git",
            "--git-dir",
            str(remote),
            "ls-tree",
            "-r",
            pushed.commit_sha,
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "100644 blob" in tree
    assert "100755 blob" in tree
    assert "\ta.txt" in tree
    assert "\trun.sh" in tree
    assert pushed.tree_sha
