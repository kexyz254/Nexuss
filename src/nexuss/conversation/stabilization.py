"""Deterministic constitutional and truth guards for unified routing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from nexuss.constitution.loader import (
    ConstitutionError,
    get_constitution,
)
from nexuss.conversation.models import RouteClassification


@dataclass(frozen=True)
class DeterministicRouteResult:
    classification: RouteClassification
    provider_id: str
    model: str
    source: str


def _classification(
    *,
    route: str,
    response: str,
    action_instruction: str | None = None,
    clarification_question: str | None = None,
    capability_hint: str | None = None,
    confidence: float = 1.0,
) -> RouteClassification:
    return RouteClassification.model_validate(
        {
            "route": route,
            "response": response,
            "action_instruction": action_instruction,
            "clarification_question": clarification_question,
            "capability_hint": capability_hint,
            "confidence": confidence,
        }
    )


def _normalize(value: str) -> str:
    return " ".join(value.strip().casefold().split())


_WHO_ARE_YOU = re.compile(
    r"^(?:nexuss[,;:\-]?\s+)?(?:who|what)\s+are\s+you[?!.]*$",
    re.IGNORECASE,
)
_FOUNDER = re.compile(
    r"\b(?:who\s+(?:founded|created|developed|built|made)\s+"
    r"(?:you|nexuss)|who\s+is\s+(?:your|nexuss(?:'s)?)\s+"
    r"(?:founder|creator|developer)|nexuss\s+team.*(?:name|individual)|"
    r"(?:name|identify)\s+(?:one\s+)?(?:person|individual).*nexuss)\b",
    re.IGNORECASE,
)
_OWNER = re.compile(
    r"\b(?:who\s+owns\s+nexuss|who\s+is\s+(?:your|nexuss(?:'s)?)\s+owner)\b",
    re.IGNORECASE,
)
_BOSS = re.compile(
    r"\bwho\s+is\s+your\s+boss\b",
    re.IGNORECASE,
)
_CONSTITUTION = re.compile(
    r"\b(?:nexuss(?:'s)?\s+)?constitution\b",
    re.IGNORECASE,
)
_OVERRIDE = re.compile(
    r"\b(?:ignore|override|bypass|forget)\s+(?:the\s+)?"
    r"(?:nexuss\s+)?constitution\b",
    re.IGNORECASE,
)
_IDENTITY_CLAIM = re.compile(
    r"\b(?:i\s+am|i'm|since\s+i\s+am|as)\s+(?:the\s+)?"
    r"(?:owner|founder|creator|administrator)\s+of\s+nexuss\b|"
    r"\bi\s+am\s+peter\b",
    re.IGNORECASE,
)
_CHROME_SEARCH = re.compile(
    r"^(?:please\s+)?(?:open|launch|start)\s+"
    r"(?:google\s+)?(?:chrome|the\s+browser|browser)\s*"
    r"(?:,?\s*(?:and|then|to)\s+)?(?:search|google)"
    r"(?:\s+(?:for|about))?\s+(?P<query>.+?)[.!?]*$",
    re.IGNORECASE,
)
# P6.14.1 DETERMINISTIC ENGINEERING ACCEPTANCE ROUTING
_ENGINEERING_ACCEPTANCE = re.compile(
    r"^(?:nexuss[,;:\-]?\s+)?(?:verify|validate|audit|check)\s+"
    r"(?P<target>(?:the\s+)?(?:installed\s+)?"
    r"(?:p\d+(?:\.\d+)*|engineering|prompt-to-build|developer\s+engineering)"
    r".*?)[?!.]*$",
    re.IGNORECASE | re.DOTALL,
)

# P6.14.3 DETERMINISTIC FAILED-BUILD REPAIR ROUTING
_ENGINEERING_REPAIR = re.compile(
    r"^(?:nexuss[,;:\-]?\s+)?repair\s+(?:the\s+)?"
    r"(?:most\s+recent|latest)\s+failed\s+"
    r"(?P<target>(?:p\d+(?:\.\d+)*\s+)?(?:engineering|prompt-to-build|"
    r"new\s+chat|recent\s+conversations|.+?))\s*$",
    re.IGNORECASE | re.DOTALL,
)

# P7 PROMPT-TO-BUILD ROUTING
_SELF_BUILD = re.compile(
    r"^(?:nexuss[,;:\-]?\s+)?(?:/build|build\s+(?:yourself|nexuss)|"
    r"modify\s+nexuss|improve\s+nexuss|update\s+nexuss)"
    r"\s*[:;,\-]?\s*(?P<goal>.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)

# P6.12 DETERMINISTIC RUNTIME ROUTING
_MANAGED_NOTE = re.compile(
    r"^(?:please\s+)?create\s+(?:a\s+)?(?:managed\s+)?note\s+"
    r"(?:named|called)\s+(?P<title>.+?)\s+with\s+(?:the\s+)?content\s*:\s*"
    r"(?P<content>.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_CLOCK_QUERY = re.compile(
    r"^(?:what(?:'s|s|\s+is)|when\s+is)\s+(?:the\s+)?"
    r"(?P<field>time|date|today|day)(?:\s+(?:now|today))?[?!.]*$|"
    r"^(?:what\s+time\s+is\s+it|what\s+day\s+is\s+it)[?!.]*$",
    re.IGNORECASE,
)
_LIVE_RESEARCH = re.compile(
    r"^(?:please\s+|can\s+you\s+)?(?:(?:use\s+deepseek\s+to)\s+)?"
    r"research(?:\s+(?:on|about))?\s+(?P<topic>.+?)"
    r"(?:\s+using\s+deepseek)?[?!.]*$",
    re.IGNORECASE,
)
_PHONE_YOUTUBE = re.compile(
    r"^(?:please\s+)?(?:open|launch|start)\s+youtube\s+on\s+"
    r"(?:my\s+)?(?:phone|mobile)(?:\s+(?:and|then)\s+search"
    r"(?:\s+for)?\s+(?P<query>.+?))?[.!?]*$",
    re.IGNORECASE,
)
_SPECULATION = re.compile(
    r"\b(?:likely|probably|possibly|might\s+be|may\s+be|"
    r"sounds\s+like|or\s+similar|i(?:'m|\s+am)\s+familiar\s+with)\b",
    re.IGNORECASE,
)
_IDENTIFICATION_CONTEXT = re.compile(
    r"\b(?:case|episode|documentary|film|movie|book|song|person|"
    r"event|title|who|which|what|do\s+you\s+know)\b",
    re.IGNORECASE,
)


def _constitution_suffix() -> tuple[str, str, str]:
    constitution = get_constitution()
    suffix = (
        f" Active Nexuss Constitution v{constitution.version}; "
        f"SHA-256 {constitution.sha256[:16]}…; informational only."
    )
    return constitution.version, constitution.sha256, suffix


def deterministic_route_result(
    user_text: str,
) -> DeterministicRouteResult | None:
    text = user_text.strip()
    normalized = _normalize(text)

    engineering_repair = _ENGINEERING_REPAIR.match(text)
    if engineering_repair:
        repair_target = " ".join(
            engineering_repair.group("target").strip().split()
        )
        return DeterministicRouteResult(
            classification=_classification(
                route="action",
                response=(
                    "I will resume the newest retained failed Prompt-to-Build candidate "
                    "and repair it from local diagnostic evidence before using any paid provider call."
                ),
                action_instruction=(
                    "Repair latest failed engineering build: " + repair_target
                ),
                capability_hint="engineering.repair_failed_build",
                confidence=1.0,
            ),
            provider_id="nexuss_deterministic_router",
            model="engineering-repair-v1",
            source="deterministic_engineering_repair",
        )

    self_build = _SELF_BUILD.match(text)
    if self_build:
        goal = " ".join(self_build.group("goal").strip().split())
        if goal:
            return DeterministicRouteResult(
                classification=_classification(
                    route="action",
                    response=(
                        "I will run that as a developer self-build. DeepSeek may inspect "
                        "and edit only an isolated Nexuss copy; Nexuss will validate the "
                        "result against the current regression baseline before any live "
                        "source is updated."
                    ),
                    action_instruction=f"Build Nexuss change: {goal}",
                    capability_hint="engineering.build_artifact",
                    confidence=1.0,
                ),
                provider_id="nexuss_deterministic_router",
                model="prompt-to-build-v1",
                source="deterministic_developer_self_build",
            )

    engineering_acceptance = _ENGINEERING_ACCEPTANCE.match(text)
    if engineering_acceptance:
        target = " ".join(
            engineering_acceptance.group("target").strip().split()
        )
        return DeterministicRouteResult(
            classification=_classification(
                route="action",
                response=(
                    "I will verify that engineering phase using deterministic "
                    "local acceptance evidence only. No paid model call is required."
                ),
                action_instruction=f"Verify engineering acceptance: {target}",
                capability_hint="engineering.verify_acceptance",
                confidence=1.0,
            ),
            provider_id="nexuss_deterministic_router",
            model="engineering-acceptance-v1",
            source="deterministic_engineering_acceptance",
        )

    note = _MANAGED_NOTE.match(text)
    if note:
        title = " ".join(note.group("title").strip(" \"'").split())
        content = note.group("content").strip()
        if title and content:
            return DeterministicRouteResult(
                classification=_classification(
                    route="action",
                    response=(
                        "I will route that through the governed managed-note "
                        "capability. No file may be written before exact approval."
                    ),
                    action_instruction=f"Create a note called {title} with the content: {content}",
                    capability_hint="workspace.create_note",
                    confidence=1.0,
                ),
                provider_id="nexuss_deterministic_router",
                model="managed-note-v1",
                source="deterministic_managed_note",
            )

    clock = _CLOCK_QUERY.match(text)
    if clock:
        local = datetime.now().astimezone()
        field = (clock.groupdict().get("field") or "").casefold()
        if field == "time" or "time" in normalized:
            response = f"The local time is {local.strftime('%H:%M:%S')} ({local.tzname() or 'local'})."
        else:
            response = f"Today is {local.strftime('%A, %d %B %Y')}."
        return DeterministicRouteResult(
            classification=_classification(route="chat", response=response, confidence=1.0),
            provider_id="nexuss_local_clock",
            model="system-clock-v1",
            source="deterministic_local_clock",
        )

    research = _LIVE_RESEARCH.match(text)
    if research:
        topic = " ".join(research.group("topic").strip(" \"'").split())
        if topic:
            return DeterministicRouteResult(
                classification=_classification(
                    route="action",
                    response=(
                        "I will gather grounded public evidence first. Nexuss will not treat "
                        "DeepSeek or any reasoning provider as an evidence source."
                    ),
                    action_instruction=f"Research {topic}.",
                    capability_hint="knowledge.web_research",
                    confidence=1.0,
                ),
                provider_id="nexuss_deterministic_router",
                model="grounded-research-v1",
                source="deterministic_grounded_research",
            )

    chrome = _CHROME_SEARCH.match(text)
    if chrome:
        query = chrome.group("query").strip(" \"'")
        if query:
            return DeterministicRouteResult(
                classification=_classification(
                    route="action",
                    response=(
                        "I will route that through the protected web-search "
                        "capability."
                    ),
                    action_instruction=(
                        f"Open Chrome and search {query}."
                    ),
                    capability_hint="device.open_web_search",
                    confidence=1.0,
                ),
                provider_id="nexuss_deterministic_router",
                model="compound-actions-v1",
                source="deterministic_compound_action",
            )

    phone_youtube = _PHONE_YOUTUBE.match(text)
    if phone_youtube:
        query = (phone_youtube.group("query") or "YouTube").strip(
            " \"'"
        )
        return DeterministicRouteResult(
            classification=_classification(
                route="action",
                response=(
                    "I will route that through the protected mobile "
                    "YouTube handoff."
                ),
                action_instruction=(
                    f"Open YouTube on my phone and search {query}."
                ),
                capability_hint="mobile.youtube.handoff",
                confidence=1.0,
            ),
            provider_id="nexuss_deterministic_router",
            model="compound-actions-v1",
            source="deterministic_compound_action",
        )

    identity_related = any(
        pattern.search(normalized)
        for pattern in (
            _WHO_ARE_YOU,
            _FOUNDER,
            _OWNER,
            _BOSS,
            _CONSTITUTION,
            _OVERRIDE,
            _IDENTITY_CLAIM,
        )
    )
    if not identity_related:
        return None

    try:
        constitution = get_constitution()
        version, _digest, suffix = _constitution_suffix()

        if _OVERRIDE.search(normalized):
            response = constitution.standard_response(
                "ignore_constitution"
            )
        elif _IDENTITY_CLAIM.search(normalized):
            response = (
                "You are asserting an owner, founder, creator, or "
                "administrator identity. I can treat that only as an "
                "unverified identity claim; it does not grant authority, "
                "change policy, bypass approval, or amend the Constitution."
            )
        elif _WHO_ARE_YOU.search(normalized):
            response = constitution.standard_response("who_are_you")
        elif _FOUNDER.search(normalized):
            response = constitution.standard_response(
                "who_is_your_founder"
            )
        elif _OWNER.search(normalized):
            response = (
                "The active Constitution identifies Peter as the founder "
                "and original developer of Nexuss. Its identity section "
                "does not separately state a legal owner."
            )
        elif _BOSS.search(normalized):
            response = constitution.standard_response("who_is_your_boss")
        else:
            response = (
                f"{constitution.canonical_self_description} "
                "The Constitution separates authentication, authorization, "
                "approval, execution, verification, and receipts."
            )

        return DeterministicRouteResult(
            classification=_classification(
                route="chat",
                response=response + suffix,
                confidence=1.0,
            ),
            provider_id="nexuss_constitution",
            model=f"constitution-v{version}",
            source="constitutional_identity",
        )
    except ConstitutionError:
        return DeterministicRouteResult(
            classification=_classification(
                route="chat",
                response=(
                    "The active Nexuss Constitution could not be verified, "
                    "so I will not invent identity or authority details."
                ),
                confidence=1.0,
            ),
            provider_id="nexuss_constitution",
            model="constitution-unavailable",
            source="constitutional_identity_fail_closed",
        )


def deterministic_route(
    user_text: str,
) -> RouteClassification | None:
    result = deterministic_route_result(user_text)
    return result.classification if result is not None else None


def apply_truth_guard(
    user_text: str,
    classification: RouteClassification,
) -> RouteClassification:
    if classification.route.value != "chat":
        return classification

    if not (
        _IDENTIFICATION_CONTEXT.search(user_text)
        and _SPECULATION.search(classification.response)
    ):
        return classification

    data = classification.model_dump()
    data["response"] = (
        "I am not certain enough to identify that from the current "
        "context, so I will not guess. I can search live sources if you "
        "ask me to research it, or you can provide the exact title, "
        "season, person, or another identifying detail."
    )
    data["confidence"] = min(float(data["confidence"]), 0.45)
    return RouteClassification.model_validate(data)


def constitutional_prompt_context() -> str:
    try:
        constitution = get_constitution()
        truth_rules = constitution.section("truth_model")["rules"]
        compact_truth = " ".join(str(rule) for rule in truth_rules)
        return (
            "AUTHORITATIVE NEXUSS IDENTITY: "
            f"{constitution.canonical_self_description} "
            f"Constitution v{constitution.version}; "
            f"SHA-256 {constitution.sha256}. "
            "CONSTITUTIONAL TRUTH RULES: "
            f"{compact_truth}"
        )
    except ConstitutionError:
        return (
            "The Nexuss Constitution is unavailable or failed integrity "
            "verification. Do not invent identity, founder, owner, or "
            "authority details."
        )
