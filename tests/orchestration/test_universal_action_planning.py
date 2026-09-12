from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from nexuss.ai.registry import default_provider_registry
from nexuss.capabilities.broker import (
    CapabilityBroker,
    CapabilityBrokerError,
)
from nexuss.capabilities.models import CapabilityMappingState
from nexuss.cognitive.models import CognitiveMode
from nexuss.engineering.models import ModelProposal
from nexuss.orchestration.models import UniversalActionPlanResponse
from nexuss.orchestration.receipt import build_action_plan_receipt
from nexuss.orchestration.service import UniversalActionPlanningService
from nexuss.orchestration.store import SQLiteOrchestrationStore


def _proposal(actions: list[dict[str, object]]) -> ModelProposal:
    return ModelProposal(
        summary="Validated provider-neutral plan.",
        tool_requests=(),
        done=True,
        completion_message=json.dumps(
            {
                "response": "I prepared the requested Nexuss workflow.",
                "requested_actions": actions,
            }
        ),
    )


def _service(
    actions: list[dict[str, object]],
) -> UniversalActionPlanningService:
    provider = default_provider_registry().select(
        provider_id="auto",
        mode=CognitiveMode.PLAN,
    )
    return UniversalActionPlanningService(
        provider=provider,
        model="deepseek-v4-pro",
        proposer=lambda _request: _proposal(actions),
        broker=CapabilityBroker(maximum_actions=8),
    )


def test_auto_provider_selection_is_provider_neutral() -> None:
    provider = default_provider_registry().select(
        provider_id="auto",
        mode=CognitiveMode.PLAN,
    )
    assert provider.provider_id == "deepseek"
    assert provider.supports_action_planning is True


def test_known_capability_maps_without_execution() -> None:
    service = _service(
        [
            {
                "action_key": "inspect_workspace",
                "capability_id": "workspace.read_status",
                "arguments": {},
                "rationale": "Inspect bounded workspace metadata.",
                "expected_evidence": ["workspace_status_snapshot"],
                "depends_on": [],
            }
        ]
    )
    envelope, _catalog = service.plan(
        instruction="Inspect this workspace.",
        mode=CognitiveMode.PLAN,
    )
    assert envelope.action_count == 1
    assert envelope.verified_existing_count == 1
    assert envelope.all_actions_mapped is True
    assert envelope.execution_authorized is False
    assert envelope.capabilities_executed == 0
    assert (
        envelope.mapped_actions[0].mapping_state
        is CapabilityMappingState.VERIFIED_EXISTING
    )


def test_unknown_capability_is_fail_closed() -> None:
    service = _service(
        [
            {
                "action_key": "invented",
                "capability_id": "invented.tool.execute",
                "arguments": {},
                "rationale": "Attempt an invented capability.",
                "expected_evidence": [],
                "depends_on": [],
            }
        ]
    )
    envelope, _catalog = service.plan(
        instruction="Use an invented capability.",
        mode=CognitiveMode.PLAN,
    )
    assert envelope.unknown_count == 1
    assert envelope.all_actions_mapped is False
    assert envelope.execution_authorized is False
    assert (
        envelope.mapped_actions[0].mapping_state
        is CapabilityMappingState.UNKNOWN
    )


def test_sensitive_arguments_are_rejected() -> None:
    service = _service(
        [
            {
                "action_key": "unsafe",
                "capability_id": "workspace.read_status",
                "arguments": {"api_key": "must-not-pass"},
                "rationale": "Unsafe argument test.",
                "expected_evidence": [],
                "depends_on": [],
            }
        ]
    )
    with pytest.raises(
        CapabilityBrokerError,
        match="Sensitive argument key",
    ):
        service.plan(
            instruction="Attempt to pass a secret.",
            mode=CognitiveMode.PLAN,
        )


def test_sqlite_store_round_trip(tmp_path: Path) -> None:
    request_id = uuid4()
    service = _service(
        [
            {
                "action_key": "inspect_workspace",
                "capability_id": "workspace.read_status",
                "arguments": {},
                "rationale": "Inspect bounded workspace metadata.",
                "expected_evidence": ["workspace_status_snapshot"],
                "depends_on": [],
            }
        ]
    )
    envelope, catalog = service.plan(
        instruction="Inspect this workspace.",
        mode=CognitiveMode.PLAN,
    )
    receipt = build_action_plan_receipt(
        request_id=request_id,
        instruction="Inspect this workspace.",
        capability_catalog=catalog,
        envelope=envelope,
    )
    response = UniversalActionPlanResponse(
        envelope=envelope,
        receipt=receipt,
    )
    store = SQLiteOrchestrationStore(
        tmp_path / "orchestration.sqlite3"
    )
    store.save(response)

    assert store.get_by_request(request_id) == response
    assert store.get_by_receipt(receipt.receipt_id) == response
