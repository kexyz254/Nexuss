from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from nexuss.engineering.archive_intake import (
    SecureArchiveIntake,
)
from nexuss.engineering.archive_publication import (
    ArchiveRepositoryImportPlanner,
)
from nexuss.engineering.errors import EngineeringError


def _default_quarantine() -> Path:
    local_app_data = os.getenv("LOCALAPPDATA")
    if not local_app_data:
        raise EngineeringError(
            "ARCHIVE_LOCAL_APP_DATA_UNAVAILABLE",
            "The local application-data directory is unavailable.",
        )
    return (
        Path(local_app_data)
        / "Nexuss"
        / "archive-intake"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Quarantine and inspect a ZIP archive for a new "
            "private GitHub repository. No GitHub write occurs."
        )
    )
    parser.add_argument(
        "--zip",
        dest="archive_path",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--repository",
        required=True,
    )
    parser.add_argument(
        "--account",
        default="kexyz254",
    )
    parser.add_argument(
        "--branch",
        default="main",
    )
    parser.add_argument(
        "--commit-message",
        default="feat: import repository archive",
    )
    args = parser.parse_args()

    try:
        receipt = SecureArchiveIntake().intake(
            args.archive_path,
            _default_quarantine(),
        )
        proposal = (
            ArchiveRepositoryImportPlanner
            .prepare_new_private_repository(
                receipt,
                account_login=args.account,
                repository_name=args.repository,
                branch=args.branch,
                commit_message=args.commit_message,
            )
        )
    except EngineeringError as exc:
        print()
        print("=" * 72)
        print("NEXUSS ARCHIVE INTAKE")
        print("=" * 72)
        print(f"STOPPED: {exc.code}")
        print(exc.message)
        print("Repository created: False")
        print("GitHub changed:     False")
        print("Published:          False")
        print("Credentials exposed: False")
        return 2

    preview_path = (
        Path(receipt.quarantine_root)
        / "REPOSITORY-IMPORT-PREVIEW.json"
    )
    preview_path.write_text(
        json.dumps(
            proposal.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 72)
    print("NEXUSS SECURE ARCHIVE INTAKE")
    print("=" * 72)
    print(f"Archive:              {receipt.archive_name}")
    print(f"Archive SHA-256:      {receipt.archive_sha256}")
    print(f"Manifest SHA-256:     {receipt.manifest_sha256}")
    print(f"Files:                {receipt.file_count}")
    print(
        f"Expanded bytes:       "
        f"{receipt.total_uncompressed_bytes}"
    )
    print(
        f"Stripped root:        "
        f"{receipt.stripped_single_root or 'none'}"
    )
    print(f"Publication allowed:  {receipt.publication_allowed}")
    print(f"Account:              {proposal.account_login}")
    print(f"Repository:           {proposal.repository_name}")
    print(f"Private:              {proposal.private}")
    print(f"Auto initialize:      {proposal.auto_init}")
    print(f"Target branch:        {proposal.branch}")
    print(
        f"Archive has README:   "
        f"{proposal.archive_contains_readme}"
    )
    print(
        f"Approvals required:   "
        f"{len(proposal.approval_phases)}"
    )
    print(f"Approval channel:     {proposal.approval_channel}")
    print(f"Non-atomic operation: {proposal.non_atomic}")
    print("Repository created:   False")
    print("GitHub changed:       False")
    print("Published:            False")
    print("Credentials exposed:  False")
    print(f"Quarantine:           {receipt.quarantine_root}")
    print(f"Preview:              {preview_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
