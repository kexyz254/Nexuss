from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

import nexuss.engineering.development_packages as dp
from nexuss.domain.models import (
    ApprovalDecision,
    ApprovalDecisionKind,
    ApprovalChannel,
    AssuranceLevel,
    IdentitySession,
    TaskState,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(repo: Path, *args: str) -> None:
    completed = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "example.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "README.md").write_text("demo\n", encoding="utf-8")
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@localhost")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    return repo


def _manifest(repo: Path, *, after: bytes, path: str = "src/example.py") -> dict[str, object]:
    live = repo / path
    return {
        "format": "nexuss-development-package-v1",
        "package_id": "p613-test-package",
        "phase": "P6.13-test",
        "title": "Test development package",
        "description": "A deterministic test package.",
        "created_at": datetime.now(UTC).isoformat(),
        "requires_restart": True,
        "trust_boundary_change": False,
        "database_schema_changed": False,
        "base_git_head": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip(),
        "files": [
            {
                "path": path,
                "operation": "replace",
                "before_sha256": _sha(live),
                "sha256": hashlib.sha256(after).hexdigest(),
                "size_bytes": len(after),
            }
        ],
        "focused_tests": [],
    }


def _zip(tmp_path: Path, manifest: dict[str, object], *, payload: bytes, path: str = "src/example.py") -> Path:
    archive = tmp_path / "package.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("NEXUSS-DEVELOPMENT-MANIFEST.json", json.dumps(manifest))
        z.writestr(f"payload/{path}", payload)
    return archive


async def _stream(path: Path):
    data = path.read_bytes()
    for start in range(0, len(data), 257):
        yield data[start : start + 257]


def _identity():
    return IdentitySession(
        session_id=uuid4(),
        authenticated=True,
        assurance_level=AssuranceLevel.BASIC,
    )


def _wait(coordinator: dp.DevelopmentPackageCoordinator, task_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = coordinator.get_task(task_id)
        if task.state in {TaskState.COMPLETED, TaskState.FAILED, TaskState.DENIED}:
            return task
        time.sleep(0.02)
    raise AssertionError("package task did not become terminal")


def _approve(coordinator, task, identity):
    approval = task.approval
    assert approval is not None and approval.approval_token is not None
    return coordinator.approve_task(
        task.task_id,
        ApprovalDecision(
            approval_id=approval.approval_id,
            approval_token=approval.approval_token,
            payload_sha256=approval.payload_sha256,
            decision=ApprovalDecisionKind.APPROVE,
        ),
        identity,
        approval_channel=ApprovalChannel.DESKTOP,
    )


def test_manifest_operation_contracts():
    with pytest.raises(ValueError):
        dp.DevelopmentPackageFile(path="x.py", operation="replace", sha256="0" * 64)
    with pytest.raises(ValueError):
        dp.DevelopmentPackageFile(path="x.py", operation="delete", before_sha256="0" * 64, sha256="1" * 64)


def test_wrong_base_hash_rejected_before_approval(tmp_path):
    repo = _repo(tmp_path)
    after = b"VALUE = 2\n"
    manifest = _manifest(repo, after=after)
    manifest["files"][0]["before_sha256"] = "0" * 64
    archive = _zip(tmp_path, manifest, payload=after)
    coordinator = dp.DevelopmentPackageCoordinator(
        repository_root=repo,
        storage_root=tmp_path / "store",
    )
    with pytest.raises(dp.DevelopmentPackageError) as captured:
        asyncio.run(
            coordinator.create_task_from_stream(
                _stream(archive),
                request_id=uuid4(),
                session=_identity(),
                archive_name=archive.name,
                content_type="application/zip",
                content_length=archive.stat().st_size,
            )
        )
    assert captured.value.code == "DEVELOPMENT_PACKAGE_BASE_HASH_MISMATCH"


def test_hard_denied_credential_path_rejected(tmp_path):
    repo = _repo(tmp_path)
    path = "src/nexuss/connectors/vault.py"
    live = repo / path
    live.parent.mkdir(parents=True)
    live.write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "vault")
    after = b"VALUE = 2\n"
    manifest = _manifest(repo, after=after, path=path)
    archive = _zip(tmp_path, manifest, payload=after, path=path)
    coordinator = dp.DevelopmentPackageCoordinator(
        repository_root=repo,
        storage_root=tmp_path / "store",
    )
    with pytest.raises(dp.DevelopmentPackageError) as captured:
        asyncio.run(
            coordinator.create_task_from_stream(
                _stream(archive),
                request_id=uuid4(),
                session=_identity(),
                archive_name=archive.name,
                content_type="application/zip",
                content_length=archive.stat().st_size,
            )
        )
    assert captured.value.code == "DEVELOPMENT_PACKAGE_PROTECTED_PATH"


def test_regression_clean_package_applies_and_rolls_back(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    before = (repo / "src/example.py").read_bytes()
    after = b"VALUE = 2\n"
    archive = _zip(tmp_path, _manifest(repo, after=after), payload=after)
    coordinator = dp.DevelopmentPackageCoordinator(
        repository_root=repo,
        storage_root=tmp_path / "store",
    )
    identity = _identity()
    task = asyncio.run(
        coordinator.create_task_from_stream(
            _stream(archive),
            request_id=uuid4(),
            session=identity,
            archive_name=archive.name,
            content_type="application/zip",
            content_length=archive.stat().st_size,
        )
    )
    assert task.state is TaskState.AWAITING_APPROVAL
    baseline = frozenset({"FAILED tests/unit/test_constitution.py::known"})
    monkeypatch.setattr(
        dp,
        "_pytest",
        lambda root, targets=(): dp._PytestResult(1, "", baseline),
    )
    approved = _approve(coordinator, task, identity)
    assert approved.state is TaskState.EXECUTING
    finished = _wait(coordinator, task.task_id)
    assert finished.state is TaskState.COMPLETED
    assert (repo / "src/example.py").read_bytes() == after
    receipt = coordinator.get_receipt(task.task_id)
    assert receipt.verified is True
    evidence = receipt.results[0].evidence[0].attributes
    assert evidence["llm_used"] is False
    assert evidence["new_regression_nodes"] == []
    rolled = coordinator.rollback_task(task.task_id, identity)
    assert rolled.state is TaskState.ROLLED_BACK
    assert (repo / "src/example.py").read_bytes() == before


def test_new_regression_blocks_live_application(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    before = (repo / "src/example.py").read_bytes()
    after = b"VALUE = 3\n"
    archive = _zip(tmp_path, _manifest(repo, after=after), payload=after)
    coordinator = dp.DevelopmentPackageCoordinator(repository_root=repo, storage_root=tmp_path / "store")
    identity = _identity()
    task = asyncio.run(
        coordinator.create_task_from_stream(
            _stream(archive),
            request_id=uuid4(),
            session=identity,
            archive_name=archive.name,
            content_type="application/zip",
            content_length=archive.stat().st_size,
        )
    )
    calls = iter(
        [
            dp._PytestResult(1, "", frozenset({"FAILED tests/a.py::known"})),
            dp._PytestResult(1, "", frozenset({"FAILED tests/a.py::known", "FAILED tests/b.py::new"})),
        ]
    )
    monkeypatch.setattr(dp, "_pytest", lambda root, targets=(): next(calls))
    _approve(coordinator, task, identity)
    finished = _wait(coordinator, task.task_id)
    assert finished.state is TaskState.FAILED
    assert finished.results[0].error_code == "DEVELOPMENT_PACKAGE_NEW_REGRESSION"
    assert (repo / "src/example.py").read_bytes() == before


def test_pytest_exit_four_blocks_live_application(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    before = (repo / "src/example.py").read_bytes()
    after = b"VALUE = 4\n"
    archive = _zip(tmp_path, _manifest(repo, after=after), payload=after)
    coordinator = dp.DevelopmentPackageCoordinator(repository_root=repo, storage_root=tmp_path / "store")
    identity = _identity()
    task = asyncio.run(
        coordinator.create_task_from_stream(
            _stream(archive),
            request_id=uuid4(),
            session=identity,
            archive_name=archive.name,
            content_type="application/zip",
            content_length=archive.stat().st_size,
        )
    )
    monkeypatch.setattr(dp, "_pytest", lambda root, targets=(): dp._PytestResult(4, "usage error", frozenset()))
    _approve(coordinator, task, identity)
    finished = _wait(coordinator, task.task_id)
    assert finished.state is TaskState.FAILED
    assert finished.results[0].error_code == "DEVELOPMENT_PACKAGE_BASELINE_CONTROLLER_FAILURE"
    assert (repo / "src/example.py").read_bytes() == before


def test_manifest_delete_path_rejects_ntfs_stream_syntax():
    with pytest.raises(ValueError):
        dp.DevelopmentPackageFile(
            path="src/example.py:evil",
            operation="delete",
            before_sha256="0" * 64,
        )


def test_symlinked_live_target_is_rejected(tmp_path):
    repo = _repo(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("VALUE = 1\n", encoding="utf-8")
    link = repo / "src" / "link.py"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    with pytest.raises(dp.DevelopmentPackageError) as captured:
        dp._target_path(repo, "src/link.py")
    assert captured.value.code == "DEVELOPMENT_PACKAGE_SYMLINK_TARGET_PROHIBITED"


def test_sensitive_control_plane_path_requires_manifest_flag(tmp_path):
    repo = _repo(tmp_path)
    path = "src/nexuss/api/app.py"
    live = repo / path
    live.parent.mkdir(parents=True, exist_ok=True)
    live.write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "api")
    after = b"VALUE = 2\n"
    manifest = _manifest(repo, after=after, path=path)
    archive = _zip(tmp_path, manifest, payload=after, path=path)
    coordinator = dp.DevelopmentPackageCoordinator(repository_root=repo, storage_root=tmp_path / "store")
    with pytest.raises(dp.DevelopmentPackageError) as captured:
        asyncio.run(
            coordinator.create_task_from_stream(
                _stream(archive),
                request_id=uuid4(),
                session=_identity(),
                archive_name=archive.name,
                content_type="application/zip",
                content_length=archive.stat().st_size,
            )
        )
    assert captured.value.code == "DEVELOPMENT_PACKAGE_TRUST_BOUNDARY_FLAG_REQUIRED"


def test_undeclared_payload_file_is_rejected(tmp_path):
    repo = _repo(tmp_path)
    after = b"VALUE = 2\n"
    manifest = _manifest(repo, after=after)
    archive = tmp_path / "package.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("NEXUSS-DEVELOPMENT-MANIFEST.json", json.dumps(manifest))
        z.writestr("payload/src/example.py", after)
        z.writestr("payload/src/undeclared.py", b"VALUE = 999\n")
    coordinator = dp.DevelopmentPackageCoordinator(repository_root=repo, storage_root=tmp_path / "store")
    with pytest.raises(dp.DevelopmentPackageError) as captured:
        asyncio.run(
            coordinator.create_task_from_stream(
                _stream(archive),
                request_id=uuid4(),
                session=_identity(),
                archive_name=archive.name,
                content_type="application/zip",
                content_length=archive.stat().st_size,
            )
        )
    assert captured.value.code == "DEVELOPMENT_PACKAGE_UNDECLARED_PAYLOAD"


def test_invalid_focused_test_is_rejected_safely(tmp_path):
    repo = _repo(tmp_path)
    after = b"VALUE = 2\n"
    manifest = _manifest(repo, after=after)
    manifest["focused_tests"] = ["--maxfail=1"]
    archive = _zip(tmp_path, manifest, payload=after)
    coordinator = dp.DevelopmentPackageCoordinator(repository_root=repo, storage_root=tmp_path / "store")
    with pytest.raises(dp.DevelopmentPackageError) as captured:
        asyncio.run(
            coordinator.create_task_from_stream(
                _stream(archive),
                request_id=uuid4(),
                session=_identity(),
                archive_name=archive.name,
                content_type="application/zip",
                content_length=archive.stat().st_size,
            )
        )
    assert captured.value.code == "DEVELOPMENT_PACKAGE_FOCUSED_TEST_INVALID"


def test_add_operation_rejects_existing_live_target(tmp_path):
    repo = _repo(tmp_path)
    after = b"VALUE = 7\n"
    manifest = _manifest(repo, after=after)
    manifest["files"][0] = {
        "path": "src/example.py",
        "operation": "add",
        "before_sha256": None,
        "sha256": hashlib.sha256(after).hexdigest(),
        "size_bytes": len(after),
    }
    archive = _zip(tmp_path, manifest, payload=after)
    coordinator = dp.DevelopmentPackageCoordinator(repository_root=repo, storage_root=tmp_path / "store")
    with pytest.raises(dp.DevelopmentPackageError) as captured:
        asyncio.run(
            coordinator.create_task_from_stream(
                _stream(archive),
                request_id=uuid4(),
                session=_identity(),
                archive_name=archive.name,
                content_type="application/zip",
                content_length=archive.stat().st_size,
            )
        )
    assert captured.value.code == "DEVELOPMENT_PACKAGE_ADD_PATH_EXISTS"
