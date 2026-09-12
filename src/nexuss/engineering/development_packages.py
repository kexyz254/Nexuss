"""P6.13 approved development-package intake and deterministic application.

This module deliberately does not invoke an LLM.  It consumes a reviewed ZIP,
quarantines it with the existing archive security layer, validates an explicit
manifest, obtains exact-payload approval, validates the package in an isolated
copy of the current Nexuss worktree, and only then applies an atomic, backed-up
change set to the live repository.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
from collections.abc import AsyncIterable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nexuss.core.state_machine import validate_transition
from nexuss.domain.models import (
    ActionEvent,
    ActionReceipt,
    ApprovalChannel,
    ApprovalDecision,
    ApprovalDecisionKind,
    ApprovalRequest,
    ApprovalStatus,
    CapabilityResult,
    EvidenceRecord,
    IdentitySession,
    Intent,
    IntentKind,
    PlanStep,
    PolicyDecision,
    PolicyOutcome,
    RiskTier,
    StepStatus,
    TaskPlan,
    TaskState,
    TaskView,
)
from nexuss.engineering.archive_intake import (
    ArchiveIntakePolicy,
    ArchiveIntakeReceipt,
    SecureArchiveIntake,
)
from nexuss.engineering.errors import EngineeringError


_PACKAGE_FORMAT = "nexuss-development-package-v1"
_MAX_UPLOAD_BYTES = 50_000_000
_MAX_PACKAGE_FILES = 750
_MAX_FOCUSED_TESTS = 50
_APPROVAL_TTL = timedelta(minutes=20)
_SHA256_RE = r"^[0-9a-f]{64}$"

_HARD_DENY_PREFIXES = (
    ".git/",
    ".patch-backups/",
    ".venv/",
    "venv/",
    "node_modules/",
    "__pycache__/",
    "src/nexuss/constitution/",
)
_HARD_DENY_EXACT = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
        "credentials.json",
        "secrets.json",
        "token.json",
        "src/nexuss/connectors/vault.py",
        "src/nexuss/engineering/credentials.py",
    }
)
_HARD_DENY_SUFFIXES = frozenset(
    {".db", ".sqlite", ".sqlite3", ".pem", ".key", ".p12", ".pfx"}
)
_SENSITIVE_PATHS = frozenset(
    {
        "src/nexuss/core/policy.py",
        "src/nexuss/core/service.py",
        "src/nexuss/core/executor.py",
        "src/nexuss/api/app.py",
        "src/nexuss/engineering/prompt_build.py",
        "scripts/start_nexuss_p612.ps1",
        "pyproject.toml",
        "requirements.txt",
        "requirements-dev.txt",
        "package.json",
        "package-lock.json",
    }
)
_SENSITIVE_PREFIXES = (
    ".github/workflows/",
)
_WINDOWS_RESERVED = frozenset(
    {
        "aux", "con", "nul", "prn",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
    }
)
_COPY_EXCLUDED_PARTS = frozenset(
    {
        ".git",
        ".patch-backups",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "node_modules",
        ".venv",
        "venv",
        "target",
    }
)
_FAILURE_PREFIXES = ("FAILED", "ERROR")


class DevelopmentPackageError(RuntimeError):
    """Safe package workflow failure suitable for the API boundary."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
        safe_details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.safe_details = safe_details or {}


class DevelopmentPackageTaskNotFoundError(DevelopmentPackageError):
    pass


class DevelopmentPackageApprovalError(DevelopmentPackageError):
    pass


class DevelopmentPackageSessionError(DevelopmentPackageError):
    pass


class PackageOperation(StrEnum):
    ADD = "add"
    REPLACE = "replace"
    DELETE = "delete"


class DevelopmentPackageFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1, max_length=1_000)
    operation: PackageOperation
    before_sha256: str | None = Field(default=None, pattern=_SHA256_RE)
    sha256: str | None = Field(default=None, pattern=_SHA256_RE)
    size_bytes: int | None = Field(default=None, ge=0, le=50_000_000)

    @field_validator("path")
    @classmethod
    def validate_repo_path(cls, value: str) -> str:
        return _normalize_repo_path(value)

    @model_validator(mode="after")
    def validate_operation_contract(self) -> "DevelopmentPackageFile":
        if self.operation is PackageOperation.ADD:
            if self.before_sha256 is not None or self.sha256 is None:
                raise ValueError("add requires sha256 and forbids before_sha256")
        elif self.operation is PackageOperation.REPLACE:
            if self.before_sha256 is None or self.sha256 is None:
                raise ValueError("replace requires before_sha256 and sha256")
        elif self.operation is PackageOperation.DELETE:
            if self.before_sha256 is None or self.sha256 is not None:
                raise ValueError("delete requires before_sha256 and forbids sha256")
        return self


class DevelopmentPackageManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    format: Literal["nexuss-development-package-v1"] = _PACKAGE_FORMAT
    package_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,99}$")
    phase: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2_000)
    created_at: datetime
    requires_restart: bool = True
    trust_boundary_change: bool = False
    database_schema_changed: bool = False
    base_git_head: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    files: tuple[DevelopmentPackageFile, ...] = Field(
        min_length=1,
        max_length=_MAX_PACKAGE_FILES,
    )
    focused_tests: tuple[str, ...] = Field(default=(), max_length=_MAX_FOCUSED_TESTS)

    @model_validator(mode="after")
    def validate_paths_unique(self) -> "DevelopmentPackageManifest":
        normalized = [_normalize_repo_path(item.path) for item in self.files]
        if len(set(normalized)) != len(normalized):
            raise ValueError("development package contains duplicate file paths")
        return self


class DevelopmentPackageInspection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    package_sha256: str = Field(pattern=_SHA256_RE)
    archive_manifest_sha256: str = Field(pattern=_SHA256_RE)
    development_manifest_sha256: str = Field(pattern=_SHA256_RE)
    package_id: str
    phase: str
    title: str
    add_count: int = Field(ge=0)
    replace_count: int = Field(ge=0)
    delete_count: int = Field(ge=0)
    sensitive_paths: tuple[str, ...]
    base_git_head_match: bool
    target_hashes_match: bool
    security_findings: int = Field(ge=0)
    llm_used: bool = False
    credentials_exposed: bool = False


@dataclass
class _PackageContext:
    task: TaskView
    manifest: DevelopmentPackageManifest
    inspection: DevelopmentPackageInspection
    archive_receipt: ArchiveIntakeReceipt
    workflow_root: Path
    live_fingerprint_at_approval: str | None = None
    backup_root: Path | None = None


@dataclass(frozen=True)
class _PytestResult:
    returncode: int
    output: str
    failure_nodes: frozenset[str]


def _normalize_repo_path(value: str) -> str:
    converted = value.replace("\\", "/").strip()
    path = PurePosixPath(converted)
    if not converted or converted.startswith("/") or not path.parts:
        raise ValueError(f"invalid repository-relative path: {value!r}")
    normalized_parts: list[str] = []
    for part in path.parts:
        if part in {"", ".", ".."}:
            raise ValueError(f"invalid repository-relative path: {value!r}")
        if ":" in part or any(ord(character) < 32 for character in part):
            raise ValueError(f"invalid repository-relative path: {value!r}")
        if part.rstrip(" .") != part:
            raise ValueError(f"invalid repository-relative path: {value!r}")
        basename = part.split(".", 1)[0].casefold()
        if basename in _WINDOWS_RESERVED:
            raise ValueError(f"invalid repository-relative path: {value!r}")
        normalized_parts.append(part)
    return PurePosixPath(*normalized_parts).as_posix()


