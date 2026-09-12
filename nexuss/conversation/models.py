"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Conversation domain model for the multi-conversation workspace (P6.15).

A conversation is the durable container for one chat. Messages retain stable
IDs and their conversation IDs. The legacy single persisted conversation is
migrated into this model rather than discarded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class ConversationStatus(str, Enum):
    """Lifecycle state of a conversation."""

    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


class MessageRole(str, Enum):
    """Author of a message within a conversation."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


@dataclass(frozen=True)
class Message:
    """A single message inside a conversation.

    Messages are immutable once written; edits create new revisions rather
    than mutating history, preserving provenance.
    """

    message_id: UUID
    conversation_id: UUID
    role: MessageRole
    content: str
    created_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)
    # Optional provenance links for cross-chat sharing / forking.
    origin_conversation_id: UUID | None = None
    origin_message_id: UUID | None = None

    @classmethod
    def create(
        cls,
        conversation_id: UUID,
        role: MessageRole,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
        origin_conversation_id: UUID | None = None,
        origin_message_id: UUID | None = None,
        now: datetime | None = None,
    ) -> "Message":
        return cls(
            message_id=uuid4(),
            conversation_id=conversation_id,
            role=role,
            content=content,
            created_at=now or datetime.now(UTC),
            metadata=metadata or {},
            origin_conversation_id=origin_conversation_id,
            origin_message_id=origin_message_id,
        )


@dataclass
class Conversation:
    """The authoritative conversation record."""

    conversation_id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None
    status: ConversationStatus
    pinned: bool
    archived: bool
    deleted_at: datetime | None
    parent_conversation_id: UUID | None
    origin_message_id: UUID | None
    summary: str | None
    summary_version: int
    message_count: int
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        title: str = "New chat",
        parent_conversation_id: UUID | None = None,
        origin_message_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> "Conversation":
        ts = now or datetime.now(UTC)
        return cls(
            conversation_id=uuid4(),
            title=title,
            created_at=ts,
            updated_at=ts,
            last_message_at=None,
            status=ConversationStatus.ACTIVE,
            pinned=False,
            archived=False,
            deleted_at=None,
            parent_conversation_id=parent_conversation_id,
            origin_message_id=origin_message_id,
            summary=None,
            summary_version=0,
            message_count=0,
            metadata=metadata or {},
        )

    @property
    def is_deleted(self) -> bool:
        return self.status is ConversationStatus.DELETED or self.deleted_at is not None

    @property
    def is_archived(self) -> bool:
        return self.archived or self.status is ConversationStatus.ARCHIVED


@dataclass(frozen=True)
class ConversationSummary:
    """A compact durable summary of one conversation."""

    conversation_id: UUID
    summary: str
    version: int
    created_at: datetime
    message_span: tuple[UUID, UUID] | None = None
