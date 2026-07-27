"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

The memory substrate: trust, decay, supersession, refusal, durability.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from nexuss.memory.models import Episode, SourceTrust, Volatility
from nexuss.memory.store import MemoryWriteRefused, SqliteMemoryStore


def _store(tmp_path: Path) -> SqliteMemoryStore:
    return SqliteMemoryStore(tmp_path / "memory.db")


def test_recall_returns_provenance_with_every_match(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.remember(
        topic="order books",
        statement="An order book matches bids against asks by price-time priority.",
        source_ref="user",
        source_trust=SourceTrust.USER_ASSERTED,
        confidence=0.95,
        volatility=Volatility.STABLE,
    )

    match = store.recall("order book priority")[0]

    assert match.claim.source_ref == "user"
    assert match.claim.source_trust is SourceTrust.USER_ASSERTED
    assert match.score > 0


def test_volatile_claims_decay_and_stable_claims_do_not(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.remember(
        topic="mechanics",
        statement="Order books match bids against asks.",
        source_ref="user",
        source_trust=SourceTrust.USER_ASSERTED,
        confidence=0.9,
        volatility=Volatility.STABLE,
    )
    store.remember(
        topic="rates",
        statement="Funding rates hover near a hundredth of a percent.",
        source_ref="https://example.com/tutorial",
        source_trust=SourceTrust.PUBLIC_WEB,
        confidence=0.9,
        volatility=Volatility.VOLATILE,
    )

    later = datetime.now(UTC) + timedelta(days=30)
    by_topic = {
        match.claim.topic: match
        for match in store.recall("order books funding rates", limit=5, now=later)
    }

    assert by_topic["mechanics"].decayed_confidence == pytest.approx(0.9)
    assert by_topic["rates"].decayed_confidence < 0.06


def test_user_asserted_outranks_public_web_for_identical_text(tmp_path: Path) -> None:
    store = _store(tmp_path)
    text = "Maker fees are lower than taker fees on most venues."
    store.remember(
        topic="fees",
        statement=text,
        source_ref="https://example.com/video",
        source_trust=SourceTrust.PUBLIC_WEB,
        confidence=0.8,
        volatility=Volatility.STABLE,
    )
    store.remember(
        topic="fees",
        statement=text,
        source_ref="user",
        source_trust=SourceTrust.USER_ASSERTED,
        confidence=0.8,
        volatility=Volatility.STABLE,
    )

    top = store.recall("maker taker fees")[0]

    assert top.claim.source_trust is SourceTrust.USER_ASSERTED


def test_superseded_claims_leave_recall_but_conflicts_stay_visible(tmp_path: Path) -> None:
    store = _store(tmp_path)
    old = store.remember(
        topic="fees",
        statement="Venue X pays maker rebates.",
        source_ref="https://example.com/2024-tutorial",
        source_trust=SourceTrust.PUBLIC_WEB,
        confidence=0.7,
        volatility=Volatility.SEASONAL,
    )
    new = store.remember(
        topic="fees",
        statement="Venue X removed maker rebates in 2026.",
        source_ref="https://docs.venue-x.example/fees",
        source_trust=SourceTrust.CURATED_DOC,
        confidence=0.9,
        volatility=Volatility.SEASONAL,
    )

    store.supersede(old.claim_id, new.claim_id)

    active = store.active_claims("fees")
    assert [claim.claim_id for claim in active] == [new.claim_id]
    assert all(match.claim.claim_id != old.claim_id for match in store.recall("rebates"))


def test_supersession_is_explicit_and_cannot_be_repeated(tmp_path: Path) -> None:
    store = _store(tmp_path)
    old = store.remember(
        topic="t",
        statement="First version.",
        source_ref="user",
        source_trust=SourceTrust.USER_ASSERTED,
        confidence=0.9,
        volatility=Volatility.STABLE,
    )
    new = store.remember(
        topic="t",
        statement="Second version.",
        source_ref="user",
        source_trust=SourceTrust.USER_ASSERTED,
        confidence=0.9,
        volatility=Volatility.STABLE,
    )
    store.supersede(old.claim_id, new.claim_id)

    with pytest.raises(MemoryWriteRefused):
        store.supersede(old.claim_id, new.claim_id)


def test_credential_shaped_statements_are_refused_not_masked(tmp_path: Path) -> None:
    store = _store(tmp_path)
    shaped = (
        "my key is AIzaSyA" + "x" * 33,
        "token sk-" + "a" * 24,
        "-----BEGIN PRIVATE KEY-----",
        "aws AKIA" + "A" * 16,
    )
    for statement in shaped:
        with pytest.raises(MemoryWriteRefused):
            store.remember(
                topic="t",
                statement=statement,
                source_ref="user",
                source_trust=SourceTrust.USER_ASSERTED,
                confidence=1.0,
                volatility=Volatility.STABLE,
            )
    assert store.recall("key token") == ()


def test_forget_removes_claims_and_their_index_rows(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.remember(
        topic="fees",
        statement="Maker fees are lower than taker fees.",
        source_ref="user",
        source_trust=SourceTrust.USER_ASSERTED,
        confidence=0.9,
        volatility=Volatility.STABLE,
    )

    assert store.forget_topic("fees") == 1
    assert store.recall("maker taker fees") == ()
    assert store.active_claims("fees") == ()


def test_claims_and_episodes_survive_a_restart(tmp_path: Path) -> None:
    database = tmp_path / "memory.db"
    first = SqliteMemoryStore(database)
    claim = first.remember(
        topic="order books",
        statement="Bids match asks by price-time priority.",
        source_ref="user",
        source_trust=SourceTrust.USER_ASSERTED,
        confidence=0.95,
        volatility=Volatility.STABLE,
    )
    episode = Episode(
        episode_id=uuid4(),
        session_id=uuid4(),
        task_id=uuid4(),
        utterance="Pair my phone",
        intent="pair_phone",
        capability_id="device.pair_phone",
        outcome="completed",
        occurred_at=datetime.now(UTC),
    )
    first.record_episode(episode)

    reopened = SqliteMemoryStore(database)

    assert reopened.recall("price time priority")[0].claim.claim_id == claim.claim_id
    assert reopened.recent_episodes(episode.session_id)[0].episode_id == episode.episode_id


def test_topic_ceiling_refuses_flooding(tmp_path: Path) -> None:
    store = _store(tmp_path)
    from nexuss.memory import store as store_module

    original = store_module._MAX_CLAIMS_PER_TOPIC
    store_module._MAX_CLAIMS_PER_TOPIC = 3
    try:
        for index in range(3):
            store.remember(
                topic="flood",
                statement=f"Statement number {index}.",
                source_ref="user",
                source_trust=SourceTrust.USER_ASSERTED,
                confidence=0.9,
                volatility=Volatility.STABLE,
            )
        with pytest.raises(MemoryWriteRefused):
            store.remember(
                topic="flood",
                statement="One statement too many.",
                source_ref="user",
                source_trust=SourceTrust.USER_ASSERTED,
                confidence=0.9,
                volatility=Volatility.STABLE,
            )
    finally:
        store_module._MAX_CLAIMS_PER_TOPIC = original
