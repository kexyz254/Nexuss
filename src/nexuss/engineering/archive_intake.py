"""Quarantined ZIP intake for controlled repository imports."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import stat
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from nexuss.engineering.errors import EngineeringError

_WINDOWS_RESERVED = frozenset(
    {
        "aux",
        "con",
        "nul",
        "prn",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
    }
)
_SECRET_FILENAMES = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
        ".netrc",
        ".npmrc",
        ".pypirc",
        "credentials",
        "credentials.json",
        "id_ed25519",
        "id_rsa",
    }
)
_NESTED_ARCHIVE_SUFFIXES = frozenset(
    {
        ".7z",
        ".bz2",
        ".gz",
        ".rar",
        ".tar",
        ".tgz",
        ".xz",
        ".zip",
    }
)
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private_key",
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
        ),
    ),
    (
        "github_token",
        re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    ),
    (
        "aws_access_key",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    ),
    (
        "authorization_bearer",
        re.compile(
            r"authorization\s*[:=]\s*bearer\s+[A-Za-z0-9._-]{12,}",
            re.IGNORECASE,
        ),
    ),
)


class ArchiveIntakePolicy(BaseModel):
    """Fail-closed limits for untrusted ZIP archives."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_archive_bytes: int = Field(
        default=50_000_000,
        ge=1_024,
        le=500_000_000,
    )
    max_entries: int = Field(default=5_000, ge=1, le=50_000)
    max_total_uncompressed_bytes: int = Field(
        default=250_000_000,
        ge=1_024,
        le=2_000_000_000,
    )
    max_file_uncompressed_bytes: int = Field(
        default=25_000_000,
        ge=1_024,
        le=100_000_000,
    )
    max_compression_ratio: float = Field(
        default=200.0,
        ge=1.0,
        le=10_000.0,
    )
    max_path_chars: int = Field(default=240, ge=32, le=1_000)
    max_segment_chars: int = Field(default=120, ge=16, le=255)
    strip_single_root: bool = True
    reject_nested_archives: bool = True
    reject_workflow_files: bool = True
    reject_secret_filenames: bool = True
    allowed_compression_methods: frozenset[int] = frozenset(
        {
            zipfile.ZIP_STORED,
            zipfile.ZIP_DEFLATED,
        }
    )


class ArchiveSecurityFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1, max_length=120)
    path: str = Field(min_length=1, max_length=1_000)
    detail: str = Field(min_length=1, max_length=2_000)


class ArchiveManifestEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_path: str = Field(min_length=1, max_length=1_000)
    repository_path: str = Field(min_length=1, max_length=1_000)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    crc32: str = Field(pattern=r"^[0-9a-f]{8}$")
    size_bytes: int = Field(ge=0)
    compressed_size_bytes: int = Field(ge=0)
    compression_method: int
    media_type: str = Field(min_length=1, max_length=200)
    git_mode: str = Field(pattern=r"^100(?:644|755)$")
    executable: bool
    text_utf8: bool


