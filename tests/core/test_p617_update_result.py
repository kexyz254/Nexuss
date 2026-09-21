from __future__ import annotations

from nexuss.core.intents import classify_intent
from nexuss.core.planner import build_plan
from nexuss.core.registry import get_capability
from nexuss.domain.models import IntentKind
from uuid import uuid4


def test_update_result_is_first_class_read_capability() -> None:
    intent = classify_intent("Did the Nexuss update succeed?")
    assert intent.kind is IntentKind.SYSTEM_UPDATE_RESULT

    plan = build_plan(uuid4(), intent)
    assert len(plan.steps) == 1
    assert plan.steps[0].capability_id == "system.update.result"

    manifest = get_capability("system.update.result")
    assert manifest is not None
    assert manifest.execution_mode == "trusted_local_control_readonly"
