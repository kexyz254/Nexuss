"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Deterministic task planning for the Nexuss P5 knowledge, media, and mobile plane.
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

from nexuss.core.managed_notes import prepare_note
from nexuss.core.web_actions import google_search_url, youtube_search_url
from nexuss.domain.models import Intent, IntentKind, PlanStep, RiskTier, TaskPlan

StepSpec = tuple[
    str,
    RiskTier,
    list[str],
    dict[str, object],
    bool,
]


def _step_id(task_id: UUID, order: int, capability_id: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"nexuss:{task_id}:{order}:{capability_id}")


def _assistant_response(intent: Intent) -> str:
    responses = {
        IntentKind.ASSISTANT_IDENTITY: (
            "I am Nexuss, your personal cognitive control plane. I interpret "
            "requests, apply safety policy, coordinate approved capabilities, "
            "verify results, and preserve auditable Action Receipts."
        ),
        IntentKind.ASSISTANT_CAPABILITIES: (
            "I can inspect this workspace, research bounded public sources, "
            "discover and rank YouTube media, create verified notes, and use "
            "governed device actions with approval only where policy requires it."
        ),
        IntentKind.ASSISTANT_HELP: (
            "Try: ‘Research the fundamentals of forex’, ‘Play Silence by "
            "Popcaan’, ‘Open YouTube on my phone and search Silence by Popcaan’, "
            "or ‘Open Chrome and search forex risk management’."
        ),
    }
    return responses[intent.kind]


def _direct_specs(intent: Intent) -> list[StepSpec] | None:
    if intent.kind in {
        IntentKind.ASSISTANT_IDENTITY,
        IntentKind.ASSISTANT_CAPABILITIES,
        IntentKind.ASSISTANT_HELP,
    }:
        return [
            (
                "assistant.respond",
                RiskTier.INFORMATIONAL,
                ["assistant_response"],
                {"response": _assistant_response(intent)},
                False,
            )
        ]

    if intent.kind is IntentKind.CREATE_NOTE:
        prepared = prepare_note(
            intent.entities["title"],
            intent.entities["content"],
        )
        return [
            (
                "workspace.create_note",
                RiskTier.MEDIUM,
                ["created_note_metadata", "sha256_verification"],
                {
                    "title": prepared.title,
                    "filename": prepared.filename,
                    "content": prepared.content,
                    "content_sha256": prepared.content_sha256,
                    "byte_count": len(prepared.content_bytes),
                },
                True,
            )
        ]

    query = intent.entities.get("query", intent.normalized_text)

    if intent.kind is IntentKind.WEB_RESEARCH:
        return [
            (
                "knowledge.web_research",
                RiskTier.LOW,
                ["public_sources", "cited_brief"],
                {"query": query},
                False,
            )
        ]

    if intent.kind is IntentKind.YOUTUBE_SEARCH:
        return [
            (
                "media.youtube.discover",
                RiskTier.LOW,
                ["youtube_discovery_state"],
                {"query": query},
                False,
            )
        ]

    if intent.kind is IntentKind.MEMORY_REMEMBER:
        statement = intent.entities.get("statement", "")
        topic = " ".join(statement.split()[:8]) or "general"
        return [
            (
                "memory.remember",
                RiskTier.LOW,
                ["memory_claim_recorded"],
                {"statement": statement, "topic": topic},
                True,
            )
        ]

    if intent.kind is IntentKind.MEMORY_RECALL:
        return [
            (
                "memory.recall",
                RiskTier.INFORMATIONAL,
                ["memory_recall_results"],
                {"query": intent.entities.get("query", "")},
                False,
            )
        ]

    if intent.kind is IntentKind.MEMORY_FORGET:
        return [
            (
                "memory.forget",
                RiskTier.HIGH,
                ["memory_topic_forgotten"],
                {"topic": intent.entities.get("topic", "")},
                False,
            )
        ]

    if intent.kind is IntentKind.PAIR_PHONE:
        return [
            (
                "device.pair_phone",
                RiskTier.LOW,
                ["mobile_pairing_challenge"],
                {},
                True,
            )
        ]

    if intent.kind is IntentKind.LIST_PAIRED_DEVICES:
        return [
            (
                "device.list_phones",
                RiskTier.LOW,
                ["paired_device_inventory"],
                {},
                False,
            )
        ]

    if intent.kind is IntentKind.UNPAIR_PHONE:
        return [
            (
                "device.unpair_phone",
                RiskTier.HIGH,
                ["paired_device_revocation"],
                {"device_label": intent.entities.get("device_label", "")},
                False,
            )
        ]

    if intent.kind is IntentKind.PHONE_OPEN_YOUTUBE:
        return [
            (
                "phone.open_youtube",
                RiskTier.LOW,
                ["paired_phone_youtube_handoff"],
                {
                    "query": query,
                    "launch_url": youtube_search_url(query),
                },
                False,
            )
        ]

    if intent.kind is IntentKind.OPEN_WEB_SEARCH:
        return [
            (
                "device.open_web_search",
                RiskTier.HIGH,
                ["trusted_node_identity", "browser_launch_handoff"],
                {
                    "query": query,
                    "launch_url": google_search_url(query),
                    "target_node_id": "windows-primary",
                },
                False,
            )
        ]

    if intent.kind is IntentKind.LAUNCH_NOTEPAD:
        return [
            (
                "device.launch_notepad",
                RiskTier.HIGH,
                ["trusted_node_identity", "process_start_verification"],
                {
                    "target_node_id": intent.entities.get(
                        "target_node_id",
                        "windows-primary",
                    ),
                    "application": "notepad",
                },
                True,
            )
        ]

    return None