class ArchiveIntakeReceipt(BaseModel):
    """Secret-free evidence for one local archive intake."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    intake_id: UUID = Field(default_factory=uuid4)
    archive_name: str = Field(min_length=1, max_length=255)
    quarantine_root: str
    extracted_root: str
    archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    archive_size_bytes: int = Field(ge=0)
    total_uncompressed_bytes: int = Field(ge=0)
    file_count: int = Field(ge=0)
    stripped_single_root: str | None = None
    entries: tuple[ArchiveManifestEntry, ...]
    security_findings: tuple[ArchiveSecurityFinding, ...] = ()
    publication_allowed: bool
    github_changed: bool = False
    published: bool = False
    credentials_exposed: bool = False
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )


@dataclass(frozen=True)
class _Candidate:
    info: zipfile.ZipInfo
    source_path: str
    normalized_path: str
    is_directory: bool
    executable: bool


class SecureArchiveIntake:
    """Inspect, quarantine, extract, hash, and scan one ZIP archive."""

    def __init__(
        self,
        policy: ArchiveIntakePolicy | None = None,
    ) -> None:
        self.policy = policy or ArchiveIntakePolicy()

    def intake(
        self,
        source_archive: Path,
        quarantine_parent: Path,
    ) -> ArchiveIntakeReceipt:
        source = source_archive.expanduser().resolve()
        if not source.is_file():
            raise EngineeringError(
                "ARCHIVE_FILE_NOT_FOUND",
                "The requested ZIP archive does not exist.",
            )

        archive_size = source.stat().st_size
        if archive_size > self.policy.max_archive_bytes:
            raise EngineeringError(
                "ARCHIVE_COMPRESSED_SIZE_LIMIT",
                "The ZIP archive exceeds the compressed-size limit.",
                safe_details={"archive_size_bytes": archive_size},
            )
        if not zipfile.is_zipfile(source):
            raise EngineeringError(
                "ARCHIVE_FORMAT_INVALID",
                "The supplied file is not a valid ZIP archive.",
            )

        intake_id = uuid4()
        root = (
            quarantine_parent.expanduser().resolve()
            / str(intake_id)
        )
        if root.exists():
            raise EngineeringError(
                "ARCHIVE_QUARANTINE_COLLISION",
                "The archive quarantine directory already exists.",
            )
        root.mkdir(parents=True)
        quarantined_archive = root / "source.zip"
        shutil.copyfile(source, quarantined_archive)
        archive_sha256 = self._hash_file(quarantined_archive)

        extracted_root = root / "content"
        extracted_root.mkdir()

        try:
            with zipfile.ZipFile(quarantined_archive) as archive:
                candidates, stripped_root = self._inspect(archive)
                entries, findings, total_uncompressed = self._extract(
                    archive,
                    candidates,
                    extracted_root,
                )
        except (EngineeringError, zipfile.BadZipFile):
            shutil.rmtree(root, ignore_errors=True)
            raise
        except OSError as exc:
            shutil.rmtree(root, ignore_errors=True)
            raise EngineeringError(
                "ARCHIVE_EXTRACTION_FAILED",
                "The ZIP archive could not be extracted safely.",
            ) from exc

        manifest_sha256 = self._manifest_sha256(
            archive_sha256,
            stripped_root,
            entries,
        )
        receipt = ArchiveIntakeReceipt(
            intake_id=intake_id,
            archive_name=source.name,
            quarantine_root=str(root),
            extracted_root=str(extracted_root),
            archive_sha256=archive_sha256,
            manifest_sha256=manifest_sha256,
            archive_size_bytes=archive_size,
            total_uncompressed_bytes=total_uncompressed,
            file_count=len(entries),
            stripped_single_root=stripped_root,
            entries=entries,
            security_findings=findings,
            publication_allowed=not findings,
            github_changed=False,
            published=False,
            credentials_exposed=False,
        )
        self._atomic_write_json(
            root / "ARCHIVE-INTAKE-RECEIPT.json",
            receipt.model_dump(mode="json"),
        )
        return receipt

    def _inspect(
        self,
        archive: zipfile.ZipFile,
    ) -> tuple[tuple[_Candidate, ...], str | None]:
        infos = archive.infolist()
        if not infos:
            raise EngineeringError(
                "ARCHIVE_EMPTY",
                "The ZIP archive contains no entries.",
            )
        if len(infos) > self.policy.max_entries:
            raise EngineeringError(
                "ARCHIVE_ENTRY_COUNT_LIMIT",
                "The ZIP archive contains too many entries.",
                safe_details={"entry_count": len(infos)},
            )

        candidates: list[_Candidate] = []
        total_uncompressed = 0

        for info in infos:
            if info.flag_bits & 0x1:
                raise EngineeringError(
                    "ARCHIVE_ENCRYPTED_ENTRY_PROHIBITED",
                    "Encrypted ZIP entries are not supported.",
                    safe_details={"path": info.filename},
                )
            if (
                info.compress_type
                not in self.policy.allowed_compression_methods
            ):
                raise EngineeringError(
                    "ARCHIVE_COMPRESSION_UNSUPPORTED",
                    "The ZIP archive uses a prohibited compression method.",
                    safe_details={"path": info.filename},
                )

            normalized = self._normalize_path(info.filename)
            mode = (info.external_attr >> 16) & 0xFFFF
            file_type = stat.S_IFMT(mode)
            is_directory = info.is_dir()

            if file_type == stat.S_IFLNK:
                raise EngineeringError(
                    "ARCHIVE_SYMLINK_PROHIBITED",
                    "Symbolic links are prohibited in archive imports.",
                    safe_details={"path": normalized},
                )
            if (
                file_type
                and not is_directory
                and file_type != stat.S_IFREG
            ):
                raise EngineeringError(
                    "ARCHIVE_SPECIAL_FILE_PROHIBITED",
                    "Device and special filesystem entries are prohibited.",
                    safe_details={"path": normalized},
                )

            if not is_directory:
                if info.file_size > self.policy.max_file_uncompressed_bytes:
                    raise EngineeringError(
                        "ARCHIVE_FILE_SIZE_LIMIT",
                        "An archive file exceeds the per-file limit.",
                        safe_details={
                            "path": normalized,
                            "size_bytes": info.file_size,
                        },
                    )
                total_uncompressed += info.file_size
                if (
                    total_uncompressed
                    > self.policy.max_total_uncompressed_bytes
                ):
                    raise EngineeringError(
                        "ARCHIVE_EXPANDED_SIZE_LIMIT",
                        "The ZIP archive exceeds the expanded-size limit.",
                    )

                ratio = (
                    float("inf")
                    if info.compress_size == 0 and info.file_size
                    else info.file_size / max(info.compress_size, 1)
                )
                if ratio > self.policy.max_compression_ratio:
                    raise EngineeringError(
                        "ARCHIVE_COMPRESSION_RATIO_LIMIT",
                        "An archive entry has a suspicious compression ratio.",
                        safe_details={
                            "path": normalized,
                            "compression_ratio": round(ratio, 3),
                        },
                    )

            candidates.append(
                _Candidate(
                    info=info,
                    source_path=info.filename,
                    normalized_path=normalized,
                    is_directory=is_directory,
                    executable=bool(mode & 0o111),
                )
            )

        file_paths = [
            candidate.normalized_path
            for candidate in candidates
            if not candidate.is_directory
        ]
        stripped_root = self._single_root(file_paths)
        remapped = tuple(
            _Candidate(
                info=candidate.info,
                source_path=candidate.source_path,
                normalized_path=self._strip_root(
                    candidate.normalized_path,
                    stripped_root,
                ),
                is_directory=candidate.is_directory,
                executable=candidate.executable,
            )
            for candidate in candidates
            if self._strip_root(
                candidate.normalized_path,
                stripped_root,
            )
        )
        self._validate_collisions(remapped)
        return remapped, stripped_root

    def _extract(
        self,
        archive: zipfile.ZipFile,
        candidates: tuple[_Candidate, ...],
        extracted_root: Path,
    ) -> tuple[
        tuple[ArchiveManifestEntry, ...],
        tuple[ArchiveSecurityFinding, ...],
        int,
    ]:
        entries: list[ArchiveManifestEntry] = []
        findings: list[ArchiveSecurityFinding] = []
        actual_total = 0

        for candidate in candidates:
            relative = PurePosixPath(candidate.normalized_path)
            target = extracted_root.joinpath(*relative.parts).resolve()
            try:
                target.relative_to(extracted_root)
            except ValueError as exc:
                raise EngineeringError(
                    "ARCHIVE_PATH_ESCAPE",
                    "An archive entry escaped the extraction boundary.",
                ) from exc

            if candidate.is_directory:
                target.mkdir(parents=True, exist_ok=True)
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(
                f".{target.name}.{uuid4().hex}.nexuss-tmp"
            )
            digest = hashlib.sha256()
            file_bytes = 0
            sample = bytearray()

            try:
                with (
                    archive.open(candidate.info, "r") as source,
                    temporary.open("xb") as destination,
                ):
                    while True:
                        chunk = source.read(65_536)
                        if not chunk:
                            break
                        file_bytes += len(chunk)
                        actual_total += len(chunk)
                        if (
                            file_bytes
                            > self.policy.max_file_uncompressed_bytes
                        ):
                            raise EngineeringError(
                                "ARCHIVE_FILE_SIZE_LIMIT",
                                "An extracted file exceeded its limit.",
                            )
                        if (
                            actual_total
                            > self.policy.max_total_uncompressed_bytes
                        ):
                            raise EngineeringError(
                                "ARCHIVE_EXPANDED_SIZE_LIMIT",
                                "The extracted archive exceeded its limit.",
                            )
                        digest.update(chunk)
                        if len(sample) < 2_000_000:
                            sample.extend(
                                chunk[
                                    : 2_000_000 - len(sample)
                                ]
                            )
                        destination.write(chunk)
                if file_bytes != candidate.info.file_size:
                    raise EngineeringError(
                        "ARCHIVE_SIZE_MISMATCH",
                        "An archive entry expanded to an unexpected size.",
                    )
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)

            text_utf8 = False
            if b"\x00" not in sample:
                try:
                    text = sample.decode("utf-8")
                except UnicodeDecodeError:
                    text = ""
                else:
                    text_utf8 = True
                    findings.extend(
                        self._secret_findings(
                            candidate.normalized_path,
                            text,
                        )
                    )

            media_type = (
                mimetypes.guess_type(candidate.normalized_path)[0]
                or "application/octet-stream"
            )
            entries.append(
                ArchiveManifestEntry(
                    source_path=candidate.source_path,
                    repository_path=candidate.normalized_path,
                    sha256=digest.hexdigest(),
                    crc32=f"{candidate.info.CRC:08x}",
                    size_bytes=file_bytes,
                    compressed_size_bytes=(
                        candidate.info.compress_size
                    ),
                    compression_method=(
                        candidate.info.compress_type
                    ),
                    media_type=media_type,
                    git_mode=(
                        "100755"
                        if candidate.executable
                        else "100644"
                    ),
                    executable=candidate.executable,
                    text_utf8=text_utf8,
                )
            )

        if not entries:
            raise EngineeringError(
                "ARCHIVE_NO_FILES",
                "The ZIP archive contains no publishable files.",
            )
        return (
            tuple(
                sorted(
                    entries,
                    key=lambda item: item.repository_path,
                )
            ),
            tuple(
                sorted(
                    findings,
                    key=lambda item: (item.path, item.code),
                )
            ),
            actual_total,
        )

    def _normalize_path(self, value: str) -> str:
        if not value or "\x00" in value:
            raise EngineeringError(
                "ARCHIVE_PATH_INVALID",
                "An archive entry has an invalid path.",
            )

        converted = value.replace("\\", "/")
        if converted.startswith("/") or re.match(
            r"^[A-Za-z]:",
            converted,
        ):
            raise EngineeringError(
                "ARCHIVE_ABSOLUTE_PATH_PROHIBITED",
                "Absolute archive paths are prohibited.",
                safe_details={"path": value},
            )

        trailing_directory = converted.endswith("/")
        parts = converted.rstrip("/").split("/")
        if not parts or any(part in {"", ".", ".."} for part in parts):
            raise EngineeringError(
                "ARCHIVE_PATH_TRAVERSAL_PROHIBITED",
                "Archive paths may not contain empty, dot, or parent segments.",
                safe_details={"path": value},
            )

        normalized_parts: list[str] = []
        for raw_part in parts:
            part = unicodedata.normalize("NFC", raw_part)
            if len(part) > self.policy.max_segment_chars:
                raise EngineeringError(
                    "ARCHIVE_PATH_SEGMENT_LIMIT",
                    "An archive path segment is too long.",
                    safe_details={"path": value},
                )
            if any(ord(character) < 32 for character in part):
                raise EngineeringError(
                    "ARCHIVE_PATH_CONTROL_CHARACTER",
                    "Archive paths may not contain control characters.",
                    safe_details={"path": value},
                )
            if ":" in part:
                raise EngineeringError(
                    "ARCHIVE_NTFS_STREAM_PROHIBITED",
                    "NTFS alternate-data-stream paths are prohibited.",
                    safe_details={"path": value},
                )
            if part.rstrip(" .") != part:
                raise EngineeringError(
                    "ARCHIVE_WINDOWS_PATH_AMBIGUOUS",
                    "Archive path segments may not end in spaces or dots.",
                    safe_details={"path": value},
                )
            basename = part.split(".", 1)[0].casefold()
            if basename in _WINDOWS_RESERVED:
                raise EngineeringError(
                    "ARCHIVE_WINDOWS_RESERVED_NAME",
                    "A Windows-reserved filename is prohibited.",
                    safe_details={"path": value},
                )
            normalized_parts.append(part)

        normalized = PurePosixPath(*normalized_parts).as_posix()
        if trailing_directory:
            normalized += "/"
        if len(normalized) > self.policy.max_path_chars:
            raise EngineeringError(
                "ARCHIVE_PATH_LENGTH_LIMIT",
                "An archive path exceeds the configured limit.",
                safe_details={"path": value},
            )

        lower_parts = tuple(
            part.casefold()
            for part in PurePosixPath(
                normalized.rstrip("/")
            ).parts
        )
        if ".git" in lower_parts:
            raise EngineeringError(
                "ARCHIVE_GIT_METADATA_PROHIBITED",
                "Embedded .git metadata is prohibited.",
                safe_details={"path": value},
            )
        workflow_path = any(
            lower_parts[index : index + 2]
            == (".github", "workflows")
            for index in range(max(len(lower_parts) - 1, 0))
        )
        if self.policy.reject_workflow_files and workflow_path:
            raise EngineeringError(
                "ARCHIVE_WORKFLOW_FILE_PROHIBITED",
                "GitHub workflow files require a separate governed capability.",
                safe_details={"path": value},
            )
        filename = lower_parts[-1]
        if (
            self.policy.reject_secret_filenames
            and filename in _SECRET_FILENAMES
        ):
            raise EngineeringError(
                "ARCHIVE_SECRET_FILENAME_PROHIBITED",
                "Credential-oriented filenames are prohibited.",
                safe_details={"path": value},
            )
        if (
            self.policy.reject_nested_archives
            and PurePosixPath(filename).suffix
            in _NESTED_ARCHIVE_SUFFIXES
        ):
            raise EngineeringError(
                "ARCHIVE_NESTED_ARCHIVE_PROHIBITED",
                "Nested archives are prohibited in this intake stage.",
                safe_details={"path": value},
            )
        return normalized

    def _single_root(
        self,
        file_paths: list[str],
    ) -> str | None:
        if not self.policy.strip_single_root or not file_paths:
            return None
        split_paths = [
            PurePosixPath(path).parts
            for path in file_paths
        ]
        if any(len(parts) < 2 for parts in split_paths):
            return None
        root = split_paths[0][0]
        if all(parts[0] == root for parts in split_paths):
            return root
        return None

    @staticmethod
    def _strip_root(
        path: str,
        root: str | None,
    ) -> str:
        is_directory = path.endswith("/")
        parts = PurePosixPath(path.rstrip("/")).parts
        if root and parts and parts[0] == root:
            parts = parts[1:]
        normalized = PurePosixPath(*parts).as_posix() if parts else ""
        if normalized and is_directory:
            normalized += "/"
        return normalized

    @staticmethod
    def _validate_collisions(
        candidates: tuple[_Candidate, ...],
    ) -> None:
        seen: dict[str, str] = {}
        file_paths: set[str] = set()

        for candidate in candidates:
            path = candidate.normalized_path.rstrip("/")
            if not path:
                continue
            key = unicodedata.normalize(
                "NFKC",
                path,
            ).casefold()
            previous = seen.get(key)
            if previous is not None and previous != path:
                raise EngineeringError(
                    "ARCHIVE_PATH_COLLISION",
                    "Archive paths collide after Unicode and case normalization.",
                    safe_details={
                        "first_path": previous,
                        "second_path": path,
                    },
                )
            if previous == path:
                raise EngineeringError(
                    "ARCHIVE_DUPLICATE_PATH",
                    "The ZIP archive contains a duplicate path.",
                    safe_details={"path": path},
                )
            seen[key] = path
            if not candidate.is_directory:
                file_paths.add(path)

        for file_path in file_paths:
            parts = PurePosixPath(file_path).parts
            for index in range(1, len(parts)):
                parent = PurePosixPath(*parts[:index]).as_posix()
                if parent in file_paths:
                    raise EngineeringError(
                        "ARCHIVE_PATH_TYPE_CONFLICT",
                        "An archive path is both a file and a directory.",
                        safe_details={
                            "file_path": parent,
                            "child_path": file_path,
                        },
                    )

    @staticmethod
    def _secret_findings(
        path: str,
        text: str,
    ) -> list[ArchiveSecurityFinding]:
        return [
            ArchiveSecurityFinding(
                code=f"ARCHIVE_SECRET_{pattern_id.upper()}",
                path=path,
                detail=(
                    "Credential-like material was detected. "
                    "The value is intentionally omitted."
                ),
            )
            for pattern_id, pattern in _SECRET_PATTERNS
            if pattern.search(text)
        ]

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1_048_576):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _manifest_sha256(
        archive_sha256: str,
        stripped_root: str | None,
        entries: tuple[ArchiveManifestEntry, ...],
    ) -> str:
        payload = {
            "archive_sha256": archive_sha256,
            "stripped_single_root": stripped_root,
            "entries": [
                {
                    "path": entry.repository_path,
                    "sha256": entry.sha256,
                    "size_bytes": entry.size_bytes,
                    "git_mode": entry.git_mode,
                }
                for entry in entries
            ],
        }
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _atomic_write_json(
        path: Path,
        payload: object,
    ) -> None:
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(
                payload,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        os.replace(temporary, path)
