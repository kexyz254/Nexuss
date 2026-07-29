from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from nexuss.core.executor import execute_step
from nexuss.domain.models import (
    PlanStep,
    RiskTier,
    StepStatus,
)


class FakeKnowledgeProvider:
    def research(self, query: str) -> dict[str, object]:
        assert query

        return {
            "brief": "Legacy provider brief.",
            "sources": [
                {
                    "title": "Foreign exchange overview",
                    "url": "https://example.com/forex",
                    "provider": "Test reference",
                    "extract": (
                        "The foreign exchange market is a global "
                        "market where currencies are exchanged. "
                        "Exchange rates can respond to interest "
                        "rates, inflation, economic growth, "
                        "political risk, and market sentiment."
                    ),
                },
                {
                    "title": "Foreign exchange risk management",
                    "url": "https://example.com/forex-risk",
                    "provider": "Test reference",
                    "extract": (
                        "Common risk controls include position "
                        "sizing, stop-loss orders, exposure limits, "
                        "and maximum daily-loss limits. Leverage "
                        "increases both possible gains and losses."
                    ),
                },
            ],
        }


class EmptyKnowledgeProvider:
    def research(self, query: str) -> dict[str, object]:
        assert query
        return {
            "brief": "",
            "sources": [],
        }


def _step(question: str) -> PlanStep:
    return PlanStep(
        step_id=uuid4(),
        order=1,
        capability_id="knowledge.answer",
        risk_tier=RiskTier.LOW,
        expected_evidence=["answer_with_provenance"],
        parameters={"question": question},
        reversible=False,
    )


def test_open_question_uses_verified_intelligence_plane() -> None:
    result = execute_step(
        _step("Explain how the forex market works."),
        observed_at=datetime.now(UTC),
        knowledge_provider=FakeKnowledgeProvider(),
        session_id=uuid4(),
    )

    assert result.status is StepStatus.VERIFIED
    assert len(result.evidence) == 1

    attributes = result.evidence[0].attributes

    assert attributes["answer_path"] == "public_web"
    assert attributes["provider_id"] == "local_extractive_v1"
    assert attributes["intelligence_mode"] == "local_only"
    assert attributes["external_processing"] is False
    assert attributes["grounded"] is True
    assert attributes["verified"] is True
    assert attributes["claims"]
    assert attributes["sources"]
    assert "[web-" in str(attributes["brief"])


def test_no_evidence_fails_closed() -> None:
    result = execute_step(
        _step("Explain an unsupported topic."),
        observed_at=datetime.now(UTC),
        knowledge_provider=EmptyKnowledgeProvider(),
        session_id=uuid4(),
    )

    assert result.status is StepStatus.FAILED
    assert result.error_code == "INTELLIGENCE_NO_EVIDENCE"
    assert result.evidence == []