def _fallback_specs(intent: Intent) -> list[StepSpec]:
    capability_specs: dict[IntentKind, list[StepSpec]] = {
        IntentKind.DAILY_BRIEFING: [
            (
                "calendar.read_summary",
                RiskTier.LOW,
                ["calendar_snapshot"],
                {},
                False,
            ),
            (
                "email.read_summary",
                RiskTier.LOW,
                ["email_snapshot"],
                {},
                False,
            ),
            (
                "github.read_summary",
                RiskTier.LOW,
                ["repository_snapshot"],
                {},
                False,
            ),
            (
                "ats.read_health",
                RiskTier.LOW,
                ["ats_health_snapshot"],
                {},
                False,
            ),
        ],
        IntentKind.SYSTEM_HEALTH: [
            (
                "nexuss.read_health",
                RiskTier.LOW,
                ["health_snapshot"],
                {},
                False,
            )
        ],
        IntentKind.LOCAL_WORKSPACE_STATUS: [
            (
                "workspace.read_status",
                RiskTier.LOW,
                ["workspace_status_snapshot"],
                {},
                False,
            )
        ],
        IntentKind.PREPARE_WORKSPACE: [
            (
                "device.workspace.prepare",
                RiskTier.MEDIUM,
                ["workspace_state"],
                {},
                True,
            )
        ],
        IntentKind.PLAY_MEDIA: [
            (
                "media.prepare_playback",
                RiskTier.LOW,
                ["playback_state"],
                {},
                False,
            )
        ],
        IntentKind.ATS_READ: [
            (
                "ats.read_intelligence",
                RiskTier.LOW,
                ["ats_intelligence_snapshot"],
                {},
                False,
            )
        ],
        IntentKind.ATS_WRITE: [
            (
                "ats.write_order",
                RiskTier.CRITICAL,
                ["trade_confirmation"],
                {},
                False,
            )
        ],
        IntentKind.FINANCIAL_TRANSFER: [
            (
                "finance.transfer",
                RiskTier.CRITICAL,
                ["transaction_receipt"],
                {},
                False,
            )
        ],
        IntentKind.SOCIAL_PUBLISH: [
            (
                "social.publish",
                RiskTier.HIGH,
                ["published_post"],
                {},
                False,
            )
        ],
        IntentKind.UNKNOWN: [
            (
                "nexuss.unsupported",
                RiskTier.HIGH,
                ["unsupported_reason"],
                {},
                False,
            )
        ],
    }
    return capability_specs.get(intent.kind, [])


def build_plan(task_id: UUID, intent: Intent) -> TaskPlan:
    specs = _direct_specs(intent)
    if specs is None:
        specs = _fallback_specs(intent)

    steps = [
        PlanStep(
            step_id=_step_id(task_id, order, capability_id),
            order=order,
            capability_id=capability_id,
            risk_tier=risk,
            expected_evidence=evidence,
            parameters=parameters,
            reversible=reversible,
        )
        for order, (
            capability_id,
            risk,
            evidence,
            parameters,
            reversible,
        ) in enumerate(specs, start=1)
    ]
    plan_id = uuid5(NAMESPACE_URL, f"nexuss:{task_id}:plan:{intent.kind}")
    return TaskPlan(
        plan_id=plan_id,
        task_id=task_id,
        intent=intent,
        steps=steps,
    )
