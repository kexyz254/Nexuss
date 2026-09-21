from __future__ import annotations

import io
import zipfile

from nexuss.chat_files.extract import extract_text


def _archive() -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "README.md",
            "# Recovery task\nInspect portability assumptions.",
        )
        archive.writestr(
            "src/check.py",
            "def verify():\n    return 'portable'\n",
        )
        archive.writestr(
            "assets/blob.bin",
            b"\x00\x01\x02\x03",
        )
    return stream.getvalue()


def test_zip_attachment_exposes_bounded_listing_and_text() -> None:
    text, status = extract_text(
        "neo-followup-recovery.zip",
        "application/x-zip-compressed",
        _archive(),
    )

    assert status == "extracted"
    assert "[ARCHIVE CONTENTS]" in text
    assert "README.md" in text
    assert "src/check.py" in text
    assert "Inspect portability assumptions." in text
    assert "return 'portable'" in text
