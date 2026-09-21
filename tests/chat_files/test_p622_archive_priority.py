from __future__ import annotations

import io
import zipfile

from nexuss.chat_files.extract import extract_text
from nexuss.cognitive.runtime import bound_cognitive_instruction


def _large_archive() -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("zzz/filler.txt", "x" * 70_000)
        archive.writestr(
            "README.md",
            "# Recovery Package\nImportant architecture and recovery notes.",
        )
        archive.writestr(
            "task.toml",
            "[task]\nname='neo-followup-recovery'\n",
        )
        archive.writestr(
            "src/main.py",
            "def recover():\n    return 'verified'\n",
        )
    return stream.getvalue()


def test_bounded_zip_window_keeps_high_signal_files() -> None:
    extracted, status = extract_text(
        "recovery.zip",
        "application/x-zip-compressed",
        _large_archive(),
    )
    provider_input = bound_cognitive_instruction(
        "Inspect this ZIP and summarize the important files.\n\n" + extracted
    )

    assert status == "extracted"
    assert "README.md" in provider_input
    assert "Important architecture and recovery notes." in provider_input
    assert "task.toml" in provider_input
    assert "neo-followup-recovery" in provider_input
    assert "src/main.py" in provider_input
    assert "return 'verified'" in provider_input
