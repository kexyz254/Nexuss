from __future__ import annotations

import stat
import zipfile
from pathlib import Path

import pytest

from nexuss.engineering.archive_intake import (
    ArchiveIntakePolicy,
    SecureArchiveIntake,
)
from nexuss.engineering.errors import EngineeringError


def _zip(
    path: Path,
    entries: dict[str, str | bytes],
) -> Path:
    with zipfile.ZipFile(
        path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return path


def test_safe_archive_is_stripped_hashed_and_extracted(
    tmp_path: Path,
) -> None:
    source = _zip(
        tmp_path / "project.zip",
        {
            "project/index.html": "<main>Hello</main>",
            "project/styles.css": "body { margin: 0; }",
        },
    )

    receipt = SecureArchiveIntake().intake(
        source,
        tmp_path / "quarantine",
    )

    assert receipt.publication_allowed is True
    assert receipt.stripped_single_root == "project"
    assert [entry.repository_path for entry in receipt.entries] == [
        "index.html",
        "styles.css",
    ]
    assert len(receipt.archive_sha256) == 64
    assert len(receipt.manifest_sha256) == 64
    assert (
        Path(receipt.extracted_root) / "index.html"
    ).is_file()
    assert receipt.github_changed is False


@pytest.mark.parametrize(
    "path",
    (
        "../../escape.txt",
        r"..\..\escape.txt",
        "/absolute.txt",
        r"C:\absolute.txt",
        "folder/file.txt:stream",
        "folder/CON.txt",
        "folder/name. ",
    ),
)
def test_unsafe_paths_are_rejected(
    tmp_path: Path,
    path: str,
) -> None:
    source = _zip(
        tmp_path / "unsafe.zip",
        {path: "blocked"},
    )

    with pytest.raises(EngineeringError):
        SecureArchiveIntake().intake(
            source,
            tmp_path / "quarantine",
        )


def test_symlink_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "symlink.zip"
    info = zipfile.ZipInfo("project/link")
    info.create_system = 3
    info.external_attr = (
        stat.S_IFLNK | 0o777
    ) << 16

    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(info, "target")

    with pytest.raises(EngineeringError) as captured:
        SecureArchiveIntake().intake(
            source,
            tmp_path / "quarantine",
        )

    assert captured.value.code == "ARCHIVE_SYMLINK_PROHIBITED"


def test_case_collision_is_rejected(
    tmp_path: Path,
) -> None:
    source = _zip(
        tmp_path / "collision.zip",
        {
            "project/Readme.md": "one",
            "project/README.md": "two",
        },
    )

    with pytest.raises(EngineeringError) as captured:
        SecureArchiveIntake().intake(
            source,
            tmp_path / "quarantine",
        )

    assert captured.value.code == "ARCHIVE_PATH_COLLISION"


def test_compression_bomb_ratio_is_rejected(
    tmp_path: Path,
) -> None:
    source = _zip(
        tmp_path / "ratio.zip",
        {"project/repeated.txt": "0" * 100_000},
    )
    service = SecureArchiveIntake(
        ArchiveIntakePolicy(
            max_compression_ratio=2.0,
        )
    )

    with pytest.raises(EngineeringError) as captured:
        service.intake(
            source,
            tmp_path / "quarantine",
        )

    assert captured.value.code == (
        "ARCHIVE_COMPRESSION_RATIO_LIMIT"
    )


def test_secret_content_blocks_publication(
    tmp_path: Path,
) -> None:
    source = _zip(
        tmp_path / "secret.zip",
        {
            "project/config.txt": (
                "Authorization: Bearer "
                "very-secret-token-value"
            )
        },
    )

    receipt = SecureArchiveIntake().intake(
        source,
        tmp_path / "quarantine",
    )

    assert receipt.publication_allowed is False
    assert receipt.security_findings
    assert "very-secret-token-value" not in (
        receipt.model_dump_json()
    )


@pytest.mark.parametrize(
    ("path", "code"),
    (
        (
            "project/.git/config",
            "ARCHIVE_GIT_METADATA_PROHIBITED",
        ),
        (
            "project/.github/workflows/build.yml",
            "ARCHIVE_WORKFLOW_FILE_PROHIBITED",
        ),
        (
            "project/.env",
            "ARCHIVE_SECRET_FILENAME_PROHIBITED",
        ),
        (
            "project/assets/vendor.zip",
            "ARCHIVE_NESTED_ARCHIVE_PROHIBITED",
        ),
    ),
)
def test_prohibited_repository_content_is_rejected(
    tmp_path: Path,
    path: str,
    code: str,
) -> None:
    source = _zip(
        tmp_path / "prohibited.zip",
        {path: "blocked"},
    )

    with pytest.raises(EngineeringError) as captured:
        SecureArchiveIntake().intake(
            source,
            tmp_path / "quarantine",
        )

    assert captured.value.code == code
