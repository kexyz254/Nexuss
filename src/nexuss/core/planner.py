"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Deterministic task planning for the Nexuss P3 approved-action platform.
"""

from uuid import NAMESPACE_URL, UUID, uuid5

from nexuss.core.managed_notes import prepare_note
from nexuss.domain.models import Intent, IntentKind, PlanStep, RiskTier, TaskPlan


def _step_id(task_id: UUID, order: int, capability_id: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"nexuss:{task_id}:{order}:{capability_id}")


def _assistant_response(intent: Intent) -> str:
    responses = {
        IntentKind.ASSISTANT_IDENTITY: (
            "I am Nexuss, your personal cognitive control plane. I interpret requests, apply "
            "safety policy, coordinate approved capabilities, verify results, and preserve "
            "auditable Action Receipts."
        ),
        IntentKind.ASSISTANT_CAPABILITIES: (
            "I can inspect this Nexuss workspace, run clearly labelled simulations, explain my "
            "decisions, and create verified notes in the managed workspace after your explicit "
            "approval. Higher-risk connectors remain disabled until separately reviewed."
        ),
        IntentKind.ASSISTANT_HELP: (
            "Try: ‘Check my workspace and system status’, ‘Who are you?’, or ‘Create a note "
            "called Launch checklist with the tasks: verify P3, review the receipt, and test undo’."
        ),
    }
    return responses[intent.kind]


def build_plan(task_id: UUID, intent: Intent) -> TaskPlan:
    specs: list[tuple[str, RiskTier, list[str], dict[str, object], bool]]

    if intent.kind in {
        IntentKind.ASSISTANT_IDENTITY,
        IntentKind.ASSISTANT_CAPABILITIES,
        IntentKind.ASSISTANT_HELP,
    }:
        specs = [
            (
                "assistant.respond",
                RiskTier.INFORMATIONAL,
                ["assistant_response"],
                {"response": _assistant_response(intent)},
                False,
            )
        ]
    elif intent.kind is IntentKind.CREATE_NOTE:
        prepared = prepare_note(intent.entities["title"], intent.entities["content"])
        specs = [
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
    else:
        capability_specs: dict[
            IntentKind, list[tuple[str, RiskTier, list[str], dict[str, object], bool]]
        ] = {
            IntentKind.DAILY_BRIEFING: [
                ("calendar.read_summary", RiskTier.LOW, ["calendar_snapshot"], {}, False),
                ("email.read_summary", RiskTier.LOW, ["email_snapshot"], {}, False),
                ("github.read_summary", RiskTier.LOW, ["repository_snapshot"], {}, False),
                ("ats.read_health", RiskTier.LOW, ["ats_health_snapshot"], {}, False),
            ],
            IntentKind.SYSTEM_HEALTH: [
                ("nexuss.read_health", RiskTier.LOW, ["health_snapshot"], {}, False),
            ],
            IntentKind.LOCAL_WORKSPACE_STATUS: [
                (
                    "workspace.read_status",
                    RiskTier.LOW,
                    ["workspace_status_snapshot"],
                    {},
                    False,
                ),
            ],
            IntentKind.PREPARE_WORKSPACE: [
                ("device.workspace.prepare", RiskTier.MEDIUM, ["workspace_state"], {}, True),
            ],
            IntentKind.PLAY_MEDIA: [
                ("media.prepare_playback", RiskTier.LOW, ["playback_state"], {}, False),
            ],
            IntentKind.ATS_READ: [
                (
                    "ats.read_intelligence",
                    RiskTier.LOW,
                    ["ats_intelligence_snapshot"],
                    {},
                    False,
                ),
            ],
            IntentKind.ATS_WRITE: [
                ("ats.write_order", RiskTier.CRITICAL, ["trade_confirmation"], {}, False),
            ],
            IntentKind.FINANCIAL_TRANSFER: [
                ("finance.transfer", RiskTier.CRITICAL, ["transaction_receipt"], {}, False),
            ],
            IntentKind.SOCIAL_PUBLISH: [
                ("social.publish", RiskTier.HIGH, ["published_post"], {}, False),
            ],
            IntentKind.UNKNOWN: [
                ("nexuss.unsupported", RiskTier.HIGH, ["unsupported_reason"], {}, False),
            ],
            IntentKind.CREATE_NOTE: [],
            IntentKind.ASSISTANT_IDENTITY: [],
            IntentKind.ASSISTANT_CAPABILITIES: [],
            IntentKind.ASSISTANT_HELP: [],
        }
        specs = capability_specs[intent.kind]

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
        for order, (capability_id, risk, evidence, parameters, reversible) in enumerate(
            specs, start=1
        )
    ]
    plan_id = uuid5(NAMESPACE_URL, f"nexuss:{task_id}:plan:{intent.kind}")
    return TaskPlan(plan_id=plan_id, task_id=task_id, intent=intent, steps=steps)
