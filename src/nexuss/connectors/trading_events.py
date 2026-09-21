"""Durable TAS observation ingestion and conservative self-healing planning.

This module deliberately separates *diagnosis* from *execution*.  Nexuss may
persist/replay evidence and propose bounded repairs, but it cannot trade, reset
the TAS breaker, deploy, or execute shell commands through this capability.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class RepairProposal:
    action: str
    reason: str
    approval_required: bool = True


class TradingEventStore:
    """SQLite-backed, idempotent observation journal with a durable cursor."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def _init(self) -> None:
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS tas_observations (
                event_key TEXT PRIMARY KEY,
                cursor INTEGER NOT NULL,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS tas_state (
                name TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )""")
            db.execute("INSERT OR IGNORE INTO tas_state(name,value) VALUES('cursor','0')")

    def cursor(self) -> int:
        with self._connect() as db:
            row = db.execute("SELECT value FROM tas_state WHERE name='cursor'").fetchone()
        return int(row[0]) if row else 0

    def ingest_page(self, events: Iterable[dict[str, Any]], next_cursor: int) -> int:
        """Atomically persist a page and advance only after every event is durable."""
        if type(next_cursor) is not int or next_cursor < self.cursor():
            raise ValueError("Observation cursor cannot move backwards")
        inserted = 0
        with self._connect() as db:
            for event in events:
                raw = json.dumps(event, sort_keys=True, separators=(",", ":"), allow_nan=False)
                digest = hashlib.sha256(raw.encode()).hexdigest()
                event_cursor = event.get("cursor")
                if type(event_cursor) is not int or event_cursor < 0 or event_cursor > next_cursor:
                    raise ValueError("Invalid event cursor")
                kind = str(event.get("kind") or event.get("type") or "unknown")[:128]
                key = str(event.get("id") or f"{event_cursor}:{digest}")[:256]
                result = db.execute(
                    "INSERT OR IGNORE INTO tas_observations(event_key,cursor,kind,payload,payload_sha256) VALUES(?,?,?,?,?)",
                    (key, event_cursor, kind, raw, digest),
                )
                inserted += result.rowcount
            db.execute("UPDATE tas_state SET value=? WHERE name='cursor'", (str(next_cursor),))
        return inserted

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1000:
            raise ValueError("Invalid limit")
        with self._connect() as db:
            rows = db.execute(
                "SELECT payload FROM tas_observations ORDER BY cursor DESC, event_key DESC LIMIT ?", (limit,)
            ).fetchall()
        return [json.loads(row[0]) for row in rows]


def plan_repairs(health: dict[str, Any], worker: dict[str, Any]) -> list[RepairProposal]:
    """Translate evidence into proposals; never authorize external execution."""
    proposals: list[RepairProposal] = []
    if worker.get("backlog_full") is True:
        proposals.append(RepairProposal("drain_observation_backlog", "TAS observer backlog is full"))
    if worker.get("stale") is True:
        proposals.append(RepairProposal("restart_observer_worker", "TAS observer heartbeat is stale"))
    reasons = health.get("reasons") or []
    if health.get("breaker") is True or "circuit breaker tripped" in reasons:
        proposals.append(RepairProposal(
            "diagnose_circuit_breaker",
            "Circuit breaker is tripped; collect evidence before any recovery action",
        ))
    if health.get("recent_error_rate", 0) and float(health["recent_error_rate"]) > 0.25:
        proposals.append(RepairProposal("investigate_error_rate", "Recent TAS error rate exceeds 25%"))
    return proposals
