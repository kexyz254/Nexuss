"""Durable safe economic ledger for provider usage.

P6.14 — AI Usage Economics.

The ledger is append-only and stores immutable historical cost records. Each
record captures the pricing version used, the UTC timestamp, authoritative
token usage (where available), and the calculated cost. Records are never
mutated in place; corrections are appended as new records.

The ledger is "safe" in the sense that it never writes outside the managed
workspace, never stores credentials, and never fabricates usage.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Optional

from .pricing import (
    CostBreakdown,
    ModelPricing,
    TokenUsage,
    calculate_cost,
    get_pricing,
)

UTC = timezone.utc


@dataclass(frozen=True)
class LedgerRecord:
    """One immutable economic record."""

    record_id: str
    provider: str
    model: str
    pricing_version: int
    timestamp_utc: str
    is_peak: bool
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    cache_hit_tokens: Optional[int]
    cache_miss_tokens: Optional[int]
    cache_hit_cost: str
    cache_miss_cost: str
    output_cost: str
    total_cost: str
    estimated: bool = False
    mission_id: Optional[str] = None

    @property
    def total_cost_decimal(self) -> Decimal:
        return Decimal(self.total_cost)


class EconomicLedger:
    """Append-only, thread-safe economic ledger persisted as JSONL."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> list[LedgerRecord]:
        if not self._path.exists():
            return []
        records: list[LedgerRecord] = []
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                records.append(LedgerRecord(**json.loads(line)))
        return records

    def append(
        self,
        *,
        provider: str,
        model: str,
        usage: TokenUsage,
        when: datetime,
        pricing: Optional[ModelPricing] = None,
        estimated: bool = False,
        mission_id: Optional[str] = None,
        record_id: Optional[str] = None,
    ) -> LedgerRecord:
        """Append an immutable cost record and return it."""
        pricing = pricing or get_pricing(provider, model)
        breakdown = calculate_cost(usage, pricing, when)
        record = LedgerRecord(
            record_id=record_id or _new_record_id(),
            provider=provider,
            model=model,
            pricing_version=pricing.version,
            timestamp_utc=when.astimezone(UTC).isoformat(),
            is_peak=pricing.is_peak(when),
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_hit_tokens=usage.cache_hit_tokens,
            cache_miss_tokens=usage.cache_miss_tokens,
            cache_hit_cost=str(breakdown.cache_hit_cost),
            cache_miss_cost=str(breakdown.cache_miss_cost),
            output_cost=str(breakdown.output_cost),
            total_cost=str(breakdown.total),
            estimated=estimated,
            mission_id=mission_id,
        )
        with self._lock:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(asdict(record), sort_keys=True) + "\n")
        return record

    def records(self) -> list[LedgerRecord]:
        with self._lock:
            return self._load()

    def total_cost(self, *, estimated: Optional[bool] = None) -> Decimal:
        total = Decimal("0")
        for record in self.records():
            if estimated is not None and record.estimated != estimated:
                continue
            total += record.total_cost_decimal
        return total

    def total_for_mission(self, mission_id: str) -> Decimal:
        total = Decimal("0")
        for record in self.records():
            if record.mission_id == mission_id:
                total += record.total_cost_decimal
        return total


def _new_record_id() -> str:
    import uuid

    return uuid.uuid4().hex


def default_ledger_path() -> Path:
    """Return the default ledger location inside the managed workspace."""
    workspace = os.environ.get("NEXUSS_MANAGED_WORKSPACE", str(Path.home() / ".nexuss" / "workspace"))
    return Path(workspace) / "economics" / "ledger.jsonl"
