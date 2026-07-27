from __future__ import annotations

from uuid import uuid4

from nexuss.intelligence.context import (
    ContextResolver,
    ConversationContextStore,
)
from nexuss.intelligence.models import ConversationTurn


def test_second_section_resolves_against_prior_answer() -> None:
    session = uuid4()
    store = ConversationContextStore()
    store.append(
        session,
        ConversationTurn(
            role="assistant",
            content="Three methods.",
            topic="forex risk management",
            answer_sections=(
                "Position sizing",
                "Stop-loss orders",
                "Risk-reward ratios",
            ),
        ),
    )

    resolution = ContextResolver().resolve(
        "Explain the second method more simply.",
        store.recent(session),
    )

    assert resolution.used_prior_context is True
    assert resolution.current_topic == "forex risk management"
    assert resolution.referenced_section == "Stop-loss orders"
    assert "Stop-loss orders" in resolution.resolved_query
