"""Immutable managed repository snapshots from authenticated GitHub ZIP archives."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from threading import RLock
from typing import Protocol

from nexuss.connectors.github.models import GitHubRepository
from nexuss.connectors.github.operation_models import (
    GitHubCommitSummary,
    RepositorySelection,
    RepositorySnapshot,
)

_MAX_ARCHIVE_BYTES = 100_000_000
_MAX_EXPANDED_BYTES = 750_000_000
_MAX_ENTRIES = 25_000
_MAX_SINGLE_FILE = 100_000_000
_MAX_RATIO = 2_000.0
_RETENTION = timedelta(days=7)


class RepositoryArchiveApi(Protocol):
    def get_repository(self, owner: str, repository: str) -> GitHubRepository: ...

    def resolve_commit(
        self,
        owner: str,
        repository: str,
        ref: str,
    ) -> GitHubCommitSummary: ...

    def download_repository_zipball(
        self,
        owner: str,
        repository: str,
        commit_sha: str,
        *,
        max_bytes: int,
    ) -> bytes: ...


class RepositoryWorkspaceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class GitHubRepositoryWorkspace:
    """Create immutable local snapshots without invoking repository code."""

    def __init__(self, root: Path) -> None:
        self._root = root.expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self.cleanup_stale()

    @classmethod
    def from_environment(cls) -> GitHubRepositoryWorkspace:
        local_data = (
            os.getenv("LOCALAPPDATA")
            or os.getenv("XDG_DATA_HOME")
            or str(Path.home() / ".local" / "share")
        )
        return cls(Path(local_data) / "Nexuss" / "github-workspace" / "snapshots")

    def create_snapshot(
        self,
        api: RepositoryArchiveApi,
        selection: RepositorySelection,
        *,
        account_login: str,
        now: datetime | None = None,
    ) -> RepositorySnapshot:
        observed_at = now or datetime.now(UTC)
        owner, repository_name = selection.repository_full_name.split("/", 1)
        repository = api.get_repository(owner, repository_name)
        if repository.disabled:
            raise RepositoryWorkspaceError(
                "GITHUB_WORKSPACE_REPOSITORY_DISABLED",
                "Disabled repositories cannot enter a managed workspace.",
            )
        commit = api.resolve_commit(owner, repository_name, selection.requested_ref)
        destination = self._destination(repository.repository_id, commit.sha)
        receipt_path = destination / "NEXUSS-SNAPSHOT.json"

        with self._lock:
            if receipt_path.is_file():
                snapshot = RepositorySnapshot.model_validate_json(
                    receipt_path.read_text(encoding="utf-8")
                )
                if (
                    snapshot.repository_id == repository.repository_id
                    and snapshot.resolved_commit_sha == commit.sha
                    and Path(snapshot.workspace_root).resolve() == destination
                ):
                    return snapshot
                raise RepositoryWorkspaceError(
                    "GITHUB_WORKSPACE_SNAPSHOT_COLLISION",
                    "An existing workspace snapshot failed identity verification.",
                )

            archive = api.download_repository_zipball(
                owner,
                repository_name,
                commit.sha,
                max_bytes=_MAX_ARCHIVE_BYTES,
            )
            if not archive or len(archive) > _MAX_ARCHIVE_BYTES:
                raise RepositoryWorkspaceError(
                    "GITHUB_WORKSPACE_ARCHIVE_SIZE_INVALID",
                    "The repository archive is empty or exceeds the snapshot limit.",
                )
            archive_sha = hashlib.sha256(archive).hexdigest()
            temporary = Path(
                tempfile.mkdtemp(
                    prefix="nexuss-github-snapshot-",
                    dir=self._root,
                )
            ).resolve()
            try:
                files, total_bytes, manifest_sha = self._extract_archive(
                    archive,
                    temporary,
                )
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(temporary, destination)
                snapshot = RepositorySnapshot(
                    account_login=account_login,
                    repository_id=repository.repository_id,
                    repository_full_name=repository.full_name,
                    requested_ref=selection.requested_ref,
                    resolved_commit_sha=commit.sha,
                    archive_sha256=archive_sha,
                    manifest_sha256=manifest_sha,
                    workspace_root=str(destination),
                    file_count=files,
                    total_bytes=total_bytes,
                    private_repository=repository.private,
                    observed_at=observed_at,
                )
                receipt_path.write_text(
                    snapshot.model_dump_json(indent=2),
                    encoding="utf-8",
                )
                self._make_snapshot_read_only(destination, receipt_path)
                return snapshot
            except Exception:
                shutil.rmtree(temporary, ignore_errors=True)
                raise

    def get_snapshot(self, snapshot_id) -> RepositorySnapshot:
        for receipt in self._root.glob("*/*/NEXUSS-SNAPSHOT.json"):
            try:
                snapshot = RepositorySnapshot.model_validate_json(
                    receipt.read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                continue
            if snapshot.snapshot_id == snapshot_id:
                return snapshot
        raise RepositoryWorkspaceError(
            "GITHUB_WORKSPACE_SNAPSHOT_NOT_FOUND",
            "The managed repository snapshot was not found.",
        )

    def cleanup_stale(self, *, now: datetime | None = None) -> int:
        checked_at = now or datetime.now(UTC)
        cutoff = checked_at - _RETENTION
        removed = 0
        for receipt in self._root.glob("*/*/NEXUSS-SNAPSHOT.json"):
            try:
                modified = datetime.fromtimestamp(
                    receipt.stat().st_mtime,
                    tz=UTC,
                )
            except OSError:
                continue
            if modified < cutoff:
                self._make_tree_writable(receipt.parent)
                shutil.rmtree(receipt.parent, ignore_errors=True)
                removed += 1
        return removed

    def _destination(self, repository_id: int, commit_sha: str) -> Path:
        return (self._root / str(repository_id) / commit_sha).resolve()

    @staticmethod
    def _normalize_member(name: str) -> PurePosixPath:
        normalized = name.replace("\\", "/")
        path = PurePosixPath(normalized)
        if (
            not normalized
            or "\x00" in normalized
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
            or (path.parts and ":" in path.parts[0])
        ):
            raise RepositoryWorkspaceError(
                "GITHUB_WORKSPACE_ARCHIVE_PATH_INVALID",
                "The repository archive contains an unsafe path.",
            )
        return path

    def _extract_archive(
        self,
        archive_bytes: bytes,
        destination: Path,
    ) -> tuple[int, int, str]:
        archive_path = destination / "repository.zip"
        archive_path.write_bytes(archive_bytes)
        entries: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
        total_expanded = 0
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            if len(infos) > _MAX_ENTRIES:
                raise RepositoryWorkspaceError(
                    "GITHUB_WORKSPACE_ENTRY_LIMIT",
                    "The repository archive exceeds the file-count limit.",
                )
            normalized = [
                (info, self._normalize_member(info.filename))
                for info in infos
                if not info.is_dir()
            ]
            roots = {path.parts[0] for _, path in normalized if path.parts}
            if len(roots) != 1:
                raise RepositoryWorkspaceError(
                    "GITHUB_WORKSPACE_ARCHIVE_ROOT_INVALID",
                    "The repository archive does not have one GitHub root directory.",
                )
            root = next(iter(roots))
            seen: set[str] = set()
            for info, path in normalized:
                if len(path.parts) < 2 or path.parts[0] != root:
                    continue
                relative = PurePosixPath(*path.parts[1:])
                key = relative.as_posix().casefold()
                if key in seen:
                    raise RepositoryWorkspaceError(
                        "GITHUB_WORKSPACE_PATH_COLLISION",
                        "The repository archive contains colliding paths.",
                    )
                seen.add(key)
                unix_mode = (info.external_attr >> 16) & 0o170000
                if unix_mode == stat.S_IFLNK:
                    raise RepositoryWorkspaceError(
                        "GITHUB_WORKSPACE_SYMLINK_DENIED",
                        "Repository symlinks are not materialized in this workspace stage.",
                    )
                if info.file_size > _MAX_SINGLE_FILE:
                    raise RepositoryWorkspaceError(
                        "GITHUB_WORKSPACE_FILE_SIZE_LIMIT",
                        "A repository file exceeds the workspace limit.",
                    )
                total_expanded += info.file_size
                if total_expanded > _MAX_EXPANDED_BYTES:
                    raise RepositoryWorkspaceError(
                        "GITHUB_WORKSPACE_EXPANDED_SIZE_LIMIT",
                        "The repository archive exceeds the expanded-size limit.",
                    )
                if info.file_size and info.compress_size:
                    ratio = info.file_size / info.compress_size
                    if ratio > _MAX_RATIO:
                        raise RepositoryWorkspaceError(
                            "GITHUB_WORKSPACE_COMPRESSION_RATIO_LIMIT",
                            "The repository archive has a suspicious compression ratio.",
                        )
                entries.append((info, relative))

            manifest: list[dict[str, object]] = []
            for info, relative in sorted(entries, key=lambda item: item[1].as_posix()):
                target = (destination / relative.as_posix()).resolve()
                try:
                    target.relative_to(destination)
                except ValueError as exc:
                    raise RepositoryWorkspaceError(
                        "GITHUB_WORKSPACE_PATH_ESCAPE",
                        "A repository file escaped the managed workspace.",
                    ) from exc
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix(target.suffix + ".nexuss-tmp")
                digest = hashlib.sha256()
                written = 0
                with archive.open(info) as source, temporary.open("xb") as output:
                    while True:
                        chunk = source.read(65_536)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > info.file_size or written > _MAX_SINGLE_FILE:
                            raise RepositoryWorkspaceError(
                                "GITHUB_WORKSPACE_FILE_SIZE_CHANGED",
                                "A repository file exceeded its declared size.",
                            )
                        digest.update(chunk)
                        output.write(chunk)
                if written != info.file_size:
                    raise RepositoryWorkspaceError(
                        "GITHUB_WORKSPACE_FILE_SIZE_MISMATCH",
                        "A repository file failed size verification.",
                    )
                os.replace(temporary, target)
                manifest.append(
                    {
                        "path": relative.as_posix(),
                        "size_bytes": written,
                        "sha256": digest.hexdigest(),
                    }
                )
        archive_path.unlink(missing_ok=True)
        manifest_sha = hashlib.sha256(
            json.dumps(
                manifest,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        return len(entries), total_expanded, manifest_sha

    @staticmethod
    def _make_snapshot_read_only(root: Path, receipt_path: Path) -> None:
        for path in root.rglob("*"):
            if path == receipt_path:
                continue
            try:
                if path.is_file():
                    path.chmod(stat.S_IREAD)
            except OSError:
                continue

    @staticmethod
    def _make_tree_writable(root: Path) -> None:
        for path in root.rglob("*"):
            try:
                if path.is_file():
                    path.chmod(stat.S_IREAD | stat.S_IWRITE)
            except OSError:
                continue
