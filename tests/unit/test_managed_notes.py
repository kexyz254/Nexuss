"""Managed note security, verification, and rollback tests."""

from pathlib import Path

import pytest

from nexuss.core.managed_notes import (
    InvalidNoteError,
    ManagedNoteStore,
    NoteAlreadyExistsError,
    NoteVerificationError,
    prepare_note,
)


def test_create_note_is_atomic_verified_and_private(tmp_path: Path) -> None:
    store = ManagedNoteStore(tmp_path)
    prepared = prepare_note("Launch checklist", "# Launch checklist\n\n- [ ] Verify P3\n")

    created = store.create(prepared)

    assert created.path.parent == tmp_path.resolve()
    assert created.path.read_text(encoding="utf-8") == prepared.content
    assert created.sha256 == prepared.content_sha256
    assert created.byte_count == len(prepared.content_bytes)


def test_create_note_never_overwrites(tmp_path: Path) -> None:
    store = ManagedNoteStore(tmp_path)
    prepared = prepare_note("Existing", "first")
    store.create(prepared)

    with pytest.raises(NoteAlreadyExistsError, match="NOTE_ALREADY_EXISTS"):
        store.create(prepared)

    assert (tmp_path / "Existing.md").read_text(encoding="utf-8") == "first\n"


@pytest.mark.parametrize("title", ["../escape", "folder/note", r"folder\note", "CON"])
def test_unsafe_note_titles_are_rejected(title: str) -> None:
    with pytest.raises(InvalidNoteError):
        prepare_note(title, "safe content")


def test_rollback_deletes_only_matching_file(tmp_path: Path) -> None:
    store = ManagedNoteStore(tmp_path)
    created = store.create(prepare_note("Rollback", "receipt-owned content"))

    removed = store.rollback(filename=created.filename, expected_sha256=created.sha256)

    assert removed == created.path
    assert not created.path.exists()


def test_rollback_rejects_modified_file(tmp_path: Path) -> None:
    store = ManagedNoteStore(tmp_path)
    created = store.create(prepare_note("Protected", "original"))
    created.path.write_text("modified\n", encoding="utf-8")

    with pytest.raises(NoteVerificationError, match="ROLLBACK_HASH_MISMATCH"):
        store.rollback(filename=created.filename, expected_sha256=created.sha256)

    assert created.path.exists()
