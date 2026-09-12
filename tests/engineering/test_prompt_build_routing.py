from __future__ import annotations

from uuid import uuid4

from nexuss.conversation.stabilization import deterministic_route
from nexuss.core.intents import classify_intent
from nexuss.core.planner import build_plan
from nexuss.core.policy import evaluate_step
from nexuss.core.registry import get_capability
from nexuss.domain.models import IntentKind, PolicyOutcome


def test_prompt_build_chat_route_is_narrow_and_exact() -> None:
    result = deterministic_route(
        "Nexuss, build yourself: add a small diagnostics badge to the workspace UI"
    )
    assert result is not None
    assert result.route.value == "action"
    assert result.capability_hint == "engineering.build_artifact"
    assert result.action_instruction is not None
    assert result.action_instruction.startswith("Build Nexuss change: ")
    assert "diagnostics badge" in result.action_instruction


def test_prompt_build_does_not_hijack_ordinary_language() -> None:
    assert deterministic_route("build confidence by practicing daily") is None
    assert deterministic_route("write me a paragraph about Rust") is None


def test_prompt_build_intent_and_plan() -> None:
    intent = classify_intent(
        "Build Nexuss change: add a small diagnostics badge to the workspace UI"
    )
    assert intent.kind is IntentKind.ENGINEERING_BUILD_ARTIFACT
    assert "diagnostics badge" in intent.entities["goal"]

    plan = build_plan(uuid4(), intent)
    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert step.capability_id == "engineering.build_artifact"
    assert step.parameters["goal"] == intent.entities["goal"]


def test_prompt_build_registry_and_policy_require_one_exact_approval(monkeypatch) -> None:
    manifest = get_capability("engineering.build_artifact")
    assert manifest is not None
    assert manifest.status.value == "active"
    assert manifest.execution_mode == "isolated_engineering_self_build"
    assert manifest.risk_tier.value == "high"
    assert manifest.approval_policy.value == "explicit"

    intent = classify_intent("Build Nexuss change: add a diagnostics badge")
    step = build_plan(uuid4(), intent).steps[0]

    monkeypatch.delenv("NEXUSS_DEVELOPER_SELF_BUILD", raising=False)
    decision = evaluate_step(step)
    assert decision.outcome is PolicyOutcome.REQUIRE_APPROVAL
    assert decision.reason_code == "DEVELOPER_ENGINEERING_MISSION_APPROVAL_REQUIRED"

    # Legacy launcher state must not silently turn a High-risk engineering
    # mission into an auto-authorized action.
    monkeypatch.setenv("NEXUSS_DEVELOPER_SELF_BUILD", "1")
    decision = evaluate_step(step)
    assert decision.outcome is PolicyOutcome.REQUIRE_APPROVAL
    assert decision.reason_code == "DEVELOPER_ENGINEERING_MISSION_APPROVAL_REQUIRED"
