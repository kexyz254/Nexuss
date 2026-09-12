"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Durable SQLite-backed conversation store (P6.15).

Provides authoritative operations for conversation lifecycle and message
persistence. Storage survives Nexuss restart. The legacy single persisted
conversation is migrated into this store on first open.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID

from nexuss.conversation.models import (
    Conversation,
    ConversationStatus,
    Message,
    MessageRole,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_message_at TEXT,
    status TEXT NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    deleted_at TEXT,
    parent_conversation_id TEXT,
    origin_message_id TEXT,
    summary TEXT,
    summary_version INTEGER NOT NULL DEFAULT 0,
    message_count INTEGER NOT NULL DEFAULT 0,
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    origin_conversation_id TEXT,
    origin_message_id TEXT,
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages (conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_conversations_updated
    ON conversations (updated_at DESC);
"""


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _parse_iso(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _uuid(value: str | None) -> UUID | None:
    return UUID(value) if value else None


class ConversationStore:
    """SQLite-backed conversation and message persistence."""

    def __init__(self, database: Path | str) -> None:
        self._path = Path(database)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------
    def create_conversation(
        self,
        *,
        title: str = "New chat",
        parent_conversation_id: UUID | None = None,
        origin_message_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Conversation:
        conversation = Conversation.create(
            title=title,
            parent_conversation_id=parent_conversation_id,
            origin_message_id=origin_message_id,
            metadata=metadata,
        )
        self._conn.execute(
            """
            INSERT INTO conversations (
                conversation_id, title, created_at, updated_at, last_message_at,
                status, pinned, archived, deleted_at, parent_conversation_id,
                origin_message_id, summary, summary_version, message_count, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(conversation.conversation_id),
                conversation.title,
                _iso(conversation.created_at),
                _iso(conversation.updated_at),
                _iso(conversation.last_message_at),
                conversation.status.value,
                int(conversation.pinned),
                int(conversation.archived),
                _iso(conversation.deleted_at),
                str(conversation.parent_conversation_id)
                if conversation.parent_conversation_id
                else None,
                str(conversation.origin_message_id)
                if conversation.origin_message_id
                else None,
                conversation.summary,
                conversation.summary_version,
                conversation.message_count,
                json.dumps(conversation.metadata),
            ),
        )
        self._conn.commit()
        return conversation

    def get_conversation(self, conversation_id: UUID) -> Conversation | None:
        row = self._conn.execute(
            "SELECT * FROM conversations WHERE conversation_id = ?",
            (str(conversation_id),),
        ).fetchone()
        return self._row_to_conversation(row) if row else None

    def list_conversations(
        self,
        *,
        include_deleted: bool = False,
        include_archived: bool = True,
    ) -> list[Conversation]:
        clauses: list[str] = []
        params: list[Any] = []
        if not include_deleted:
            clauses.append("status != ?")
            params.append(ConversationStatus.DELETED.value)
        if not include_archived:
            clauses.append("archived = 0")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM conversations {where} ORDER BY pinned DESC, updated_at DESC",
            params,
        ).fetchall()
        return [self._row_to_conversation(r) for r in rows]

    def search_conversations(self, query: str, *, limit: int = 50) -> list[Conversation]:
        pattern = f"%{query}%"
        rows = self._conn.execute(
            """
            SELECT * FROM conversations
            WHERE status != ? AND (title LIKE ? OR summary LIKE ?)
            ORDER BY pinned DESC, updated_at DESC
            LIMIT ?
            """,
            (ConversationStatus.DELETED.value, pattern, pattern, limit),
        ).fetchall()
        return [self._row_to_conversation(r) for r in rows]

    def update_conversation(
        self,
        conversation_id: UUID,
        *,
        title: str | None = None,
        pinned: bool | None = None,
        archived: bool | None = None,
        summary: str | None = None,
        summary_version: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Conversation | None:
        current = self.get_conversation(conversation_id)
        if current is None:
            return None
        new_title = title if title is not None else current.title
        new_pinned = pinned if pinned is not None else current.pinned
        new_archived = archived if archived is not None else current.archived
        new_summary = summary if summary is not None else current.summary
        new_summary_version = (
            summary_version if summary_version is not None else current.summary_version
        )
        new_metadata = metadata if metadata is not None else current.metadata
        now = datetime.now(UTC)
        self._conn.execute(
            """
            UPDATE conversations
            SET title = ?, pinned = ?, archived = ?, summary = ?,
                summary_version = ?, metadata = ?, updated_at = ?
            WHERE conversation_id = ?
            """,
            (
                new_title,
                int(new_pinned),
                int(new_archived),
                new_summary,
                new_summary_version,
                json.dumps(new_metadata),
                _iso(now),
                str(conversation_id),
            ),
        )
        self._conn.commit()
        return self.get_conversation(conversation_id)

    def soft_delete(self, conversation_id: UUID) -> Conversation | None:
        current = self.get_conversation(conversation_id)
        if current is None:
            return None
        now = datetime.now(UTC)
        self._conn.execute(
            """
            UPDATE conversations
            SET status = ?, deleted_at = ?, updated_at = ?
            WHERE conversation_id = ?
            """,
            (ConversationStatus.DELETED.value, _iso(now), _iso(now), str(conversation_id)),
        )
        self._conn.commit()
        return self.get_conversation(conversation_id)

    def restore(self, conversation_id: UUID) -> Conversation | None:
        current = self.get_conversation(conversation_id)
        if current is None:
            return None
        now = datetime.now(UTC)
        self._conn.execute(
            """
            UPDATE conversations
            SET status = ?, deleted_at = NULL, updated_at = ?
            WHERE conversation_id = ?
            """,
            (ConversationStatus.ACTIVE.value, _iso(now), str(conversation_id)),
        )
        self._conn.commit()
        return self.get_conversation(conversation_id)

    def hard_delete(self, conversation_id: UUID) -> bool:
        """Permanently remove a conversation and its messages."""
        cur = self._conn.execute(
            "DELETE FROM messages WHERE conversation_id = ?", (str(conversation_id),)
        )
        cur2 = self._conn.execute(
            "DELETE FROM conversations WHERE conversation_id = ?", (str(conversation_id),)
        )
        self._conn.commit()
        return cur.rowcount > 0 or cur2.rowcount > 0

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------
    def add_message(self, message: Message) -> Message:
        self._conn.execute(
            """
            INSERT INTO messages (
                message_id, conversation_id, role, content, created_at,
                metadata, origin_conversation_id, origin_message_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(message.message_id),
                str(message.conversation_id),
                message.role.value,
                message.content,
                _iso(message.created_at),
                json.dumps(message.metadata),
                str(message.origin_conversation_id)
                if message.origin_conversation_id
                else None,
                str(message.origin_message_id) if message.origin_message_id else None,
            ),
        )
        self._conn.execute(
            """
            UPDATE conversations
            SET message_count = message_count + 1,
                last_message_at = ?, updated_at = ?
            WHERE conversation_id = ?
            """,
            (_iso(message.created_at), _iso(message.created_at), str(message.conversation_id)),
        )
        self._conn.commit()
        return message

    def list_messages(
        self, conversation_id: UUID, *, limit: int | None = None
    ) -> list[Message]:
        query = """
            SELECT * FROM messages WHERE conversation_id = ?
            ORDER BY created_at ASC
        """
        params: list[Any] = [str(conversation_id)]
        if limit is not None:
            query = """
                SELECT * FROM (
                    SELECT * FROM messages WHERE conversation_id = ?
                    ORDER BY created_at DESC LIMIT ?
                ) ORDER BY created_at ASC
            """
            params = [str(conversation_id), limit]
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_message(r) for r in rows]

    def get_message(self, message_id: UUID) -> Message | None:
        row = self._conn.execute(
            "SELECT * FROM messages WHERE message_id = ?", (str(message_id),)
        ).fetchone()
        return self._row_to_message(row) if row else None

    # ------------------------------------------------------------------
    # Migration / compatibility
    # ------------------------------------------------------------------
    def migrate_legacy_conversation(
        self, *, title: str, messages: Iterable[tuple[str, str, str]]
    ) -> Conversation:
        """Import a legacy single persisted conversation.

        ``messages`` is an iterable of (role, content, iso_timestamp).
        Returns the migrated conversation, or the existing one if already
        migrated (idempotent).
        """
        existing = self.list_conversations()
        if existing:
            # Idempotent: do not duplicate the legacy conversation.
            return existing[0]
        conversation = self.create_conversation(title=title)
        for role, content, ts in messages:
            self.add_message(
                Message.create(
                    conversation.conversation_id,
                    MessageRole(role),
                    content,
                    now=_parse_iso(ts) or datetime.now(UTC),
                )
            )
        return conversation

    # ------------------------------------------------------------------
    # Row mapping
    # ------------------------------------------------------------------
    def _row_to_conversation(self, row: sqlite3.Row) -> Conversation:
        return Conversation(
            conversation_id=UUID(row["conversation_id"]),
            title=row["title"],
            created_at=_parse_iso(row["created_at"]) or datetime.now(UTC),
            updated_at=_parse_iso(row["updated_at"]) or datetime.now(UTC),
            last_message_at=_parse_iso(row["last_message_at"]),
            status=ConversationStatus(row["status"]),
            pinned=bool(row["pinned"]),
            archived=bool(row["archived"]),
            deleted_at=_parse_iso(row["deleted_at"]),
            parent_conversation_id=_uuid(row["parent_conversation_id"]),
            origin_message_id=_uuid(row["origin_message_id"]),
            summary=row["summary"],
            summary_version=row["summary_version"],
            message_count=row["message_count"],
            metadata=json.loads(row["metadata"] or "{}"),
        )

    def _row_to_message(self, row: sqlite3.Row) -> Message:
        return Message(
            message_id=UUID(row["message_id"]),
            conversation_id=UUID(row["conversation_id"]),
            role=MessageRole(row["role"]),
            content=row["content"],
            created_at=_parse_iso(row["created_at"]) or datetime.now(UTC),
            metadata=json.loads(row["metadata"] or "{}"),
            origin_conversation_id=_uuid(row["origin_conversation_id"]),
            origin_message_id=_uuid(row["origin_message_id"]),
        )
