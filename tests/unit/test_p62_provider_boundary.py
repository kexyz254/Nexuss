from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from nexuss.core.executor import execute_step
from nexuss.domain.models import (
    PlanStep,
    RiskTier,
    StepStatus,
)
from nexuss.intelligence.errors import IntelligenceError
from nexuss.intelligence.knowledge import (
    ExistingKnowledgeProviderAdapter,
)
from nexuss.knowledge.provider import KnowledgeProviderError


class NoSourcesProvider:
    def research(self, query: str) -> dict[str, object]:
        raise KnowledgeProviderError(
            "KNOWLEDGE_NO_SOURCES"
        )


class TopicProvider:
    def __init__(self) -> None:
        self.query = ""

    def research(
        self,
        query: str,
    ) -> dict[str, object]:
        self.query = query

        if query == "photosynthesis":
            return {
                "brief": "Photosynthesis.",
                "sources": [
                    {
                        "title": "Photosynthesis",
                        "url": (
                            "https://example.com/"
                            "photosynthesis"
                        ),
                        "provider": "Test source",
                        "extract": (
                            "Photosynthesis is the process "
                            "plants use to convert light energy "
                            "into chemical energy. Plants need "
                            "the resulting sugars for growth "
                            "and metabolism."
                        ),
                    }
                ],
            }

        return {
            "brief": "Inflation.",
            "sources": [
                {
                    "title": "Inflation",
                    "url": "https://example.com/inflation",
                    "provider": "Test source",
                    "extract": (
                        "Inflation is a sustained increase "
                        "in the general price level of goods "
                        "and services."
                    ),
                },
                {
                    "title": "Inflation (disambiguation)",
                    "url": (
                        "https://example.com/"
                        "inflation-disambiguation"
                    ),
                    "provider": "Test source",
                    "extract": (
                        "Inflation may refer to several "
                        "unrelated subjects."
                    ),
                },
                {
                    "title": "Body inflation",
                    "url": (
                        "https://example.com/"
                        "body-inflation"
                    ),
                    "provider": "Test source",
                    "extract": (
                        "Body inflation is an unrelated "
                        "use of the word inflation."
                    ),
                },
            ],
        }


def _step(question: str) -> PlanStep:
    return PlanStep(
        step_id=uuid4(),
        order=1,
        capability_id="knowledge.answer",
        risk_tier=RiskTier.LOW,
        expected_evidence=[
            "answer_with_provenance",
        ],
        parameters={"question": question},
        reversible=False,
    )


def test_no_sources_is_translated_to_intelligence_error() -> None:
    adapter = ExistingKnowledgeProviderAdapter(
        NoSourcesProvider()
    )

    with pytest.raises(IntelligenceError) as raised:
        adapter.retrieve(
            "photosynthesis",
            limit=5,
        )

    assert raised.value.code == (
        "INTELLIGENCE_NO_EVIDENCE"
    )


def test_executor_returns_failure_instead_of_raising() -> None:
    result = execute_step(
        _step("What is photosynthesis?"),
        observed_at=datetime.now(UTC),
        knowledge_provider=NoSourcesProvider(),
        session_id=uuid4(),
    )

    assert result.status is StepStatus.FAILED
    assert result.error_code == (
        "INTELLIGENCE_NO_EVIDENCE"
    )
    assert result.evidence == []


def test_compound_question_reduces_to_main_topic() -> None:
    provider = TopicProvider()
    adapter = ExistingKnowledgeProviderAdapter(
        provider
    )

    chunks = adapter.retrieve(
        (
            "What is photosynthesis and why "
            "do plants need it?"
        ),
        limit=5,
    )

    assert provider.query == "photosynthesis"
    assert len(chunks) == 1
    assert chunks[0].source.title == "Photosynthesis"


def test_exact_title_excludes_unrelated_collisions() -> None:
    provider = TopicProvider()
    adapter = ExistingKnowledgeProviderAdapter(
        provider
    )

    chunks = adapter.retrieve(
        "Explain inflation in simple terms.",
        limit=5,
    )

    assert provider.query == "inflation"
    assert [
        chunk.source.title
        for chunk in chunks
    ] == ["Inflation"]