def _target_path(root: Path, relative: str) -> Path:
    """Resolve one repository-relative target without following a symlink escape."""
    normalized = _normalize_repo_path(relative)
    root_resolved = root.resolve()
    current = root_resolved
    for part in PurePosixPath(normalized).parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise DevelopmentPackageError(
                "DEVELOPMENT_PACKAGE_SYMLINK_TARGET_PROHIBITED",
                "Development packages may not target symlinked repository paths.",
                safe_details={"path": normalized},
            )
    resolved = current.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise DevelopmentPackageError(
            "DEVELOPMENT_PACKAGE_TARGET_ESCAPE",
            "A development-package target escaped the repository boundary.",
            safe_details={"path": normalized},
        ) from exc
    return current


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(payload: object) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return _sha256_bytes(raw)


def _failure_nodes(output: str) -> frozenset[str]:
    nodes: set[str] = set()
    for raw in output.splitlines():
        line = raw.strip()
        for prefix in _FAILURE_PREFIXES:
            marker = prefix + " "
            if line.startswith(marker):
                node = line[len(marker) :].split(" - ", 1)[0].strip()
                if node:
                    nodes.add(f"{prefix} {node}")
    return frozenset(nodes)


def _run(
    argv: list[str],
    cwd: Path,
    *,
    timeout: int = 1_800,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        capture_output=True,
        text=True,
        shell=False,
        check=False,
        timeout=timeout,
    )


def _pytest(root: Path, targets: Iterable[str] = ()) -> _PytestResult:
    completed = _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--import-mode=importlib",
            "-q",
            "-p",
            "no:cacheprovider",
            *targets,
        ],
        root,
    )
    output = completed.stdout + (
        "\nSTDERR:\n" + completed.stderr if completed.stderr else ""
    )
    return _PytestResult(
        returncode=completed.returncode,
        output=output,
        failure_nodes=_failure_nodes(output),
    )


def _safe_visible_file(relative: Path) -> bool:
    if any(part.casefold() in _COPY_EXCLUDED_PARTS for part in relative.parts):
        return False
    if relative.name.casefold() in {
        ".env",
        ".env.local",
        ".env.production",
        "credentials.json",
        "secrets.json",
        "token.json",
    }:
        return False
    if relative.suffix.casefold() in _HARD_DENY_SUFFIXES:
        return False
    return True


def _git_visible_files(repo: Path) -> tuple[str, ...]:
    completed = subprocess.run(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        cwd=repo,
        capture_output=True,
        shell=False,
        check=False,
    )
    if completed.returncode != 0:
        raise DevelopmentPackageError(
            "DEVELOPMENT_PACKAGE_GIT_ENUMERATION_FAILED",
            "Nexuss could not enumerate the current repository safely.",
            safe_details={"returncode": completed.returncode},
        )
    result: list[str] = []
    for raw in completed.stdout.split(b"\x00"):
        if not raw:
            continue
        relative = Path(raw.decode("utf-8", errors="strict"))
        if _safe_visible_file(relative):
            result.append(relative.as_posix())
    return tuple(sorted(set(result)))


def _repository_fingerprint(repo: Path) -> str:
    payload: list[tuple[str, str]] = []
    for relative in _git_visible_files(repo):
        path = repo / relative
        if path.is_symlink():
            raise DevelopmentPackageError(
                "DEVELOPMENT_PACKAGE_REPOSITORY_SYMLINK_PROHIBITED",
                "The Git-visible repository contains a symlink and cannot be fingerprinted safely for package application.",
                safe_details={"path": relative},
            )
        if path.is_file():
            payload.append((relative, _sha256_file(path)))
    return _canonical_sha256(payload)


def _copy_current_repository(repo: Path, candidate: Path) -> None:
    candidate.mkdir(parents=True, exist_ok=False)
    for relative in _git_visible_files(repo):
        source = repo / relative
        if source.is_symlink():
            raise DevelopmentPackageError(
                "DEVELOPMENT_PACKAGE_REPOSITORY_SYMLINK_PROHIBITED",
                "The Git-visible repository contains a symlink and cannot be copied safely for package validation.",
                safe_details={"path": relative},
            )
        if not source.is_file():
            continue
        destination = candidate / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    commands = [
        ["git", "init", "-b", "main"],
        ["git", "config", "user.name", "Nexuss Package Validator"],
        ["git", "config", "user.email", "nexuss-package@localhost"],
        ["git", "add", "-A"],
        ["git", "commit", "-m", "Nexuss development-package validation baseline"],
    ]
    for argv in commands:
        completed = _run(argv, candidate, timeout=120)
        if completed.returncode != 0:
            raise DevelopmentPackageError(
                "DEVELOPMENT_PACKAGE_CANDIDATE_GIT_FAILED",
                "Nexuss could not initialize the isolated validation repository.",
                safe_details={"command": argv[:2], "returncode": completed.returncode},
            )


def _path_is_hard_denied(relative: str) -> bool:
    normalized = relative.casefold()
    if normalized in {item.casefold() for item in _HARD_DENY_EXACT}:
        return True
    if any(normalized.startswith(prefix.casefold()) for prefix in _HARD_DENY_PREFIXES):
        return True
    return Path(relative).suffix.casefold() in _HARD_DENY_SUFFIXES


def _path_is_sensitive(relative: str) -> bool:
    normalized = relative.casefold()
    return (
        normalized in {item.casefold() for item in _SENSITIVE_PATHS}
        or any(normalized.startswith(prefix.casefold()) for prefix in _SENSITIVE_PREFIXES)
    )


def _safe_focused_test(value: str) -> str:
    candidate = value.strip().replace("\\", "/")
    path_part = candidate.split("::", 1)[0]
    if (
        not candidate
        or not path_part.startswith("tests/")
        or not path_part.endswith(".py")
        or ".." in PurePosixPath(path_part).parts
        or candidate.startswith("-")
        or any(token in candidate for token in (";", "|", "&&", "`", "$(`"))
    ):
        raise ValueError(f"invalid focused pytest target: {value!r}")
    return candidate


