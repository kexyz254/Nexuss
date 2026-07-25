"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Controlled managed-note storage for the Nexuss P3 approved-action platform.
"""

from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

_MAX_NOTE_BYTES = 32_768
_MAX_TITLE_LENGTH = 80
_RESERVED_WINDOWS_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class ManagedNoteError(RuntimeError):
    """Base class for managed-note failures safe to expose as error codes."""


class InvalidNoteError(ManagedNoteError):
    """Raised when note metadata violates the managed workspace contract."""


class NoteAlreadyExistsError(ManagedNoteError):
    """Raised when the requested note would overwrite an existing file."""


class NoteVerificationError(ManagedNoteError):
    """Raised when post-write or pre-rollback verification fails."""


@dataclass(frozen=True)
class PreparedNote:
    title: str
    filename: str
    content: str
    content_bytes: bytes
    content_sha256: str


@dataclass(frozen=True)
class CreatedNote:
    path: Path
    filename: str
    byte_count: int
    sha256: str


def _normalize_title(raw_title: str) -> str:
    title = unicodedata.normalize("NFKC", raw_title).strip()
    if title.casefold().endswith(".md"):
        title = title[:-3].rstrip()
    if not title or len(title) > _MAX_TITLE_LENGTH:
        raise InvalidNoteError("NOTE_TITLE_LENGTH_INVALID")
    if ".." in title or any(separator in title for separator in ("/", "\\", ":")):
        raise InvalidNoteError("NOTE_TITLE_PATH_SYNTAX_REJECTED")

    cleaned = "".join(
        character
        for character in title
        if character.isalnum() or character in {" ", "-", "_", "(", ")"}
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        raise InvalidNoteError("NOTE_TITLE_EMPTY_AFTER_SANITIZATION")
    if cleaned.upper() in _RESERVED_WINDOWS_NAMES:
        raise InvalidNoteError("NOTE_TITLE_RESERVED")
    return cleaned


def prepare_note(title: str, content: str) -> PreparedNote:
    normalized_title = _normalize_title(title)
    if "\x00" in content:
        raise InvalidNoteError("NOTE_CONTENT_NULL_BYTE_REJECTED")
    normalized_content = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized_content:
        raise InvalidNoteError("NOTE_CONTENT_EMPTY")
    if not normalized_content.endswith("\n"):
        normalized_content += "\n"
    content_bytes = normalized_content.encode("utf-8")
    if len(content_bytes) > _MAX_NOTE_BYTES:
        raise InvalidNoteError("NOTE_CONTENT_TOO_LARGE")
    return PreparedNote(
        title=normalized_title,
        filename=f"{normalized_title}.md",
        content=normalized_content,
        content_bytes=content_bytes,
        content_sha256=hashlib.sha256(content_bytes).hexdigest(),
    )


class ManagedNoteStore:
    """Create and rollback notes strictly inside one configured managed directory."""

    def __init__(self, root: Path | None = None) -> None:
        configured_root = root or Path(
            os.environ.get("NEXUSS_MANAGED_WORKSPACE", Path.home() / ".nexuss" / "workspace")
        )
        self.root = configured_root.expanduser().resolve()

    def _target_path(self, filename: str) -> Path:
        target = (self.root / filename).resolve()
        if target.parent != self.root:
            raise InvalidNoteError("NOTE_PATH_OUTSIDE_MANAGED_WORKSPACE")
        return target

    def create(self, prepared: PreparedNote) -> CreatedNote:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self._target_path(prepared.filename)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        try:
            descriptor = os.open(target, flags, 0o600)
        except FileExistsError as exc:
            raise NoteAlreadyExistsError("NOTE_ALREADY_EXISTS") from exc
        except OSError as exc:
            raise ManagedNoteError("NOTE_CREATE_FAILED") from exc

        try:
            with os.fdopen(descriptor, "wb") as file_handle:
                file_handle.write(prepared.content_bytes)
                file_handle.flush()
                os.fsync(file_handle.fileno())
        except Exception:
            target.unlink(missing_ok=True)
            raise

        actual_bytes = target.read_bytes()
        actual_sha256 = hashlib.sha256(actual_bytes).hexdigest()
        if actual_bytes != prepared.content_bytes or actual_sha256 != prepared.content_sha256:
            target.unlink(missing_ok=True)
            raise NoteVerificationError("NOTE_POST_WRITE_VERIFICATION_FAILED")

        return CreatedNote(
            path=target,
            filename=prepared.filename,
            byte_count=len(actual_bytes),
            sha256=actual_sha256,
        )

    def rollback(self, *, filename: str, expected_sha256: str) -> Path:
        target = self._target_path(filename)
        if not target.is_file():
            raise NoteVerificationError("ROLLBACK_TARGET_MISSING")
        actual_sha256 = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual_sha256 != expected_sha256:
            raise NoteVerificationError("ROLLBACK_HASH_MISMATCH")
        target.unlink()
        if target.exists():
            raise NoteVerificationError("ROLLBACK_DELETE_VERIFICATION_FAILED")
        return target
