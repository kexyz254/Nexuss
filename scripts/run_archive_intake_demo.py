from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

from nexuss.engineering.archive_intake import (
    SecureArchiveIntake,
)
from nexuss.engineering.archive_publication import (
    ArchiveRepositoryImportPlanner,
)


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="nexuss-archive-demo-"))
    archive_path = root / "fenril-task.zip"

    with zipfile.ZipFile(
        archive_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        archive.writestr(
            "fenril-task/index.html",
            (
                "<!doctype html><title>Fenril Task</title>"
                "<main><h1>Fenril Task</h1></main>"
            ),
        )
        archive.writestr(
            "fenril-task/styles.css",
            "body { margin: 0; font-family: system-ui; }",
        )

    receipt = SecureArchiveIntake().intake(
        archive_path,
        root / "quarantine",
    )
    proposal = (
        ArchiveRepositoryImportPlanner
        .prepare_new_private_repository(
            receipt,
            account_login="kexyz254",
            repository_name="fenril-task",
        )
    )

    print()
    print("=" * 72)
    print("NEXUSS ARCHIVE INTAKE OFFLINE DEMO")
    print("=" * 72)
    print(f"Archive:            {receipt.archive_name}")
    print(f"Files:              {receipt.file_count}")
    print(
        f"Stripped root:      "
        f"{receipt.stripped_single_root}"
    )
    print(f"Security findings:  {len(receipt.security_findings)}")
    print(f"Publication ready:  {receipt.publication_allowed}")
    print(f"Repository:         {proposal.repository_name}")
    print(f"Private:            {proposal.private}")
    print(f"Auto initialize:    {proposal.auto_init}")
    print(
        f"Approvals required: "
        f"{len(proposal.approval_phases)}"
    )
    print("Repository created: False")
    print("GitHub changed:     False")
    print("Published:          False")
    print("Credentials exposed: False")
    print(f"Quarantine:         {receipt.quarantine_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
