"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Deterministic task planning for the Nexuss P5 knowledge, media, and mobile plane.
"""

from __future__ import annotations

import re
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
    if intent.kind is IntentKind.ASSISTANT_IDENTITY:
        return [
            (
                "assistant.respond",
                RiskTier.INFORMATIONAL,
                ["assistant_response"],
                {"response_key": "who_are_you"},
                False,
            )
        ]

    if intent.kind in {
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

    if intent.kind is IntentKind.CONSTITUTION_OVERRIDE:
        return [
            (
                "assistant.respond",
                RiskTier.INFORMATIONAL,
                ["assistant_response"],
                {"response_key": "ignore_constitution"},
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
                ["sources", "brief"],
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

    if intent.kind is IntentKind.IDENTITY_RECALL:
        response_key = intent.entities.get("response_key", "")
        if response_key:
            return [
                (
                    "assistant.respond",
                    RiskTier.INFORMATIONAL,
                    ["assistant_response"],
                    {"response_key": response_key},
                    False,
                )
            ]

        return [
            (
                "memory.recall",
                RiskTier.INFORMATIONAL,
                ["memory_recall_results"],
                {"query": intent.entities.get("query", "")},
                False,
            )
        ]

    if intent.kind is IntentKind.USER_IDENTITY_CLAIM:
        claim = intent.entities.get("claim", "")
        normalized_claim = " ".join(claim.casefold().split())

        if normalized_claim == "peter":
            response_parameters: dict[str, object] = {
                "response_key": "user_claims_to_be_peter",
            }
        else:
            response_parameters = {
                "response": (
                    f"You are claiming to be {claim}. I can retain that as an "
                    "unverified identity claim, but authority still requires "
                    "authentication."
                )
            }

        return [
            (
                "memory.remember",
                RiskTier.LOW,
                ["memory_claim_recorded"],
                {
                    "statement": f"The operator states that they are {claim}.",
                    "topic": derive_topic(claim),
                    "unverified_identity_claim": True,
                },
                True,
            ),
            (
                "assistant.respond",
                RiskTier.INFORMATIONAL,
                ["assistant_response"],
                response_parameters,
                False,
            ),
        ]

    if intent.kind is IntentKind.SMALL_TALK:
        return [
            (
                "assistant.converse",
                RiskTier.INFORMATIONAL,
                ["conversational_reply"],
                {"small_talk_kind": intent.entities.get("small_talk_kind", "greeting")},
                False,
            )
        ]

    if intent.kind is IntentKind.DATETIME_QUERY:
        return [
            (
                "assistant.converse",
                RiskTier.INFORMATIONAL,
                ["conversational_reply"],
                {"datetime_field": intent.entities.get("datetime_field", "time")},
                False,
            )
        ]

    if intent.kind is IntentKind.OPEN_QUESTION:
        return [
            (
                "knowledge.answer",
                RiskTier.LOW,
                ["answer_with_provenance"],
                {"question": intent.entities.get("question", "")},
                False,
            )
        ]

    if intent.kind is IntentKind.MEMORY_REMEMBER:
        statement = intent.entities.get("statement", "")
        topic = derive_topic(statement)
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


# Topic labels group and display claims; the full statement is always stored
# separately. Taking the first N words produced labels like "maker fees are
# lower than taker fees on", which is a truncated sentence, not a topic.
_TOPIC_STOPWORDS = frozenset({
    "a", "about", "all", "also", "am", "an", "and", "any", "are", "as", "at",
    "be", "been", "being", "but", "by", "can", "did", "do", "does", "for",
    "from", "had", "has", "have", "he", "her", "his", "how", "i", "if", "in",
    "into", "is", "it", "its", "just", "me", "more", "most", "my", "no", "not",
    "of", "on", "one", "only", "or", "our", "out", "over", "own", "she", "so",
    "some", "than", "that", "the", "their", "them", "then", "there", "these",
    "they", "this", "those", "to", "up", "us", "very", "was", "we", "were",
    "what", "when", "where", "which", "while", "who", "why", "will", "with",
    "would", "you", "your",
})

_TOPIC_WORD_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\-]*")
_TOPIC_MAX_WORDS = 4


def derive_topic(statement: str) -> str:
    """Derive a short topic label from a statement.

    Keeps the content words in order and drops filler, so
    "maker fees are lower than taker fees on most venues" becomes
    "maker fees lower taker" rather than a clipped sentence.

    This is deliberately a heuristic. ADR-0009 places real topic extraction in
    the claim extractor, where a language model can do it properly; until then
    an honest approximation beats a truncation that reads like a bug.
    """
    words = _TOPIC_WORD_PATTERN.findall(statement.lower())
    content = [word for word in words if word not in _TOPIC_STOPWORDS]
    selected = content[:_TOPIC_MAX_WORDS] or words[:_TOPIC_MAX_WORDS]
    return " ".join(selected) or "general"


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
