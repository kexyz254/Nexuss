"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Device pairing as a first-class capability.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from nexuss.core.executor import execute_step
from nexuss.core.intents import classify_intent
from nexuss.core.planner import build_plan
from nexuss.core.policy import evaluate_step
from nexuss.domain.models import (
    ApprovalChannel,
    IntentKind,
    PolicyOutcome,
    RiskTier,
    StepStatus,
)
from nexuss.mobile.gateway import MobileApprovalGateway


def _plan_step(utterance: str):
    intent = classify_intent(utterance)
    plan = build_plan(uuid4(), intent)
    return intent, plan.steps[0]


# ---------------------------------------------------------------- intents


def test_pair_phrasings_classify_as_pairing() -> None:
    for utterance in (
        "Pair my phone",
        "pair a new device",
        "add my phone",
        "connect my phone",
        "trust this phone",
    ):
        assert classify_intent(utterance).kind is IntentKind.PAIR_PHONE


def test_unpair_is_not_swallowed_by_the_pair_matcher() -> None:
    """'unpair my phone' contains 'pair my phone'. Ordering must handle it."""
    assert classify_intent("unpair my phone").kind is IntentKind.UNPAIR_PHONE
    assert classify_intent("forget this device").kind is IntentKind.UNPAIR_PHONE


def test_pairing_does_not_collide_with_the_youtube_handoff() -> None:
    handoff = classify_intent("Open YouTube on my phone and search Silence by Popcaan")
    assert handoff.kind is IntentKind.PHONE_OPEN_YOUTUBE


def test_listing_devices_classifies_separately() -> None:
    assert classify_intent("show my paired devices").kind is IntentKind.LIST_PAIRED_DEVICES


def test_named_device_is_carried_into_the_plan() -> None:
    _, step = _plan_step("unpair Work phone")
    assert step.parameters["device_label"] == "Work phone"


def test_a_label_beginning_with_phone_is_not_truncated() -> None:
    """Matching is case-insensitive, so an optional noun group in the label
    regex silently ate the first word: 'unpair Phone A' yielded 'A'."""
    for utterance, expected in (
        ("unpair Phone A", "Phone A"),
        ("unpair Device 2", "Device 2"),
        ("unpair my phone", ""),
        ("forget this device", ""),
    ):
        _, step = _plan_step(utterance)
        assert step.parameters["device_label"] == expected


def test_unambiguous_verbs_accept_any_label() -> None:
    """'unpair' means one thing, so it carries any name. 'remove' does not:
    'remove the Galaxy S24' must not be read as a revocation."""
    assert classify_intent("unpair Galaxy S24").kind is IntentKind.UNPAIR_PHONE
    assert classify_intent("untrust Jeuri Pixel").kind is IntentKind.UNPAIR_PHONE
    assert classify_intent("remove the Galaxy S24").kind is not IntentKind.UNPAIR_PHONE


# ----------------------------------------------------------------- policy


def test_pairing_needs_no_approval() -> None:
    _, step = _plan_step("pair my phone")
    decision = evaluate_step(step)
    assert step.capability_id == "device.pair_phone"
    assert decision.outcome is PolicyOutcome.ALLOW


def test_unpairing_requires_desktop_approval() -> None:
    """A handset you have lost must not be able to authorise its own removal."""
    from nexuss.core.registry import get_capability

    _, step = _plan_step("unpair my phone")
    decision = evaluate_step(step)
    manifest = get_capability("device.unpair_phone")

    assert step.risk_tier is RiskTier.HIGH
    assert decision.outcome is PolicyOutcome.REQUIRE_APPROVAL
    assert manifest is not None
    assert manifest.approval_channel is ApprovalChannel.DESKTOP


# --------------------------------------------------------------- execution


def test_pairing_returns_a_scannable_url_and_a_code() -> None:
    gateway = MobileApprovalGateway(mobile_url="http://192.168.1.10:8100/mobile")
    session_id = uuid4()
    _, step = _plan_step("pair my phone")

    result = execute_step(
        step,
        observed_at=datetime.now(UTC),
        session_id=session_id,
        pairing_gateway=gateway,
    )

    attributes = result.evidence[0].attributes
    assert result.status is StepStatus.VERIFIED
    assert str(attributes["pairing_code"]).isdigit()
    assert len(str(attributes["pairing_code"])) == 8
    assert attributes["pair_url"] == (
        f"http://192.168.1.10:8100/mobile?pair={attributes['pairing_code']}"
    )


def test_a_new_challenge_retires_the_previous_one() -> None:
    """The displayed code rotates, so a photographed screen goes stale."""
    gateway = MobileApprovalGateway()
    session_id = uuid4()

    first = gateway.create_pairing(session_id)
    gateway.create_pairing(session_id)

    from nexuss.mobile.gateway import MobilePairingError

    try:
        gateway.pair(first.pairing_code, "Phone")
    except MobilePairingError as exc:
        assert str(exc) == "PAIRING_CODE_INVALID"
    else:  # pragma: no cover - the superseded code must not pair
        raise AssertionError("A retired pairing code was accepted.")


def test_pairing_without_a_gateway_fails_closed() -> None:
    _, step = _plan_step("pair my phone")
    result = execute_step(step, observed_at=datetime.now(UTC))
    assert result.status is StepStatus.FAILED
    assert result.error_code == "MOBILE_PAIRING_GATEWAY_NOT_CONFIGURED"


def test_unpair_refuses_when_the_target_is_ambiguous() -> None:
    gateway = MobileApprovalGateway()
    session_id = uuid4()
    for label in ("Phone A", "Phone B"):
        challenge = gateway.create_pairing(session_id)
        gateway.pair(challenge.pairing_code, label)

    _, step = _plan_step("unpair my phone")
    result = execute_step(
        step,
        observed_at=datetime.now(UTC),
        pairing_gateway=gateway,
    )

    assert result.status is StepStatus.FAILED
    assert result.error_code == "PAIRED_DEVICE_AMBIGUOUS"
    assert len(gateway.list_devices()) == 2


def test_unpair_removes_a_named_device() -> None:
    gateway = MobileApprovalGateway()
    session_id = uuid4()
    for label in ("Phone A", "Phone B"):
        challenge = gateway.create_pairing(session_id)
        gateway.pair(challenge.pairing_code, label)

    _, step = _plan_step("unpair Phone A")
    result = execute_step(
        step,
        observed_at=datetime.now(UTC),
        pairing_gateway=gateway,
    )

    remaining = gateway.list_devices()
    assert result.status is StepStatus.VERIFIED
    assert len(remaining) == 1
    assert remaining[0].device_label == "Phone B"


def test_listing_devices_never_exposes_a_token_digest() -> None:
    gateway = MobileApprovalGateway()
    challenge = gateway.create_pairing(uuid4())
    gateway.pair(challenge.pairing_code, "Primary phone")

    _, step = _plan_step("show my paired devices")
    result = execute_step(
        step,
        observed_at=datetime.now(UTC),
        pairing_gateway=gateway,
    )

    attributes = result.evidence[0].attributes
    assert attributes["device_count"] == 1
    assert "token_sha256" not in str(attributes)
    assert isinstance(UUID(str(attributes["devices"][0]["device_id"])), UUID)
