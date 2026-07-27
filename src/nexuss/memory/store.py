"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Durable memory for Nexuss: episodic (what happened) and semantic (what is
known), on SQLite with FTS5 lexical recall.

Design properties, per ADR-0009:
- Trust is enforced at the storage boundary. Every claim carries its tier.
- Confidence decays by volatility at recall time; the stored value is never
  mutated, so the decay curve can be tuned without rewriting history.
- Contradictions are never resolved silently: supersession is an explicit,
  recorded act, and conflicting active claims are surfaced together.
- Credential-shaped content is refused at write time, not masked. Memory must
  not become the hole in the no-persisted-secrets discipline.
- Recall always returns provenance. Score = relevance x trust x decayed
  confidence, and all three factors ride along in the result.
"""

from __future__ import annotations

import math
import os
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Protocol
from uuid import UUID, uuid4

from nexuss.memory.models import (
    Episode,
    MemoryClaim,
    RecallMatch,
    SourceTrust,
    Volatility,
)

_SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS episodes (
    episode_id    TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL,
    task_id       TEXT NOT NULL,
    utterance     TEXT NOT NULL,
    intent        TEXT NOT NULL,
    capability_id TEXT NOT NULL,
    outcome       TEXT NOT NULL,
    occurred_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claims (
    claim_id      TEXT PRIMARY KEY,
    topic         TEXT NOT NULL,
    statement     TEXT NOT NULL,
    source_ref    TEXT NOT NULL,
    source_trust  TEXT NOT NULL,
    confidence    REAL NOT NULL,
    volatility    TEXT NOT NULL,
    observed_at   TEXT NOT NULL,
    superseded_by TEXT,
    episode_id    TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS claims_fts USING fts5(
    claim_id UNINDEXED,
    topic,
    statement
);
"""

_TRUST_WEIGHT: dict[SourceTrust, float] = {
    SourceTrust.USER_ASSERTED: 1.0,
    SourceTrust.CURATED_DOC: 0.85,
    SourceTrust.PUBLIC_WEB: 0.6,
}

# Half-life in days. None means the claim does not decay.
_HALF_LIFE_DAYS: dict[Volatility, float | None] = {
    Volatility.STABLE: None,
    Volatility.SEASONAL: 90.0,
    Volatility.VOLATILE: 7.0,
}

# Credential shapes refused at the write boundary. Deliberately specific:
# a generic long-string rule would reject ordinary prose.
_CREDENTIAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\."),
    re.compile(r"PRIVATE KEY", re.IGNORECASE),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)

_MAX_CLAIMS_PER_TOPIC = 500


class MemoryWriteRefused(ValueError):
    """Raised when a write violates a storage invariant. Fail closed."""


class MemoryStore(Protocol):
    """Persistence port for the memory plane."""

    def remember(
        self,
        *,
        topic: str,
        statement: str,
        source_ref: str,
        source_trust: SourceTrust,
        confidence: float,
        volatility: Volatility,
        episode_id: UUID | None = None,
        now: datetime | None = None,
    ) -> MemoryClaim: ...

    def recall(
        self,
        query: str,
        *,
        limit: int = 5,
        now: datetime | None = None,
    ) -> tuple[RecallMatch, ...]: ...

    def active_claims(self, topic: str) -> tuple[MemoryClaim, ...]: ...

    def supersede(self, old_claim_id: UUID, new_claim_id: UUID) -> None: ...

    def forget_topic(self, topic: str) -> int: ...

    def record_episode(self, episode: Episode) -> None: ...

    def recent_episodes(self, session_id: UUID, *, limit: int = 20) -> tuple[Episode, ...]: ...


def _refuse_credentials(statement: str) -> None:
    for pattern in _CREDENTIAL_PATTERNS:
        if pattern.search(statement):
            raise MemoryWriteRefused(
                "MEMORY_WRITE_REFUSED_CREDENTIAL_SHAPED: the statement matches "
                "a credential pattern and will not be stored."
            )


def _decayed(confidence: float, volatility: Volatility, age_days: float) -> float:
    half_life = _HALF_LIFE_DAYS[volatility]
    if half_life is None or age_days <= 0:
        return confidence
    return confidence * math.pow(0.5, age_days / half_life)