class DevelopmentPackageCoordinator:
    """Own approved ZIP-development tasks as a deterministic local authority."""

    def __init__(
        self,
        *,
        repository_root: Path,
        storage_root: Path,
        intake: SecureArchiveIntake | None = None,
    ) -> None:
        self.repository_root = repository_root.expanduser().resolve()
        self.storage_root = storage_root.expanduser().resolve()
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self._intake = intake or SecureArchiveIntake(
            ArchiveIntakePolicy(
                max_archive_bytes=_MAX_UPLOAD_BYTES,
                max_entries=5_000,
                max_total_uncompressed_bytes=250_000_000,
                max_file_uncompressed_bytes=25_000_000,
                strip_single_root=True,
                reject_nested_archives=True,
                reject_workflow_files=False,
                reject_secret_filenames=True,
            )
        )
        self._lock = threading.RLock()
        self._contexts: dict[UUID, _PackageContext] = {}
        self._request_index: dict[UUID, UUID] = {}
        self._receipt_history: dict[UUID, list[ActionReceipt]] = {}
        self._load_durable_tasks()

    @classmethod
    def from_environment(cls) -> "DevelopmentPackageCoordinator":
        repo = Path(__file__).resolve().parents[3]
        local = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local) if local else Path.home() / ".nexuss"
        return cls(
            repository_root=repo,
            storage_root=base / "Nexuss" / "development-packages",
        )

    async def create_task_from_stream(
        self,
        stream: AsyncIterable[bytes],
        *,
        request_id: UUID,
        session: IdentitySession,
        archive_name: str,
        content_type: str,
        content_length: int | None,
    ) -> TaskView:
        if not session.authenticated:
            raise DevelopmentPackageSessionError(
                "DEVELOPMENT_PACKAGE_SESSION_REQUIRED",
                "An authenticated local session is required.",
                status_code=401,
            )
        if not archive_name.casefold().endswith(".zip"):
            raise DevelopmentPackageError(
                "DEVELOPMENT_PACKAGE_FILENAME_INVALID",
                "The attached development package must have a .zip filename.",
                status_code=400,
            )
        if content_type.casefold().split(";", 1)[0].strip() not in {
            "application/zip",
            "application/x-zip-compressed",
            "application/octet-stream",
        }:
            raise DevelopmentPackageError(
                "DEVELOPMENT_PACKAGE_CONTENT_TYPE_INVALID",
                "The development package must use a ZIP-compatible content type.",
                status_code=415,
            )
        if content_length is not None and (
            content_length <= 0 or content_length > _MAX_UPLOAD_BYTES
        ):
            raise DevelopmentPackageError(
                "DEVELOPMENT_PACKAGE_UPLOAD_SIZE_INVALID",
                "The development package upload has an invalid size.",
                status_code=413,
            )

        with self._lock:
            existing = self._request_index.get(request_id)
            if existing is not None:
                return self.get_task(existing)

        task_id = uuid5(NAMESPACE_URL, f"nexuss:development-package:{request_id}")
        workflow_root = self.storage_root / "tasks" / str(task_id)
        if workflow_root.exists():
            raise DevelopmentPackageError(
                "DEVELOPMENT_PACKAGE_TASK_COLLISION",
                "This package request is already being processed.",
            )
        workflow_root.mkdir(parents=True, exist_ok=False)
        upload_path = workflow_root / "upload.zip"
        received = 0
        try:
            with upload_path.open("xb") as destination:
                async for chunk in stream:
                    if not chunk:
                        continue
                    received += len(chunk)
                    if received > _MAX_UPLOAD_BYTES:
                        raise DevelopmentPackageError(
                            "DEVELOPMENT_PACKAGE_UPLOAD_TOO_LARGE",
                            "The ZIP upload exceeds the 50 MB development-package limit.",
                            status_code=413,
                        )
                    destination.write(chunk)
            if received == 0:
                raise DevelopmentPackageError(
                    "DEVELOPMENT_PACKAGE_UPLOAD_EMPTY",
                    "The ZIP upload is empty.",
                    status_code=400,
                )

            archive_receipt = self._intake.intake(
                upload_path,
                self.storage_root / "quarantine",
            )
            context = self._prepare_context(
                task_id=task_id,
                request_id=request_id,
                session=session,
                workflow_root=workflow_root,
                archive_receipt=archive_receipt,
            )
            with self._lock:
                self._contexts[task_id] = context
                self._request_index[request_id] = task_id
                self._persist_context(context)
                self._record_receipt(context.task)
            return context.task.model_copy(deep=True)
        except Exception:
            if task_id not in self._contexts:
                shutil.rmtree(workflow_root, ignore_errors=True)
            raise

    def contains_task(self, task_id: UUID) -> bool:
        with self._lock:
            return task_id in self._contexts

    def get_task(self, task_id: UUID) -> TaskView:
        with self._lock:
            context = self._contexts.get(task_id)
            if context is None:
                raise DevelopmentPackageTaskNotFoundError(
                    "DEVELOPMENT_PACKAGE_TASK_NOT_FOUND",
                    "Development package task not found.",
                    status_code=404,
                )
            return context.task.model_copy(deep=True)

    def get_receipt(self, task_id: UUID) -> ActionReceipt:
        with self._lock:
            history = self._receipt_history.get(task_id)
            if not history:
                raise DevelopmentPackageTaskNotFoundError(
                    "DEVELOPMENT_PACKAGE_RECEIPT_NOT_FOUND",
                    "Development package receipt not found.",
                    status_code=404,
                )
            return history[-1].model_copy(deep=True)

    def get_receipt_history(self, task_id: UUID) -> tuple[ActionReceipt, ...]:
        with self._lock:
            history = self._receipt_history.get(task_id)
            if history is None:
                raise DevelopmentPackageTaskNotFoundError(
                    "DEVELOPMENT_PACKAGE_RECEIPT_NOT_FOUND",
                    "Development package receipt history not found.",
                    status_code=404,
                )
            return tuple(item.model_copy(deep=True) for item in history)

    def approve_task(
        self,
        task_id: UUID,
        decision: ApprovalDecision,
        session: IdentitySession,
        *,
        approval_channel: ApprovalChannel,
    ) -> TaskView:
        if not session.authenticated:
            raise DevelopmentPackageSessionError(
                "DEVELOPMENT_PACKAGE_SESSION_REQUIRED",
                "An authenticated local session is required.",
                status_code=401,
            )
        if approval_channel is not ApprovalChannel.DESKTOP:
            raise DevelopmentPackageApprovalError(
                "DEVELOPMENT_PACKAGE_DESKTOP_APPROVAL_REQUIRED",
                "Development-package application currently requires local desktop approval.",
            )

        with self._lock:
            context = self._require_context(task_id, session.session_id)
            task = context.task
            approval = task.approval
            if task.state is not TaskState.AWAITING_APPROVAL or approval is None:
                raise DevelopmentPackageApprovalError(
                    "DEVELOPMENT_PACKAGE_APPROVAL_NOT_PENDING",
                    "The development-package approval is not pending.",
                )
            now = datetime.now(UTC)
            if approval.expires_at <= now:
                updated_approval = approval.model_copy(update={"status": ApprovalStatus.EXPIRED})
                context.task = task.model_copy(update={"approval": updated_approval, "updated_at": now})
                self._persist_context(context)
                raise DevelopmentPackageApprovalError(
                    "DEVELOPMENT_PACKAGE_APPROVAL_EXPIRED",
                    "The development-package approval expired.",
                )
            if (
                decision.approval_id != approval.approval_id
                or decision.approval_token != approval.approval_token
                or decision.payload_sha256 != approval.payload_sha256
            ):
                raise DevelopmentPackageApprovalError(
                    "DEVELOPMENT_PACKAGE_APPROVAL_PAYLOAD_MISMATCH",
                    "The approval does not match the exact development-package payload.",
                )

            events = list(task.events)
            if decision.decision is ApprovalDecisionKind.REJECT:
                validate_transition(TaskState.AWAITING_APPROVAL, TaskState.DENIED)
                denied_at = datetime.now(UTC)
                updated_approval = approval.model_copy(update={"status": ApprovalStatus.REJECTED})
                self._append_event(
                    task_id,
                    events,
                    TaskState.DENIED,
                    "development_package_rejected",
                    "The reviewed development package was rejected. No repository file was modified.",
                    denied_at,
                )
                context.task = task.model_copy(
                    update={
                        "state": TaskState.DENIED,
                        "approval": updated_approval,
                        "events": events,
                        "updated_at": denied_at,
                    }
                )
                self._persist_context(context)
                self._record_receipt(context.task)
                return context.task.model_copy(deep=True)

            validate_transition(TaskState.AWAITING_APPROVAL, TaskState.APPROVED)
            approved_at = datetime.now(UTC)
            updated_approval = approval.model_copy(update={"status": ApprovalStatus.CONSUMED})
            self._append_event(
                task_id,
                events,
                TaskState.APPROVED,
                "development_package_approved",
                "Exact package hash and manifest were approved for isolated validation.",
                approved_at,
            )
            validate_transition(TaskState.APPROVED, TaskState.EXECUTING)
            executing_at = datetime.now(UTC)
            self._append_event(
                task_id,
                events,
                TaskState.EXECUTING,
                "development_package_validation_started",
                "Nexuss started isolated baseline, package, and regression validation.",
                executing_at,
            )
            context.live_fingerprint_at_approval = _repository_fingerprint(self.repository_root)
            context.task = task.model_copy(
                update={
                    "state": TaskState.EXECUTING,
                    "approval": updated_approval,
                    "events": events,
                    "updated_at": executing_at,
                }
            )
            self._persist_context(context)
            self._record_receipt(context.task)

            worker = threading.Thread(
                target=self._run_approved_package,
                args=(task_id,),
                name=f"nexuss-package-{str(task_id)[:8]}",
                daemon=True,
            )
            worker.start()
            return context.task.model_copy(deep=True)

    def rollback_task(self, task_id: UUID, session: IdentitySession) -> TaskView:
        if not session.authenticated:
            raise DevelopmentPackageSessionError(
                "DEVELOPMENT_PACKAGE_SESSION_REQUIRED",
                "An authenticated local session is required.",
                status_code=401,
            )
        with self._lock:
            context = self._require_context(task_id, session.session_id)
            task = context.task
            if task.state is not TaskState.COMPLETED or context.backup_root is None:
                raise DevelopmentPackageError(
                    "DEVELOPMENT_PACKAGE_ROLLBACK_NOT_AVAILABLE",
                    "This development package does not have an available rollback.",
                )
            self._verify_live_matches_applied(context)
            events = list(task.events)
            validate_transition(TaskState.COMPLETED, TaskState.ROLLING_BACK)
            started = datetime.now(UTC)
            self._append_event(
                task_id,
                events,
                TaskState.ROLLING_BACK,
                "development_package_rollback_started",
                "Nexuss is restoring the package backup inside the live repository.",
                started,
            )
            context.task = task.model_copy(
                update={"state": TaskState.ROLLING_BACK, "events": events, "updated_at": started}
            )
            self._persist_context(context)

            try:
                self._restore_backup(context)
                validate_transition(TaskState.ROLLING_BACK, TaskState.ROLLED_BACK)
                finished = datetime.now(UTC)
                self._append_event(
                    task_id,
                    events,
                    TaskState.ROLLED_BACK,
                    "development_package_rollback_completed",
                    "The approved development package was undone from its recorded backup.",
                    finished,
                )
                context.task = context.task.model_copy(
                    update={
                        "state": TaskState.ROLLED_BACK,
                        "events": events,
                        "updated_at": finished,
                    }
                )
            except Exception as exc:
                validate_transition(TaskState.ROLLING_BACK, TaskState.FAILED)
                failed_at = datetime.now(UTC)
                self._append_event(
                    task_id,
                    events,
                    TaskState.FAILED,
                    "development_package_rollback_failed",
                    "Rollback could not be proven complete; manual review is required.",
                    failed_at,
                )
                context.task = context.task.model_copy(
                    update={"state": TaskState.FAILED, "events": events, "updated_at": failed_at}
                )
                self._persist_context(context)
                self._record_receipt(context.task)
                raise DevelopmentPackageError(
                    "DEVELOPMENT_PACKAGE_ROLLBACK_FAILED",
                    "The package rollback failed and requires manual review.",
                    safe_details={"error_type": type(exc).__name__},
                ) from exc

            self._persist_context(context)
            self._record_receipt(context.task)
            return context.task.model_copy(deep=True)

    def _prepare_context(
        self,
        *,
        task_id: UUID,
        request_id: UUID,
        session: IdentitySession,
        workflow_root: Path,
        archive_receipt: ArchiveIntakeReceipt,
    ) -> _PackageContext:
        if archive_receipt.security_findings:
            raise DevelopmentPackageError(
                "DEVELOPMENT_PACKAGE_SECURITY_FINDINGS",
                "The ZIP contains credential-like material and cannot be accepted.",
                status_code=422,
                safe_details={"finding_count": len(archive_receipt.security_findings)},
            )

        extracted = Path(archive_receipt.extracted_root)
        manifest_path = extracted / "NEXUSS-DEVELOPMENT-MANIFEST.json"
        if not manifest_path.is_file():
            raise DevelopmentPackageError(
                "DEVELOPMENT_PACKAGE_MANIFEST_MISSING",
                "NEXUSS-DEVELOPMENT-MANIFEST.json is required at the package root.",
                status_code=422,
            )
        try:
            raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = DevelopmentPackageManifest.model_validate(raw_manifest)
        except Exception as exc:
            raise DevelopmentPackageError(
                "DEVELOPMENT_PACKAGE_MANIFEST_INVALID",
                "The development-package manifest is invalid.",
                status_code=422,
                safe_details={"error_type": type(exc).__name__},
            ) from exc
        if manifest.database_schema_changed:
            raise DevelopmentPackageError(
                "DEVELOPMENT_PACKAGE_DATABASE_CHANGE_UNSUPPORTED",
                "P6.13 v1 does not apply database-schema-changing packages.",
                status_code=422,
            )

        sensitive: list[str] = []
        payload_paths: set[str] = set()
        for entry in manifest.files:
            relative = _normalize_repo_path(entry.path)
            if _path_is_hard_denied(relative):
                raise DevelopmentPackageError(
                    "DEVELOPMENT_PACKAGE_PROTECTED_PATH",
                    "The package targets a path that P6.13 will never modify.",
                    status_code=422,
                    safe_details={"path": relative},
                )
            if _path_is_sensitive(relative):
                sensitive.append(relative)
            if entry.operation is not PackageOperation.DELETE:
                payload_path = extracted / "payload" / relative
                if not payload_path.is_file():
                    raise DevelopmentPackageError(
                        "DEVELOPMENT_PACKAGE_PAYLOAD_MISSING",
                        "A manifest payload file is missing from the ZIP.",
                        status_code=422,
                        safe_details={"path": relative},
                    )
                actual = _sha256_file(payload_path)
                if actual != entry.sha256:
                    raise DevelopmentPackageError(
                        "DEVELOPMENT_PACKAGE_PAYLOAD_HASH_MISMATCH",
                        "A payload file does not match its declared SHA-256.",
                        status_code=422,
                        safe_details={"path": relative},
                    )
                if entry.size_bytes is not None and payload_path.stat().st_size != entry.size_bytes:
                    raise DevelopmentPackageError(
                        "DEVELOPMENT_PACKAGE_PAYLOAD_SIZE_MISMATCH",
                        "A payload file does not match its declared byte length.",
                        status_code=422,
                        safe_details={"path": relative},
                    )
                payload_paths.add(relative)

        if sensitive and not manifest.trust_boundary_change:
            raise DevelopmentPackageError(
                "DEVELOPMENT_PACKAGE_TRUST_BOUNDARY_FLAG_REQUIRED",
                "The package changes a sensitive control-plane path but does not declare trust_boundary_change=true.",
                status_code=422,
                safe_details={"paths": sorted(sensitive)},
            )

        actual_payload_paths: set[str] = set()
        payload_root = extracted / "payload"
        if payload_root.exists():
            for path in payload_root.rglob("*"):
                if path.is_file():
                    actual_payload_paths.add(path.relative_to(payload_root).as_posix())
        extras = sorted(actual_payload_paths - payload_paths)
        if extras:
            raise DevelopmentPackageError(
                "DEVELOPMENT_PACKAGE_UNDECLARED_PAYLOAD",
                "The ZIP contains payload files not declared by the manifest.",
                status_code=422,
                safe_details={"paths": extras[:20], "extra_count": len(extras)},
            )

        try:
            for item in manifest.focused_tests:
                _safe_focused_test(item)
        except ValueError as exc:
            raise DevelopmentPackageError(
                "DEVELOPMENT_PACKAGE_FOCUSED_TEST_INVALID",
                "The package declares an invalid focused pytest target.",
                status_code=422,
                safe_details={"error_type": type(exc).__name__},
            ) from exc

        base_git_head_match = True
        if manifest.base_git_head is not None:
            completed = _run(["git", "rev-parse", "HEAD"], self.repository_root, timeout=120)
            base_git_head_match = (
                completed.returncode == 0
                and completed.stdout.strip().casefold() == manifest.base_git_head.casefold()
            )
            if not base_git_head_match:
                raise DevelopmentPackageError(
                    "DEVELOPMENT_PACKAGE_BASE_GIT_HEAD_MISMATCH",
                    "The package was built for a different Nexuss Git base.",
                    status_code=409,
                )

        self._verify_target_preconditions(manifest, self.repository_root)
        manifest_sha = _canonical_sha256(manifest.model_dump(mode="json"))
        inspection = DevelopmentPackageInspection(
            package_sha256=archive_receipt.archive_sha256,
            archive_manifest_sha256=archive_receipt.manifest_sha256,
            development_manifest_sha256=manifest_sha,
            package_id=manifest.package_id,
            phase=manifest.phase,
            title=manifest.title,
            add_count=sum(1 for item in manifest.files if item.operation is PackageOperation.ADD),
            replace_count=sum(1 for item in manifest.files if item.operation is PackageOperation.REPLACE),
            delete_count=sum(1 for item in manifest.files if item.operation is PackageOperation.DELETE),
            sensitive_paths=tuple(sorted(sensitive)),
            base_git_head_match=base_git_head_match,
            target_hashes_match=True,
            security_findings=0,
            llm_used=False,
            credentials_exposed=False,
        )

        now = datetime.now(UTC)
        intent = Intent(
            kind=IntentKind.PREPARE_WORKSPACE,
            normalized_text=f"apply approved development package {manifest.package_id}",
            confidence=1.0,
            entities={"package_id": manifest.package_id, "phase": manifest.phase},
        )
        step = PlanStep(
            step_id=uuid5(NAMESPACE_URL, f"nexuss:{task_id}:engineering.package.apply"),
            order=1,
            capability_id="engineering.package.apply",
            risk_tier=RiskTier.HIGH,
            expected_evidence=[
                "development_package_receipt",
                "sha256_verification",
                "regression_verification",
                "rollback_backup",
            ],
            parameters={
                "package_id": manifest.package_id,
                "package_sha256": archive_receipt.archive_sha256,
                "development_manifest_sha256": manifest_sha,
                "file_count": len(manifest.files),
            },
            reversible=True,
        )
        plan = TaskPlan(
            plan_id=uuid5(NAMESPACE_URL, f"nexuss:{task_id}:development-package-plan"),
            task_id=task_id,
            intent=intent,
            steps=[step],
        )
        decision = PolicyDecision(
            step_id=step.step_id,
            capability_id=step.capability_id,
            outcome=PolicyOutcome.REQUIRE_APPROVAL,
            reason_code="APPROVED_DEVELOPMENT_PACKAGE_EXACT_PAYLOAD",
            explanation=(
                "Live source application is allowed only after exact local approval and isolated regression validation."
            ),
        )
        approval_payload = {
            "package_id": manifest.package_id,
            "phase": manifest.phase,
            "package_sha256": archive_receipt.archive_sha256,
            "development_manifest_sha256": manifest_sha,
            "files": [item.model_dump(mode="json") for item in manifest.files],
            "sensitive_paths": sorted(sensitive),
        }
        payload_sha = _canonical_sha256(approval_payload)
        preview_lines = [
            f"Package: {manifest.package_id} · {manifest.phase}",
            f"Title: {manifest.title}",
            f"ZIP SHA-256: {archive_receipt.archive_sha256}",
            f"Files: +{inspection.add_count} ~{inspection.replace_count} -{inspection.delete_count}",
            f"Focused tests: {len(manifest.focused_tests)}",
            f"Trust-boundary change: {'yes' if manifest.trust_boundary_change else 'no'}",
            "No LLM/API call will be used to apply this ZIP.",
        ]
        if sensitive:
            preview_lines.append("Sensitive paths: " + ", ".join(sorted(sensitive)))
        approval = ApprovalRequest(
            approval_id=uuid4(),
            task_id=task_id,
            capability_id=step.capability_id,
            status=ApprovalStatus.PENDING,
            action_title=f"Apply Nexuss development package {manifest.package_id}",
            action_summary=(
                "Validate this reviewed package in an isolated Nexuss copy, then atomically apply it only if it introduces zero new regression failures."
            ),
            exact_preview="\n".join(preview_lines),
            destination_label=str(self.repository_root),
            payload_sha256=payload_sha,
            approval_token=secrets.token_urlsafe(36),
            session_id=session.session_id,
            expires_at=now + _APPROVAL_TTL,
            risk_tier=RiskTier.HIGH,
            reversible=True,
            approval_channel=ApprovalChannel.DESKTOP,
        )
        events: list[ActionEvent] = []
        self._append_event(
            task_id,
            events,
            TaskState.RECEIVED,
            "development_package_received",
            "The ZIP was received into local quarantine; no repository write occurred.",
            now,
        )
        self._append_event(
            task_id,
            events,
            TaskState.PLANNED,
            "development_package_verified",
            "Manifest, package hashes, payload declarations, target preconditions, and security intake passed.",
            now,
        )
        self._append_event(
            task_id,
            events,
            TaskState.AWAITING_APPROVAL,
            "development_package_approval_required",
            "Exact desktop approval is required before isolated validation or live application begins.",
            now,
        )
        task = TaskView(
            task_id=task_id,
            request_id=request_id,
            user_session_id=session.session_id,
            state=TaskState.AWAITING_APPROVAL,
            intent=intent,
            plan=plan,
            policy_decisions=[decision],
            results=[],
            events=events,
            approval=approval,
            created_at=now,
            updated_at=now,
        )
        return _PackageContext(
            task=task,
            manifest=manifest,
            inspection=inspection,
            archive_receipt=archive_receipt,
            workflow_root=workflow_root,
        )

    def _run_approved_package(self, task_id: UUID) -> None:
        try:
            with self._lock:
                context = self._contexts.get(task_id)
                if context is None or context.task.state is not TaskState.EXECUTING:
                    return
            self._validate_and_apply(context)
        except Exception as exc:
            self._fail_task(task_id, exc)

    def _validate_and_apply(self, context: _PackageContext) -> None:
        task_id = context.task.task_id
        manifest = context.manifest
        repo = self.repository_root
        candidate_root = context.workflow_root / "candidate"
        if candidate_root.exists():
            shutil.rmtree(candidate_root)

        self._event(task_id, TaskState.EXECUTING, "development_package_candidate_copy", "Copying the current Git-visible Nexuss worktree into isolated validation.")
        _copy_current_repository(repo, candidate_root)
        baseline = _pytest(candidate_root)
        if baseline.returncode not in {0, 1}:
            raise DevelopmentPackageError(
                "DEVELOPMENT_PACKAGE_BASELINE_CONTROLLER_FAILURE",
                "The isolated pre-package pytest baseline did not run normally.",
                safe_details={"pytest_exit_code": baseline.returncode},
            )
        self._event(
            task_id,
            TaskState.EXECUTING,
            "development_package_baseline_ready",
            f"Isolated baseline captured with {len(baseline.failure_nodes)} known failing/error node(s).",
        )

        self._verify_target_preconditions(manifest, candidate_root)
        self._apply_manifest_to_root(context, candidate_root)
        self._syntax_check_changed_python(manifest, candidate_root)
        self._event(task_id, TaskState.EXECUTING, "development_package_static_validation_passed", "Changed Python source passed deterministic syntax validation.")

        if manifest.focused_tests:
            focused = _pytest(candidate_root, tuple(_safe_focused_test(item) for item in manifest.focused_tests))
            if focused.returncode != 0:
                self._write_validation(context, baseline, focused=focused, post=None)
                raise DevelopmentPackageError(
                    "DEVELOPMENT_PACKAGE_FOCUSED_TEST_FAILED",
                    "Package-declared focused validation failed in isolation.",
                    safe_details={"pytest_exit_code": focused.returncode, "failure_nodes": sorted(focused.failure_nodes)},
                )
            self._event(task_id, TaskState.EXECUTING, "development_package_focused_tests_passed", "Package-declared focused tests passed in the isolated candidate.")
        else:
            focused = None

        with self._lock:
            current = self._contexts[task_id].task
            if current.state is TaskState.EXECUTING:
                events = list(current.events)
                validate_transition(TaskState.EXECUTING, TaskState.VERIFYING)
                now = datetime.now(UTC)
                self._append_event(
                    task_id,
                    events,
                    TaskState.VERIFYING,
                    "development_package_regression_verification_started",
                    "Nexuss is comparing the full post-package suite with the isolated baseline.",
                    now,
                )
                self._contexts[task_id].task = current.model_copy(update={"state": TaskState.VERIFYING, "events": events, "updated_at": now})
                self._persist_context(self._contexts[task_id])
                self._record_receipt(self._contexts[task_id].task)

        post = _pytest(candidate_root)
        if post.returncode not in {0, 1}:
            self._write_validation(context, baseline, focused=focused, post=post)
            raise DevelopmentPackageError(
                "DEVELOPMENT_PACKAGE_POST_TEST_CONTROLLER_FAILURE",
                "The post-package pytest suite did not run normally.",
                safe_details={"pytest_exit_code": post.returncode},
            )
        new_nodes = frozenset(post.failure_nodes - baseline.failure_nodes)
        if new_nodes:
            self._write_validation(context, baseline, focused=focused, post=post)
            raise DevelopmentPackageError(
                "DEVELOPMENT_PACKAGE_NEW_REGRESSION",
                "The package introduced new failing/error pytest node IDs and was not applied.",
                safe_details={"new_failure_nodes": sorted(new_nodes)},
            )
        self._event(task_id, TaskState.VERIFYING, "development_package_regression_clean", "Full pytest is baseline-equivalent or better; zero new failing/error node IDs were introduced.")

        fingerprint_now = _repository_fingerprint(repo)
        if context.live_fingerprint_at_approval != fingerprint_now:
            self._write_validation(context, baseline, focused=focused, post=post)
            raise DevelopmentPackageError(
                "DEVELOPMENT_PACKAGE_LIVE_WORKTREE_DRIFT",
                "The live Git-visible Nexuss worktree changed during validation; the package was not applied.",
            )
        self._verify_target_preconditions(manifest, repo)

        backup = self._create_backup(context)
        context.backup_root = backup
        self._event(task_id, TaskState.VERIFYING, "development_package_backup_ready", "A complete affected-file rollback backup was created before live application.")
        try:
            self._apply_manifest_to_root(context, repo)
            self._verify_live_matches_applied(context)
        except Exception:
            self._restore_backup(context)
            raise

        self._write_validation(context, baseline, focused=focused, post=post)
        result = self._success_result(context, baseline, post)
        with self._lock:
            current = self._contexts[task_id].task
            if current.state is not TaskState.VERIFYING:
                return
            events = list(current.events)
            validate_transition(TaskState.VERIFYING, TaskState.COMPLETED)
            now = datetime.now(UTC)
            self._append_event(
                task_id,
                events,
                TaskState.COMPLETED,
                "development_package_applied",
                "The approved regression-clean package was atomically applied. Restart Nexuss to load changed Python/UI source.",
                now,
            )
            self._contexts[task_id].task = current.model_copy(
                update={
                    "state": TaskState.COMPLETED,
                    "results": [result],
                    "events": events,
                    "updated_at": now,
                }
            )
            self._contexts[task_id].backup_root = backup
            self._persist_context(self._contexts[task_id])
            self._record_receipt(self._contexts[task_id].task)

    def _verify_target_preconditions(self, manifest: DevelopmentPackageManifest, root: Path) -> None:
        for entry in manifest.files:
            relative = _normalize_repo_path(entry.path)
            target = _target_path(root, relative)
            if entry.operation is PackageOperation.ADD:
                if target.exists():
                    raise DevelopmentPackageError(
                        "DEVELOPMENT_PACKAGE_ADD_PATH_EXISTS",
                        "A package add target already exists.",
                        safe_details={"path": relative},
                    )
            else:
                if not target.is_file():
                    raise DevelopmentPackageError(
                        "DEVELOPMENT_PACKAGE_BASE_FILE_MISSING",
                        "A package replace/delete base file is missing.",
                        safe_details={"path": relative},
                    )
                if _sha256_file(target) != entry.before_sha256:
                    raise DevelopmentPackageError(
                        "DEVELOPMENT_PACKAGE_BASE_HASH_MISMATCH",
                        "A package target changed from the version the ZIP was built against.",
                        safe_details={"path": relative},
                    )

    def _apply_manifest_to_root(self, context: _PackageContext, root: Path) -> None:
        extracted = Path(context.archive_receipt.extracted_root)
        for entry in context.manifest.files:
            relative = _normalize_repo_path(entry.path)
            target = _target_path(root, relative)
            if entry.operation is PackageOperation.DELETE:
                target.unlink()
                self._prune_empty_parents(target.parent, root)
                continue
            source = extracted / "payload" / relative
            content = source.read_bytes()
            if _sha256_bytes(content) != entry.sha256:
                raise DevelopmentPackageError(
                    "DEVELOPMENT_PACKAGE_PAYLOAD_HASH_CHANGED",
                    "A quarantined package payload hash changed unexpectedly.",
                    safe_details={"path": relative},
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.{uuid4().hex}.nexuss-package-tmp")
            temporary.write_bytes(content)
            os.replace(temporary, target)

    def _syntax_check_changed_python(self, manifest: DevelopmentPackageManifest, root: Path) -> None:
        for entry in manifest.files:
            if entry.operation is PackageOperation.DELETE or not entry.path.endswith(".py"):
                continue
            path = root / _normalize_repo_path(entry.path)
            try:
                compile(path.read_text(encoding="utf-8"), str(path), "exec")
            except Exception as exc:
                raise DevelopmentPackageError(
                    "DEVELOPMENT_PACKAGE_PYTHON_SYNTAX_INVALID",
                    "A changed Python file failed deterministic syntax validation.",
                    safe_details={"path": entry.path, "error_type": type(exc).__name__},
                ) from exc

    def _create_backup(self, context: _PackageContext) -> Path:
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        root = self.repository_root / ".patch-backups" / f"development-package-{context.manifest.package_id}-{stamp}"
        root.mkdir(parents=True, exist_ok=False)
        existed: dict[str, bool] = {}
        hashes: dict[str, str | None] = {}
        for entry in context.manifest.files:
            relative = _normalize_repo_path(entry.path)
            source = _target_path(self.repository_root, relative)
            existed[relative] = source.is_file()
            hashes[relative] = _sha256_file(source) if source.is_file() else None
            if source.is_file():
                destination = root / "files" / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
        payload = {
            "package_id": context.manifest.package_id,
            "package_sha256": context.inspection.package_sha256,
            "created_at": datetime.now(UTC).isoformat(),
            "existed": existed,
            "before_sha256": hashes,
        }
        (root / "BACKUP-MANIFEST.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return root

    def _restore_backup(self, context: _PackageContext) -> None:
        if context.backup_root is None:
            raise DevelopmentPackageError(
                "DEVELOPMENT_PACKAGE_BACKUP_MISSING",
                "The package rollback backup is unavailable.",
            )
        manifest_path = context.backup_root / "BACKUP-MANIFEST.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        existed = payload["existed"]
        for entry in context.manifest.files:
            relative = _normalize_repo_path(entry.path)
            destination = _target_path(self.repository_root, relative)
            if existed.get(relative):
                source = context.backup_root / "files" / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.rollback-tmp")
                shutil.copy2(source, temporary)
                os.replace(temporary, destination)
            else:
                destination.unlink(missing_ok=True)

    def _verify_live_matches_applied(self, context: _PackageContext) -> None:
        for entry in context.manifest.files:
            relative = _normalize_repo_path(entry.path)
            target = _target_path(self.repository_root, relative)
            if entry.operation is PackageOperation.DELETE:
                if target.exists():
                    raise DevelopmentPackageError(
                        "DEVELOPMENT_PACKAGE_POST_APPLY_DELETE_MISMATCH",
                        "A deleted package path still exists after application.",
                        safe_details={"path": relative},
                    )
            else:
                if not target.is_file() or _sha256_file(target) != entry.sha256:
                    raise DevelopmentPackageError(
                        "DEVELOPMENT_PACKAGE_POST_APPLY_HASH_MISMATCH",
                        "A live package file does not match the approved payload after application.",
                        safe_details={"path": relative},
                    )

    def _success_result(
        self,
        context: _PackageContext,
        baseline: _PytestResult,
        post: _PytestResult,
    ) -> CapabilityResult:
        resolved = sorted(baseline.failure_nodes - post.failure_nodes)
        return CapabilityResult(
            step_id=context.task.plan.steps[0].step_id,
            capability_id="engineering.package.apply",
            status=StepStatus.VERIFIED,
            evidence=[
                EvidenceRecord(
                    source="local:approved_development_package",
                    observed_at=datetime.now(UTC),
                    attributes={
                        "development_package_receipt": True,
                        "sha256_verification": True,
                        "regression_verification": True,
                        "rollback_backup": str(context.backup_root),
                        "package_id": context.manifest.package_id,
                        "phase": context.manifest.phase,
                        "package_sha256": context.inspection.package_sha256,
                        "development_manifest_sha256": context.inspection.development_manifest_sha256,
                        "changed_file_count": len(context.manifest.files),
                        "baseline_failure_nodes": sorted(baseline.failure_nodes),
                        "post_failure_nodes": sorted(post.failure_nodes),
                        "new_regression_nodes": [],
                        "baseline_failures_resolved": resolved,
                        "llm_used": False,
                        "external_api_used": False,
                        "credentials_exposed": False,
                        "database_schema_changed": False,
                        "git_staged": False,
                        "github_changed": False,
                        "applied_to_live_repository": True,
                        "requires_restart": context.manifest.requires_restart,
                    },
                )
            ],
        )

    def _fail_task(self, task_id: UUID, exc: Exception) -> None:
        with self._lock:
            context = self._contexts.get(task_id)
            if context is None:
                return
            current = context.task
            if current.state in {TaskState.COMPLETED, TaskState.DENIED, TaskState.FAILED, TaskState.ROLLED_BACK}:
                return
            error_code = exc.code if isinstance(exc, DevelopmentPackageError) else "DEVELOPMENT_PACKAGE_UNEXPECTED_FAILURE"
            state = current.state
            events = list(current.events)
            if state is TaskState.EXECUTING:
                validate_transition(TaskState.EXECUTING, TaskState.FAILED)
            elif state is TaskState.VERIFYING:
                validate_transition(TaskState.VERIFYING, TaskState.FAILED)
            elif state is TaskState.APPROVED:
                validate_transition(TaskState.APPROVED, TaskState.FAILED)
            else:
                return
            now = datetime.now(UTC)
            self._append_event(
                task_id,
                events,
                TaskState.FAILED,
                "development_package_failed",
                "The development package stopped safely; the live repository was not accepted as successfully updated.",
                now,
            )
            result = CapabilityResult(
                step_id=current.plan.steps[0].step_id,
                capability_id="engineering.package.apply",
                status=StepStatus.FAILED,
                evidence=[
                    EvidenceRecord(
                        source="local:approved_development_package",
                        observed_at=now,
                        attributes={
                            "development_package_receipt": True,
                            "sha256_verification": bool(context.inspection),
                            "package_id": context.manifest.package_id,
                            "package_sha256": context.inspection.package_sha256,
                            "error_code": error_code,
                            "error_type": type(exc).__name__,
                            "llm_used": False,
                            "external_api_used": False,
                            "credentials_exposed": False,
                            "git_staged": False,
                            "github_changed": False,
                        },
                    )
                ],
                error_code=error_code,
            )
            context.task = current.model_copy(
                update={
                    "state": TaskState.FAILED,
                    "results": [result],
                    "events": events,
                    "updated_at": now,
                }
            )
            self._persist_context(context)
            self._record_receipt(context.task)

    def _write_validation(
        self,
        context: _PackageContext,
        baseline: _PytestResult,
        *,
        focused: _PytestResult | None,
        post: _PytestResult | None,
    ) -> None:
        payload = {
            "package_id": context.manifest.package_id,
            "baseline": {
                "exit_code": baseline.returncode,
                "failure_nodes": sorted(baseline.failure_nodes),
            },
            "focused": None if focused is None else {
                "exit_code": focused.returncode,
                "failure_nodes": sorted(focused.failure_nodes),
                "output": focused.output,
            },
            "post": None if post is None else {
                "exit_code": post.returncode,
                "failure_nodes": sorted(post.failure_nodes),
                "new_failure_nodes": sorted(post.failure_nodes - baseline.failure_nodes),
                "output": post.output,
            },
        }
        path = context.workflow_root / "VALIDATION.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temporary, path)

    def _event(self, task_id: UUID, state: TaskState, event_type: str, detail: str) -> None:
        with self._lock:
            context = self._contexts[task_id]
            current = context.task
            events = list(current.events)
            now = datetime.now(UTC)
            self._append_event(task_id, events, state, event_type, detail, now)
            context.task = current.model_copy(update={"events": events, "updated_at": now})
            self._persist_context(context)
            self._record_receipt(context.task)

    @staticmethod
    def _append_event(
        task_id: UUID,
        events: list[ActionEvent],
        state: TaskState,
        event_type: str,
        detail: str,
        occurred_at: datetime,
    ) -> None:
        sequence = len(events) + 1
        events.append(
            ActionEvent(
                event_id=uuid5(NAMESPACE_URL, f"nexuss:development-package-event:{task_id}:{sequence}:{event_type}"),
                sequence=sequence,
                state=state,
                event_type=event_type,
                occurred_at=occurred_at,
                detail=detail,
            )
        )

    def _record_receipt(self, task: TaskView) -> None:
        history = self._receipt_history.setdefault(task.task_id, [])
        receipt = ActionReceipt(
            receipt_id=uuid5(NAMESPACE_URL, f"nexuss:development-package-receipt:{task.task_id}:{len(history)+1}"),
            receipt_version=len(history) + 1,
            task_id=task.task_id,
            request_id=task.request_id,
            state=task.state,
            intent=task.intent,
            plan_id=task.plan.plan_id,
            policy_decisions=task.policy_decisions,
            results=task.results,
            events=task.events,
            created_at=task.created_at,
            updated_at=task.updated_at,
            verified=(task.state is TaskState.COMPLETED and all(result.status is StepStatus.VERIFIED for result in task.results)),
            reversible=task.state is TaskState.COMPLETED,
        )
        history.append(receipt)
        root = self.storage_root / "receipts" / str(task.task_id)
        root.mkdir(parents=True, exist_ok=True)
        (root / f"{receipt.receipt_version:04d}.json").write_text(
            json.dumps(receipt.model_dump(mode="json"), indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )

    def _persist_context(self, context: _PackageContext) -> None:
        root = context.workflow_root
        root.mkdir(parents=True, exist_ok=True)
        payload = {
            "task": context.task.model_dump(mode="json"),
            "manifest": context.manifest.model_dump(mode="json"),
            "inspection": context.inspection.model_dump(mode="json"),
            "archive_receipt": context.archive_receipt.model_dump(mode="json"),
            "live_fingerprint_at_approval": context.live_fingerprint_at_approval,
            "backup_root": str(context.backup_root) if context.backup_root is not None else None,
        }
        temporary = root / "context.json.tmp"
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
        os.replace(temporary, root / "context.json")

    def _load_durable_tasks(self) -> None:
        tasks_root = self.storage_root / "tasks"
        if not tasks_root.is_dir():
            return
        for context_path in tasks_root.glob("*/context.json"):
            try:
                payload = json.loads(context_path.read_text(encoding="utf-8"))
                task = TaskView.model_validate(payload["task"])
                manifest = DevelopmentPackageManifest.model_validate(payload["manifest"])
                inspection = DevelopmentPackageInspection.model_validate(payload["inspection"])
                archive_receipt = ArchiveIntakeReceipt.model_validate(payload["archive_receipt"])
                context = _PackageContext(
                    task=task,
                    manifest=manifest,
                    inspection=inspection,
                    archive_receipt=archive_receipt,
                    workflow_root=context_path.parent,
                    live_fingerprint_at_approval=payload.get("live_fingerprint_at_approval"),
                    backup_root=Path(payload["backup_root"]) if payload.get("backup_root") else None,
                )
                if task.state in {TaskState.APPROVED, TaskState.EXECUTING, TaskState.VERIFYING}:
                    events = list(task.events)
                    now = datetime.now(UTC)
                    self._append_event(
                        task.task_id,
                        events,
                        TaskState.FAILED,
                        "development_package_runtime_interrupted",
                        "Nexuss restarted while package validation/application was active; the task stopped safely and was not resumed automatically.",
                        now,
                    )
                    context.task = task.model_copy(update={"state": TaskState.FAILED, "events": events, "updated_at": now})
                self._contexts[task.task_id] = context
                self._request_index[task.request_id] = task.task_id
                self._load_receipts(task.task_id)
                if context.task is not task:
                    self._persist_context(context)
                    self._record_receipt(context.task)
            except Exception:
                continue

    def _load_receipts(self, task_id: UUID) -> None:
        root = self.storage_root / "receipts" / str(task_id)
        history: list[ActionReceipt] = []
        if root.is_dir():
            for path in sorted(root.glob("*.json")):
                try:
                    history.append(ActionReceipt.model_validate_json(path.read_text(encoding="utf-8")))
                except Exception:
                    continue
        self._receipt_history[task_id] = history

    def _require_context(self, task_id: UUID, session_id: UUID) -> _PackageContext:
        context = self._contexts.get(task_id)
        if context is None:
            raise DevelopmentPackageTaskNotFoundError(
                "DEVELOPMENT_PACKAGE_TASK_NOT_FOUND",
                "Development package task not found.",
                status_code=404,
            )
        if context.task.user_session_id != session_id:
            raise DevelopmentPackageSessionError(
                "DEVELOPMENT_PACKAGE_SESSION_MISMATCH",
                "Authenticated session does not match the development-package task.",
                status_code=401,
            )
        return context

    @staticmethod
    def _prune_empty_parents(path: Path, root: Path) -> None:
        current = path
        root = root.resolve()
        while current.resolve() != root:
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent
