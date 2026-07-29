from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from nexuss.engineering.archive_intake import (
    SecureArchiveIntake,
)
from nexuss.engineering.archive_publication import (
    ArchiveRepositoryImportPlanner,
)
from nexuss.engineering.errors import EngineeringError


def _receipt(tmp_path: Path, content: str = "hello"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / f"project-{len(content)}.zip"
    with zipfile.ZipFile(
        source,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        archive.writestr(
            "project/README.md",
            "# Project",
        )
        archive.writestr(
            "project/index.html",
            content,
        )
    return SecureArchiveIntake().intake(
        source,
        tmp_path / f"quarantine-{len(content)}",
    )


def test_new_repo_proposal_is_private_uninitialized_and_nonexecuting(
    tmp_path: Path,
) -> None:
    receipt = _receipt(tmp_path)

    proposal = (
        ArchiveRepositoryImportPlanner
        .prepare_new_private_repository(
            receipt,
            account_login="kexyz254",
            repository_name="fenril-task",
        )
    )

    assert proposal.private is True
    assert proposal.auto_init is False
    assert proposal.archive_contains_readme is True
    assert proposal.requires_two_approvals is True
    assert proposal.approval_channel == "phone"
    assert proposal.non_atomic is True
    assert proposal.automatic_rollback_available is False
    assert proposal.github_changed is False
    assert proposal.published is False
    assert len(proposal.repository_create_payload_sha256) == 64
    assert len(proposal.archive_publish_payload_sha256) == 64


def test_publication_hash_changes_with_archive_content(
    tmp_path: Path,
) -> None:
    first = _receipt(tmp_path / "first", "one")
    second = _receipt(tmp_path / "second", "two")

    first_proposal = (
        ArchiveRepositoryImportPlanner
        .prepare_new_private_repository(
            first,
            account_login="kexyz254",
            repository_name="fenril-task",
        )
    )
    second_proposal = (
        ArchiveRepositoryImportPlanner
        .prepare_new_private_repository(
            second,
            account_login="kexyz254",
            repository_name="fenril-task",
        )
    )

    assert (
        first_proposal.archive_publish_payload_sha256
        != second_proposal.archive_publish_payload_sha256
    )


def test_secret_findings_prohibit_proposal(
    tmp_path: Path,
) -> None:
    source = tmp_path / "secret.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(
            "project/config.txt",
            "Authorization: Bearer secret-token-value",
        )
    receipt = SecureArchiveIntake().intake(
        source,
        tmp_path / "quarantine",
    )

    with pytest.raises(EngineeringError) as captured:
        (
            ArchiveRepositoryImportPlanner
            .prepare_new_private_repository(
                receipt,
                account_login="kexyz254",
                repository_name="fenril-task",
            )
        )

    assert captured.value.code == (
        "ARCHIVE_PUBLICATION_PROHIBITED"
    )