class SqliteMemoryStore:
    """SQLite-backed store. A connection per operation, matching the paired
    device store: memory traffic is low and it removes threading bugs from a
    trust-relevant path."""

    def __init__(self, database_path: Path) -> None:
        self._path = database_path
        self._lock = RLock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=5.0)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialise(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(_SCHEMA)
            row = connection.execute(
                "SELECT version FROM memory_schema_version"
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO memory_schema_version (version) VALUES (?)",
                    (_SCHEMA_VERSION,),
                )
            elif int(row[0]) != _SCHEMA_VERSION:
                raise RuntimeError(
                    f"STOP: memory schema version {row[0]} is not supported "
                    f"by this build (expected {_SCHEMA_VERSION})."
                )

    # ----------------------------------------------------------- semantic

    def remember(
        self,
        *,
        topic: str,
        statement: str,
        source_ref: str,
        source_trust: SourceTrust,
        confidence: float,
        volatility: Volatility,
        episode_id: UUID | None = None,
        now: datetime | None = None,
    ) -> MemoryClaim:
        _refuse_credentials(statement)
        _refuse_credentials(topic)

        claim = MemoryClaim(
            claim_id=uuid4(),
            topic=topic.strip(),
            statement=statement.strip(),
            source_ref=source_ref,
            source_trust=source_trust,
            confidence=confidence,
            volatility=volatility,
            observed_at=now or datetime.now(UTC),
            superseded_by=None,
            episode_id=episode_id,
        )

        with self._lock, self._connect() as connection:
            existing = connection.execute(
                "SELECT COUNT(*) FROM claims WHERE topic = ?",
                (claim.topic,),
            ).fetchone()
            if int(existing[0]) >= _MAX_CLAIMS_PER_TOPIC:
                raise MemoryWriteRefused(
                    "MEMORY_TOPIC_CEILING_REACHED: refusing to flood a topic; "
                    "consolidate or forget before adding more."
                )
            connection.execute(
                "INSERT INTO claims (claim_id, topic, statement, source_ref, "
                "source_trust, confidence, volatility, observed_at, "
                "superseded_by, episode_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(claim.claim_id),
                    claim.topic,
                    claim.statement,
                    claim.source_ref,
                    claim.source_trust.value,
                    claim.confidence,
                    claim.volatility.value,
                    claim.observed_at.isoformat(),
                    None,
                    str(episode_id) if episode_id else None,
                ),
            )
            connection.execute(
                "INSERT INTO claims_fts (claim_id, topic, statement) VALUES (?, ?, ?)",
                (str(claim.claim_id), claim.topic, claim.statement),
            )
        return claim

    def recall(
        self,
        query: str,
        *,
        limit: int = 5,
        now: datetime | None = None,
    ) -> tuple[RecallMatch, ...]:
        checked_at = now or datetime.now(UTC)
        sanitized = re.sub(r"[^\w\s]", " ", query).strip()
        if not sanitized:
            return ()
        fts_query = " OR ".join(sanitized.split())

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT c.claim_id, c.topic, c.statement, c.source_ref, "
                "c.source_trust, c.confidence, c.volatility, c.observed_at, "
                "c.superseded_by, c.episode_id, bm25(claims_fts) AS rank "
                "FROM claims_fts JOIN claims c ON c.claim_id = claims_fts.claim_id "
                "WHERE claims_fts MATCH ? AND c.superseded_by IS NULL "
                "ORDER BY rank LIMIT ?",
                (fts_query, max(limit * 4, limit)),
            ).fetchall()

        matches: list[RecallMatch] = []
        for row in rows:
            claim = _claim_from_row(row)
            age_days = (checked_at - claim.observed_at).total_seconds() / 86_400
            decayed = _decayed(claim.confidence, claim.volatility, age_days)
            relevance = 1.0 / (1.0 + max(float(row[10]), 0.0))
            score = relevance * _TRUST_WEIGHT[claim.source_trust] * decayed
            matches.append(
                RecallMatch(claim=claim, score=score, decayed_confidence=decayed)
            )

        matches.sort(key=lambda match: match.score, reverse=True)
        return tuple(matches[:limit])

    def active_claims(self, topic: str) -> tuple[MemoryClaim, ...]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT claim_id, topic, statement, source_ref, source_trust, "
                "confidence, volatility, observed_at, superseded_by, episode_id "
                "FROM claims WHERE topic = ? AND superseded_by IS NULL "
                "ORDER BY observed_at",
                (topic.strip(),),
            ).fetchall()
        return tuple(_claim_from_row(row) for row in rows)

    def supersede(self, old_claim_id: UUID, new_claim_id: UUID) -> None:
        with self._lock, self._connect() as connection:
            updated = connection.execute(
                "UPDATE claims SET superseded_by = ? "
                "WHERE claim_id = ? AND superseded_by IS NULL",
                (str(new_claim_id), str(old_claim_id)),
            )
            if updated.rowcount != 1:
                raise MemoryWriteRefused(
                    "MEMORY_SUPERSEDE_TARGET_INVALID: the claim does not exist "
                    "or is already superseded."
                )

    def forget_topic(self, topic: str) -> int:
        with self._lock, self._connect() as connection:
            claim_ids = [
                str(row[0])
                for row in connection.execute(
                    "SELECT claim_id FROM claims WHERE topic = ?",
                    (topic.strip(),),
                ).fetchall()
            ]
            for claim_id in claim_ids:
                connection.execute(
                    "DELETE FROM claims_fts WHERE claim_id = ?", (claim_id,)
                )
            connection.execute("DELETE FROM claims WHERE topic = ?", (topic.strip(),))
        return len(claim_ids)

    # ----------------------------------------------------------- episodic

    def record_episode(self, episode: Episode) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO episodes (episode_id, session_id, "
                "task_id, utterance, intent, capability_id, outcome, occurred_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(episode.episode_id),
                    str(episode.session_id),
                    str(episode.task_id),
                    episode.utterance,
                    episode.intent,
                    episode.capability_id,
                    episode.outcome,
                    episode.occurred_at.isoformat(),
                ),
            )

    def recent_episodes(
        self, session_id: UUID, *, limit: int = 20
    ) -> tuple[Episode, ...]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT episode_id, session_id, task_id, utterance, intent, "
                "capability_id, outcome, occurred_at FROM episodes "
                "WHERE session_id = ? ORDER BY occurred_at DESC LIMIT ?",
                (str(session_id), limit),
            ).fetchall()
        return tuple(
            Episode(
                episode_id=UUID(str(row[0])),
                session_id=UUID(str(row[1])),
                task_id=UUID(str(row[2])),
                utterance=str(row[3]),
                intent=str(row[4]),
                capability_id=str(row[5]),
                outcome=str(row[6]),
                occurred_at=datetime.fromisoformat(str(row[7])),
            )
            for row in rows
        )


