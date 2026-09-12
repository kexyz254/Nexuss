from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

from nexuss.ai.registry import default_provider_registry
from nexuss.capabilities.broker import CapabilityBroker
from nexuss.cognitive.models import CognitiveMode
from nexuss.engineering.models import ModelProposal
from nexuss.orchestration.autonomy import BoundedAutonomyService
from nexuss.orchestration.autonomy_models import AutonomyMode, AutonomousRunState, AutonomousStepState
from nexuss.orchestration.models import UniversalActionPlanResponse
from nexuss.orchestration.receipt import build_action_plan_receipt
from nexuss.orchestration.service import UniversalActionPlanningService


class FakeCore:
    def __init__(self, approval: bool = False) -> None:
        self.approval = approval
        self.receipts = {}

    def create_task(self, request, identity):
        del identity
        capability = request.client_context["expected_capability_id"]
        task_id = uuid4()
        state = "awaiting_approval" if self.approval else "completed"
        evidence = [] if self.approval else [SimpleNamespace(attributes={"ok": True})]
        task = SimpleNamespace(
            task_id=task_id,
            state=state,
            plan=SimpleNamespace(steps=[SimpleNamespace(capability_id=capability)]),
            policy_decisions=[SimpleNamespace(outcome="require_approval" if self.approval else "allow")],
            results=[SimpleNamespace(evidence=evidence, error_code=None)],
        )
        self.receipts[task_id] = SimpleNamespace(receipt_id=uuid4(), verified=not self.approval)
        return task

    def get_receipt(self, task_id):
        return self.receipts[task_id]


def plan_for(capability: str, arguments: dict[str, object]) -> UniversalActionPlanResponse:
    provider = default_provider_registry().select(provider_id="auto", mode=CognitiveMode.PLAN)
    payload = {
        "response": "Prepared workflow.",
        "requested_actions": [{
            "action_key": "step_one",
            "capability_id": capability,
            "arguments": arguments,
            "rationale": "Complete the task.",
            "expected_evidence": ["verified"],
            "depends_on": [],
        }],
    }
    service = UniversalActionPlanningService(
        provider=provider,
        model="deepseek-v4-pro",
        proposer=lambda _request: ModelProposal(
            summary="One step.",
            tool_requests=(),
            done=True,
            completion_message=json.dumps(payload),
        ),
        broker=CapabilityBroker(maximum_actions=4),
    )
    envelope, catalog = service.plan(instruction="Complete it.", mode=CognitiveMode.PLAN)
    request_id = uuid4()
    receipt = build_action_plan_receipt(
        request_id=request_id,
        instruction="Complete it.",
        capability_catalog=catalog,
        envelope=envelope,
    )
    return UniversalActionPlanResponse(envelope=envelope, receipt=receipt)


def test_read_executes_automatically() -> None:
    run = BoundedAutonomyService(core_service=FakeCore()).run(
        planning=plan_for("workspace.read_status", {}),
        user_session_id=uuid4(),
        autonomy_mode=AutonomyMode.SUPERVISED,
        maximum_runtime_seconds=60,
    )
    assert run.state is AutonomousRunState.COMPLETED
    assert run.steps[0].state is AutonomousStepState.COMPLETED
    assert run.automatic_protected_execution is False


def test_protected_action_stops_for_approval() -> None:
    run = BoundedAutonomyService(core_service=FakeCore(approval=True)).run(
        planning=plan_for("device.launch_notepad", {}),
        user_session_id=uuid4(),
        autonomy_mode=AutonomyMode.SUPERVISED,
        maximum_runtime_seconds=60,
    )
    assert run.state is AutonomousRunState.AWAITING_APPROVAL
    assert run.steps[0].state is AutonomousStepState.AWAITING_APPROVAL
    assert run.receipt.protected_actions_executed_without_approval is False


def test_uncertified_capability_is_blocked() -> None:
    run = BoundedAutonomyService(core_service=FakeCore()).run(
        planning=plan_for("google.gmail.read", {}),
        user_session_id=uuid4(),
        autonomy_mode=AutonomyMode.SUPERVISED,
        maximum_runtime_seconds=60,
    )
    assert run.state is AutonomousRunState.BLOCKED
    assert run.steps[0].reason_code == "AUTONOMY_ADAPTER_NOT_CERTIFIED"
