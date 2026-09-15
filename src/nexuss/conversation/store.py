"""SQLite persistence for resumable Nexuss conversations."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from nexuss.conversation.models import (
    ConversationRecord,
    ConversationRoute,
    MessageRole,
    StoredConversationMessage,
)


def default_conversation_database() -> Path:
    configured = os.environ.get("NEXUSS_CONVERSATION_DB", "").strip()

    if configured:
        return Path(configured).expanduser().resolve()

    local = os.environ.get("LOCALAPPDATA", "").strip()

    if local:
        return Path(local) / "Nexuss" / "conversations.sqlite3"

    return Path.home() / ".nexuss" / "conversations.sqlite3"


class SQLiteConversationStore:
    """Durable local thread storage with session ownership."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = (path or default_conversation_database()).resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    @property
    def path(self) -> Path:
        return self._path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._path,
            timeout=10.0,
            isolation_level=None,
        )
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialise(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    user_session_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    provider_id TEXT NOT NULL,
                    model TEXT NOT NULL,
                    continuation_token_sha256 TEXT NOT NULL,
                    pending_action TEXT,
                    pending_capability_hint TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS conversation_messages (
                    message_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    text TEXT NOT NULL,
                    route TEXT,
                    provider_id TEXT,
                    model TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id)
                        REFERENCES conversations(conversation_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS
                    idx_conversation_messages_thread
                ON conversation_messages(
                    conversation_id,
                    created_at
                );
                """
            )

    def create(
        self,
        *,
        conversation_id: UUID,
        user_session_id: UUID,
        title: str,
        provider_id: str,
        model: str,
        continuation_token: str,
    ) -> ConversationRecord:
        """Atomically create or securely rebind one conversation.

        P6.10G ATOMIC CONVERSATION CREATE OR REBIND. The write lock is acquired before checking for
        an existing row, so concurrent identical requests cannot both
        attempt the primary-key insert.
        """
        token_hash = hashlib.sha256(
            continuation_token.encode("utf-8")
        ).hexdigest()
        now = datetime.now(UTC)

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")

            try:
                existing = connection.execute(
                    """
                    SELECT
                        conversation_id,
                        user_session_id,
                        title,
                        provider_id,
                        model,
                        pending_action,
                        pending_capability_hint,
                        created_at,
                        updated_at,
                        continuation_token_sha256
                    FROM conversations
                    WHERE conversation_id = ?
                    """,
                    (str(conversation_id),),
                ).fetchone()

                if existing is not None:
                    if existing[9] != token_hash:
                        raise PermissionError(
                            "Conversation continuation token is invalid."
                        )

                    connection.execute(
                        """
                        UPDATE conversations
                        SET user_session_id = ?, updated_at = ?
                        WHERE conversation_id = ?
                        """,
                        (
                            str(user_session_id),
                            now.isoformat(),
                            str(conversation_id),
                        ),
                    )
                    connection.execute("COMMIT")

                    return ConversationRecord(
                        conversation_id=UUID(existing[0]),
                        user_session_id=user_session_id,
                        title=existing[2],
                        provider_id=existing[3],
                        model=existing[4],
                        pending_action=existing[5],
                        pending_capability_hint=existing[6],
                        created_at=datetime.fromisoformat(existing[7]),
                        updated_at=now,
                    )

                record = ConversationRecord(
                    conversation_id=conversation_id,
                    user_session_id=user_session_id,
                    title=title.strip() or "New conversation",
                    provider_id=provider_id,
                    model=model,
                    created_at=now,
                    updated_at=now,
                )

                connection.execute(
                    """
                    INSERT INTO conversations (
                        conversation_id,
                        user_session_id,
                        title,
                        provider_id,
                        model,
                        continuation_token_sha256,
                        pending_action,
                        pending_capability_hint,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
                    """,
                    (
                        str(record.conversation_id),
                        str(record.user_session_id),
                        record.title,
                        record.provider_id,
                        record.model,
                        token_hash,
                        record.created_at.isoformat(),
                        record.updated_at.isoformat(),
                    ),
                )
                connection.execute("COMMIT")
                return record
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def get(self, conversation_id: UUID) -> ConversationRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    conversation_id,
                    user_session_id,
                    title,
                    provider_id,
                    model,
                    pending_action,
                    pending_capability_hint,
                    created_at,
                    updated_at
                FROM conversations
                WHERE conversation_id = ?
                """,
                (str(conversation_id),),
            ).fetchone()

        if row is None:
            return None

        return ConversationRecord(
            conversation_id=UUID(row[0]),
            user_session_id=UUID(row[1]),
            title=row[2],
            provider_id=row[3],
            model=row[4],
            pending_action=row[5],
            pending_capability_hint=row[6],
            created_at=datetime.fromisoformat(row[7]),
            updated_at=datetime.fromisoformat(row[8]),
        )

    def list_for_session(
        self,
        user_session_id: UUID,
        *,
        limit: int = 30,
    ) -> tuple[ConversationRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    conversation_id,
                    user_session_id,
                    title,
                    provider_id,
                    model,
                    pending_action,
                    pending_capability_hint,
                    created_at,
                    updated_at
                FROM conversations
                WHERE user_session_id = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (str(user_session_id), limit),
            ).fetchall()

        return tuple(
            ConversationRecord(
                conversation_id=UUID(row[0]),
                user_session_id=UUID(row[1]),
                title=row[2],
                provider_id=row[3],
                model=row[4],
                pending_action=row[5],
                pending_capability_hint=row[6],
                created_at=datetime.fromisoformat(row[7]),
                updated_at=datetime.fromisoformat(row[8]),
            )
            for row in rows
        )

    def append_message(
        self,
        *,
        conversation_id: UUID,
        role: MessageRole,
        text: str,
        route: ConversationRoute | None = None,
        provider_id: str | None = None,
        model: str | None = None,
    ) -> StoredConversationMessage:
        now = datetime.now(UTC)
        message = StoredConversationMessage(
            message_id=uuid4(),
            conversation_id=conversation_id,
            role=role,
            text=text,
            route=route,
            provider_id=provider_id,
            model=model,
            created_at=now,
        )

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO conversation_messages (
                    message_id,
                    conversation_id,
                    role,
                    text,
                    route,
                    provider_id,
                    model,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(message.message_id),
                    str(message.conversation_id),
                    message.role.value,
                    message.text,
                    (
                        message.route.value
                        if message.route is not None
                        else None
                    ),
                    message.provider_id,
                    message.model,
                    message.created_at.isoformat(),
                ),
            )
            connection.execute(
                """
                UPDATE conversations
                SET updated_at = ?
                WHERE conversation_id = ?
                """,
                (now.isoformat(), str(conversation_id)),
            )
            connection.execute("COMMIT")

        return message


    def append_turn(
        self,
        *,
        conversation_id: UUID,
        user_text: str,
        assistant_text: str,
        route: ConversationRoute,
        provider_id: str,
        model: str,
        pending_action: str | None,
        pending_capability_hint: str | None,
    ) -> tuple[
        StoredConversationMessage,
        StoredConversationMessage,
        ConversationRecord,
    ]:
        """Persist one validated user/assistant turn atomically."""

        now = datetime.now(UTC)
        user_message = StoredConversationMessage(
            message_id=uuid4(),
            conversation_id=conversation_id,
            role=MessageRole.USER,
            text=user_text,
            created_at=now,
        )
        assistant_message = StoredConversationMessage(
            message_id=uuid4(),
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            text=assistant_text,
            route=route,
            provider_id=provider_id,
            model=model,
            created_at=now,
        )

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")

            for message in (user_message, assistant_message):
                connection.execute(
                    """
                    INSERT INTO conversation_messages (
                        message_id,
                        conversation_id,
                        role,
                        text,
                        route,
                        provider_id,
                        model,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(message.message_id),
                        str(message.conversation_id),
                        message.role.value,
                        message.text,
                        (
                            message.route.value
                            if message.route is not None
                            else None
                        ),
                        message.provider_id,
                        message.model,
                        message.created_at.isoformat(),
                    ),
                )

            row = connection.execute(
                """
                SELECT title
                FROM conversations
                WHERE conversation_id = ?
                """,
                (str(conversation_id),),
            ).fetchone()

            if row is None:
                connection.execute("ROLLBACK")
                raise LookupError("Conversation was not found.")

            title = row[0]
            if title == "New conversation":
                compact = " ".join(user_text.split()).strip()
                title = compact[:76] + (
                    "…" if len(compact) > 76 else ""
                )
                title = title or "New conversation"

            connection.execute(
                """
                UPDATE conversations
                SET
                    title = ?,
                    pending_action = ?,
                    pending_capability_hint = ?,
                    updated_at = ?
                WHERE conversation_id = ?
                """,
                (
                    title,
                    pending_action,
                    pending_capability_hint,
                    now.isoformat(),
                    str(conversation_id),
                ),
            )
            connection.execute("COMMIT")

        record = self.get(conversation_id)
        if record is None:
            raise LookupError("Conversation disappeared after commit.")

        return user_message, assistant_message, record

    def messages(
        self,
        conversation_id: UUID,
        *,
        limit: int = 200,
    ) -> tuple[StoredConversationMessage, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    message_id,
                    conversation_id,
                    role,
                    text,
                    route,
                    provider_id,
                    model,
                    created_at
                FROM conversation_messages
                WHERE conversation_id = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (str(conversation_id), limit),
            ).fetchall()

        return tuple(
            StoredConversationMessage(
                message_id=UUID(row[0]),
                conversation_id=UUID(row[1]),
                role=MessageRole(row[2]),
                text=row[3],
                route=(
                    ConversationRoute(row[4])
                    if row[4]
                    else None
                ),
                provider_id=row[5],
                model=row[6],
                created_at=datetime.fromisoformat(row[7]),
            )
            for row in rows
        )

    def rename(
        self,
        conversation_id: UUID,
        *,
        title: str,
    ) -> ConversationRecord | None:
        normalized = " ".join(title.split()).strip()
        if not normalized:
            raise ValueError("Conversation title cannot be empty.")

        now = datetime.now(UTC)

        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE conversations
                SET title = ?, updated_at = ?
                WHERE conversation_id = ?
                """,
                (
                    normalized[:160],
                    now.isoformat(),
                    str(conversation_id),
                ),
            )

        if cursor.rowcount != 1:
            return None

        return self.get(conversation_id)

    def delete(self, conversation_id: UUID) -> bool:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                DELETE FROM conversations
                WHERE conversation_id = ?
                """,
                (str(conversation_id),),
            )
            connection.execute("COMMIT")

        return cursor.rowcount == 1

    def recent_context(
        self,
        conversation_id: UUID,
        *,
        limit: int = 16,
        maximum_characters: int = 24_000,
    ) -> str:
        messages = self.messages(conversation_id, limit=500)[-limit:]
        rendered: list[str] = []
        total = 0

        for message in reversed(messages):
            line = (
                f"{message.role.value.upper()}: "
                f"{message.text.strip()}"
            )
            if total + len(line) > maximum_characters:
                break
            rendered.append(line)
            total += len(line)

        return "\n".join(reversed(rendered))

    def set_pending_action(
        self,
        *,
        conversation_id: UUID,
        pending_action: str | None,
        capability_hint: str | None,
    ) -> ConversationRecord:
        now = datetime.now(UTC)

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE conversations
                SET
                    pending_action = ?,
                    pending_capability_hint = ?,
                    updated_at = ?
                WHERE conversation_id = ?
                """,
                (
                    pending_action,
                    capability_hint,
                    now.isoformat(),
                    str(conversation_id),
                ),
            )
            connection.execute("COMMIT")

        record = self.get(conversation_id)

        if record is None:
            raise LookupError("Conversation disappeared after update.")

        return record

    def update_title_from_first_message(
        self,
        conversation_id: UUID,
        text: str,
    ) -> None:
        record = self.get(conversation_id)

        if record is None or record.title != "New conversation":
            return

        compact = " ".join(text.split()).strip()
        title = compact[:76] + ("…" if len(compact) > 76 else "")

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE conversations
                SET title = ?
                WHERE conversation_id = ?
                """,
                (title or "New conversation", str(conversation_id)),
            )
