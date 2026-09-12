"""Conversation journal export without automatic semantic-memory promotion."""

from __future__ import annotations

import hashlib

from nexuss.conversation.models import (
    ConversationRecord,
    StoredConversationMessage,
)


def build_session_markdown(
    conversation: ConversationRecord,
    messages: tuple[StoredConversationMessage, ...],
) -> tuple[str, str]:
    lines = [
        f"# Nexuss Session — {conversation.title}",
        "",
        f"- Conversation ID: `{conversation.conversation_id}`",
        f"- Provider: `{conversation.provider_id}`",
        f"- Model: `{conversation.model}`",
        f"- Created: `{conversation.created_at.isoformat()}`",
        f"- Updated: `{conversation.updated_at.isoformat()}`",
        "",
        "## Transcript",
        "",
    ]

    for message in messages:
        speaker = (
            "User"
            if message.role.value == "user"
            else "Nexuss"
        )
        lines.extend(
            [
                f"### {speaker} — {message.created_at.isoformat()}",
                "",
                message.text.strip(),
                "",
            ]
        )

    markdown = "\n".join(lines).strip() + "\n"
    digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    return markdown, digest
