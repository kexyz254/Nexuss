from __future__ import annotations

import zipfile
from uuid import uuid4

import pytest

from nexuss.chat_files.store import ChatFileError, WorkspaceFileStore


def test_attachment_context_is_conversation_scoped(tmp_path) -> None:
    store = WorkspaceFileStore(tmp_path)
    conversation_id = uuid4()
    session_id = uuid4()
    record = store.save_attachment(
        conversation_id=conversation_id,
        user_session_id=session_id,
        name="notes.md",
        media_type="text/markdown",
        data=b"# Incident\nThe API returned 503 after deploy.",
    )

    context = store.context_for(
        attachment_ids=(record.attachment_id,),
        conversation_id=conversation_id,
        user_session_id=session_id,
    )

    assert "notes.md" in context
    assert "API returned 503" in context
    assert "UNTRUSTED CONTENT" in context
    assert record.extracted_chars > 0

    with pytest.raises(ChatFileError, match="another conversation"):
        store.context_for(
            attachment_ids=(record.attachment_id,),
            conversation_id=uuid4(),
            user_session_id=session_id,
        )


def test_package_artifact_contains_original_files(tmp_path) -> None:
    store = WorkspaceFileStore(tmp_path)
    conversation_id = uuid4()
    session_id = uuid4()
    first = store.save_attachment(
        conversation_id=conversation_id,
        user_session_id=session_id,
        name="a.txt",
        media_type="text/plain",
        data=b"alpha",
    )
    second = store.save_attachment(
        conversation_id=conversation_id,
        user_session_id=session_id,
        name="b.txt",
        media_type="text/plain",
        data=b"beta",
    )

    artifact = store.create_package(
        conversation_id=conversation_id,
        user_session_id=session_id,
        attachment_ids=(first.attachment_id, second.attachment_id),
        name="bundle.zip",
    )
    resolved = store.get_artifact(artifact.artifact_id)

    assert resolved is not None
    record, path = resolved
    assert record.name == "bundle.zip"
    assert record.size_bytes > 0

    with zipfile.ZipFile(path) as archive:
        assert archive.read("a.txt") == b"alpha"
        assert archive.read("b.txt") == b"beta"


def test_text_artifact_is_downloadable_managed_output(tmp_path) -> None:
    store = WorkspaceFileStore(tmp_path)
    conversation_id = uuid4()
    session_id = uuid4()

    artifact = store.create_text_artifact(
        conversation_id=conversation_id,
        user_session_id=session_id,
        name="report.md",
        content="# Report\nVerified output.",
        media_type="text/markdown",
    )
    resolved = store.get_artifact(artifact.artifact_id)

    assert resolved is not None
    record, path = resolved
    assert record.sha256 == artifact.sha256
    assert path.read_text(encoding="utf-8").startswith("# Report")
