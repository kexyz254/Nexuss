from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from nexuss.core.executor import execute_step
from nexuss.domain.models import (
    PlanStep,
    RiskTier,
    StepStatus,
)
from nexuss.intelligence.knowledge import (
    ExistingKnowledgeProviderAdapter,
)


class PublicKnowledgeProvider:
    def research(self, query: str) -> dict[str, object]:
        return {
            "brief": "Public answer.",
            "sources": [
                {
                    "title": "Foreign exchange market",
                    "url": "https://example.com/forex",
                    "provider": "Test source",
                    "extract": (
                        "The foreign exchange market is where "
                        "currencies are exchanged, and prices can "
                        "respond to inflation, interest rates, "
                        "economic growth, and market sentiment."
                    ),
                }
            ],
        }


class IrrelevantMemoryStore:
    def recall(
        self,
        query: str,
        *,
        limit: int,
        now: datetime,
    ) -> tuple[object, ...]:
        return (
            SimpleNamespace(
                score=0.99,
                decayed_confidence=0.95,
                claim=SimpleNamespace(
                    statement=(
                        "Peter is the Nexuss founder."
                    ),
                    source_ref="user",
                    source_trust=SimpleNamespace(
                        value="user_asserted"
                    ),
                ),
            ),
        )


class RecordingProvider:
    def __init__(self) -> None:
        self.query = ""

    def research(self, query: str) -> dict[str, object]:
        self.query = query
        return {
            "brief": "",
            "sources": [
                {
                    "title": "Stagflation",
                    "url": "https://example.com/stagflation",
                    "provider": "Test source",
                    "extract": (
                        "Stagflation combines high inflation "
                        "with weak economic growth."
                    ),
                },
                {
                    "title": "Inflation",
                    "url": "https://example.com/inflation",
                    "provider": "Test source",
                    "extract": (
                        "Inflation is a sustained increase in "
                        "the general price level of goods "
                        "and services."
                    ),
                },
            ],
        }


def _knowledge_step(question: str) -> PlanStep:
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


def test_unrelated_memory_cannot_answer_world_question() -> None:
    result = execute_step(
        _knowledge_step(
            "What is the foreign exchange market?"
        ),
        observed_at=datetime.now(UTC),
        knowledge_provider=PublicKnowledgeProvider(),
        memory_store=IrrelevantMemoryStore(),
        session_id=uuid4(),
    )

    assert result.status is StepStatus.VERIFIED

    attributes = result.evidence[0].attributes

    assert attributes["answer_path"] == "public_web"
    assert attributes["provider_id"] == (
        "local_extractive_v1"
    )
    assert "Peter" not in str(attributes["brief"])


def test_ambiguous_remember_request_fails_closed() -> None:
    step = PlanStep(
        step_id=uuid4(),
        order=1,
        capability_id="memory.remember",
        risk_tier=RiskTier.LOW,
        expected_evidence=[
            "memory_claim_stored",
        ],
        parameters={
            "statement": "that",
            "topic": "that",
        },
        reversible=True,
    )

    result = execute_step(
        step,
        observed_at=datetime.now(UTC),
        memory_store=object(),
    )

    assert result.status is StepStatus.FAILED
    assert result.error_code == (
        "MEMORY_STATEMENT_AMBIGUOUS"
    )


def test_retrieval_query_removes_conversational_noise() -> None:
    provider = RecordingProvider()
    adapter = ExistingKnowledgeProviderAdapter(
        provider
    )

    chunks = adapter.retrieve(
        "Explain inflation in simple terms.",
        limit=5,
    )

    assert provider.query == "inflation"
    assert len(chunks) == 1
    assert chunks[0].source.title == "Inflation"
    assert chunks[0].retrieval_score == 1.0