def _claim_from_row(row: sqlite3.Row | tuple[object, ...]) -> MemoryClaim:
    return MemoryClaim(
        claim_id=UUID(str(row[0])),
        topic=str(row[1]),
        statement=str(row[2]),
        source_ref=str(row[3]),
        source_trust=SourceTrust(str(row[4])),
        confidence=float(str(row[5])),
        volatility=Volatility(str(row[6])),
        observed_at=datetime.fromisoformat(str(row[7])),
        superseded_by=UUID(str(row[8])) if row[8] else None,
        episode_id=UUID(str(row[9])) if row[9] else None,
    )


def memory_store_from_environment() -> MemoryStore:
    """Select a store from NEXUSS_MEMORY_STORE.

    Unset means an isolated in-memory database file is NOT used; instead a
    temporary path under the working directory would leak between tests, so
    the default is a fresh SQLite database in the process temporary directory
    semantics: callers that need hermetic behaviour (the test suite) construct
    SqliteMemoryStore(tmp_path / ...) directly.
    """
    configured = os.getenv("NEXUSS_MEMORY_STORE", "").strip()
    if configured:
        return SqliteMemoryStore(Path(configured))
    import tempfile

    return SqliteMemoryStore(
        Path(tempfile.mkdtemp(prefix="nexuss-memory-")) / "memory.db"
    )
