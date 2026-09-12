"""Canonical receipts for universal zero-execution action plans."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from nexuss.orchestration.models import (
    ActionPlanEnvelope,
    ActionPlanReceipt,
    OrchestrationLifecycleEvent,
)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_action_plan_receipt(
    *,
    request_id: UUID,
    instruction: str,
    capability_catalog: str,
    envelope: ActionPlanEnvelope,
) -> ActionPlanReceipt:
    created_at = datetime.now(UTC)
    request_hash = _sha256(instruction)
    catalog_hash = _sha256(capability_catalog)
    plan_hash = _sha256(envelope.model_dump_json())
    receipt_id = uuid5(
        NAMESPACE_URL,
        f"nexuss:universal-action-plan:{request_id}:{plan_hash}",
    )

    events = (
        OrchestrationLifecycleEvent(
            sequence=1,
            state="received",
            event_type="orchestration_request_received",
            occurred_at=created_at,
            detail="Authenticated universal orchestration request accepted.",
        ),
        OrchestrationLifecycleEvent(
            sequence=2,
            state="selecting_provider",
            event_type="ai_provider_selected",
            occurred_at=created_at,
            detail=(
                f"Nexuss selected {envelope.provider.display_name} through "
                "the provider-neutral registry."
            ),
        ),
        OrchestrationLifecycleEvent(
            sequence=3,
            state="preparing_context",
            event_type="capability_catalog_prepared",
            occurred_at=created_at,
            detail=(
                "A sanitized capability catalogue was prepared from the "
                "authoritative Nexuss registry."
            ),
        ),
        OrchestrationLifecycleEvent(
            sequence=4,
            state="reasoning",
            event_type="provider_action_plan_received",
            occurred_at=created_at,
            detail=(
                "The provider returned requested actions without direct "
                "tool or execution authority."
            ),
        ),
        OrchestrationLifecycleEvent(
            sequence=5,
            state="mapping_capabilities",
            event_type="capability_mapping_completed",
            occurred_at=created_at,
            detail=(
                f"Nexuss mapped {envelope.action_count} actions; "
                f"{envelope.unknown_count} unknown and "
                f"{envelope.prohibited_count} prohibited."
            ),
        ),
        OrchestrationLifecycleEvent(
            sequence=6,
            state="planned",
            event_type="universal_action_plan_verified",
            occurred_at=created_at,
            detail=(
                "Schema, dependency, sensitive-key, and registry validation "
                "passed. No capability was executed."
            ),
        ),
    )

    return ActionPlanReceipt(
        receipt_id=receipt_id,
        receipt_type="universal_action_plan",
        request_id=request_id,
        provider_id=envelope.plan.provider_id,
        model=envelope.plan.model,
        mode=envelope.plan.mode.value,
        request_sha256=request_hash,
        capability_catalog_sha256=catalog_hash,
        plan_sha256=plan_hash,
        events=events,
        created_at=created_at,
    )
