"""Ephemeral, path-contained engineering workspace."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field

from nexuss.engineering.errors import EngineeringError


class WorkspacePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_file_bytes: int = Field(default=1_000_000, ge=1_024, le=20_000_000)
    max_output_chars: int = Field(default=100_000, ge=1_000, le=1_000_000)
    command_timeout_seconds: int = Field(default=120, ge=1, le=1_800)
    allowed_executables: frozenset[str] = frozenset(
        {"python", "python3", "node", "npm", "pytest", "git"}
    )
    allowed_git_subcommands: frozenset[str] = frozenset(
        {"status", "diff", "log", "show", "rev-parse"}
    )
    denied_filenames: frozenset[str] = frozenset(
        {".env", ".env.local", "credentials", "credentials.json", "id_rsa", "id_ed25519"}
    )


class IsolatedWorkspace:
    def __init__(
        self,
        root: Path,
        *,
        policy: WorkspacePolicy | None = None,
        owns_root: bool = False,
    ) -> None:
        self.root = root.resolve()
        self.policy = policy or WorkspacePolicy()
        self._owns_root = owns_root
        self.root.mkdir(parents=True, exist_ok=True)
        self._changed_files: set[str] = set()

    @classmethod
    def create(cls, *, policy: WorkspacePolicy | None = None) -> IsolatedWorkspace:
        root = Path(tempfile.mkdtemp(prefix="nexuss-engineering-"))
        return cls(root, policy=policy, owns_root=True)

    @property
    def changed_files(self) -> tuple[str, ...]:
        return tuple(sorted(self._changed_files))

    def close(self) -> None:
        if self._owns_root:
            shutil.rmtree(self.root, ignore_errors=True)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _resolve(self, relative_path: str) -> Path:
        if not relative_path or "\x00" in relative_path:
            raise EngineeringError(
                "ENGINEERING_PATH_INVALID",
                "The workspace path is invalid.",
            )
        candidate = (self.root / relative_path).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise EngineeringError(
                "ENGINEERING_PATH_ESCAPE",
                "The requested path escapes the engineering workspace.",
            ) from exc
        if candidate.name.casefold() in {name.casefold() for name in self.policy.denied_filenames}:
            raise EngineeringError(
                "ENGINEERING_SECRET_FILE_DENIED",
                "The requested filename is reserved for credentials or secrets.",
            )
        return candidate

    def read_text(self, relative_path: str) -> str:
        path = self._resolve(relative_path)
        if not path.is_file():
            raise EngineeringError(
                "ENGINEERING_FILE_NOT_FOUND",
                "The requested workspace file does not exist.",
            )
        if path.stat().st_size > self.policy.max_file_bytes:
            raise EngineeringError(
                "ENGINEERING_FILE_TOO_LARGE",
                "The requested workspace file exceeds the read limit.",
            )
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise EngineeringError(
                "ENGINEERING_BINARY_FILE_UNSUPPORTED",
                "Binary files are not supported by this tool.",
            ) from exc

    def write_text(
        self,
        relative_path: str,
        content: str,
        *,
        expected_sha256: str | None = None,
    ) -> str:
        encoded = content.encode("utf-8")
        if len(encoded) > self.policy.max_file_bytes:
            raise EngineeringError(
                "ENGINEERING_FILE_TOO_LARGE",
                "The proposed file exceeds the write limit.",
            )
        path = self._resolve(relative_path)
        if path.exists() and expected_sha256 is not None:
            current = hashlib.sha256(path.read_bytes()).hexdigest()
            if current != expected_sha256:
                raise EngineeringError(
                    "ENGINEERING_FILE_CHANGED",
                    "The workspace file changed after the model inspected it.",
                )
        elif path.exists() and expected_sha256 is None:
            raise EngineeringError(
                "ENGINEERING_OVERWRITE_REQUIRES_HASH",
                "Overwriting an existing file requires its expected SHA-256.",
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".nexuss-tmp")
        temporary.write_bytes(encoded)
        os.replace(temporary, path)
        relative = path.relative_to(self.root).as_posix()
        self._changed_files.add(relative)
        return hashlib.sha256(encoded).hexdigest()

    def list_files(self, relative_path: str = ".") -> tuple[str, ...]:
        directory = self._resolve(relative_path)
        if not directory.is_dir():
            raise EngineeringError(
                "ENGINEERING_DIRECTORY_NOT_FOUND",
                "The requested workspace directory does not exist.",
            )
        return tuple(
            sorted(
                path.relative_to(self.root).as_posix()
                for path in directory.rglob("*")
                if path.is_file()
            )[:2_000]
        )

    def run_command(self, argv: list[str]) -> tuple[int, str]:
        if not argv or any(not isinstance(part, str) or not part for part in argv):
            raise EngineeringError(
                "ENGINEERING_COMMAND_INVALID",
                "The command argument vector is invalid.",
            )
        executable = Path(argv[0]).name.casefold()
        if executable not in {item.casefold() for item in self.policy.allowed_executables}:
            raise EngineeringError(
                "ENGINEERING_COMMAND_DENIED",
                "The requested executable is not allowlisted.",
            )
        if executable == "git" and (
            len(argv) < 2
            or argv[1].casefold()
            not in {
                item.casefold()
                for item in self.policy.allowed_git_subcommands
            }
        ):
            raise EngineeringError(
                "ENGINEERING_GIT_WRITE_DENIED",
                "Only read-only Git subcommands are allowed in this workspace stage.",
            )
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE"}
        }
        try:
            completed = subprocess.run(
                argv,
                cwd=self.root,
                env=environment,
                shell=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=self.policy.command_timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise EngineeringError(
                "ENGINEERING_COMMAND_FAILED",
                "The bounded workspace command could not complete.",
            ) from exc
        output = completed.stdout[: self.policy.max_output_chars]
        return completed.returncode, output
