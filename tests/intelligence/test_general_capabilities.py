from __future__ import annotations

import pytest

from nexuss.core.intents import classify_intent
from nexuss.core.planner import build_plan
from nexuss.core.policy import evaluate_step
from nexuss.core.registry import get_capability
from nexuss.domain.models import IntentKind, PolicyOutcome
from uuid import uuid4


@pytest.mark.parametrize(
    ("utterance", "mode", "capability"),
    [
        ("Analyze this architecture.", "analyze", "intelligence.analyze"),
        ("Compare PostgreSQL and SQLite.", "compare", "intelligence.compare"),
        ("Plan how to migrate this service.", "plan", "intelligence.plan"),
        ("Summarize this incident report.", "summarize", "intelligence.summarize"),
        ("Review this API design.", "review", "intelligence.review"),
        ("Draft a project brief.", "write", "intelligence.write"),
        ("Rewrite this message professionally.", "rewrite", "intelligence.rewrite"),
        ("Design a resilient event bus.", "design", "intelligence.design"),
        ("Debug this Python failure.", "debug", "intelligence.debug"),
        ("Write code for a bounded retry helper.", "code", "intelligence.code"),
        (
            "Synthesize these findings into one conclusion.",
            "research_synthesis",
            "intelligence.research_synthesis",
        ),
        ("Brainstorm ways to improve onboarding.", "create", "intelligence.create"),
    ],
)
def test_general_intelligence_routes_to_registered_capability(
    utterance: str,
    mode: str,
    capability: str,
) -> None:
    intent = classify_intent(utterance)
    assert intent.kind is IntentKind.GENERAL_INTELLIGENCE
    assert intent.entities["mode"] == mode

    plan = build_plan(uuid4(), intent)
    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert step.capability_id == capability
    assert step.parameters["mode"] == mode

    manifest = get_capability(capability)
    assert manifest is not None
    assert manifest.execution_mode == "proposal_only_cognitive_provider"

    policy = evaluate_step(step)
    assert policy.outcome is PolicyOutcome.ALLOW


def test_general_intelligence_does_not_take_execution_authority() -> None:
    intent = classify_intent("Design a release automation architecture.")
    plan = build_plan(uuid4(), intent)
    step = plan.steps[0]
    assert step.reversible is False
    assert step.capability_id == "intelligence.design"
