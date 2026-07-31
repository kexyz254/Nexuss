"""Bounded process-local stores for P6.7A mobile signals and actions."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from uuid import UUID

from nexuss.mobile_fabric.models import MobileFeedItem, MobileSignal


@dataclass(frozen=True, slots=True)
class SignalInsertResult:
    accepted: int
    duplicates: int
    latest_cursor: int


class MobileSignalStore:
    def __init__(self, *, maximum_items: int = 5_000) -> None:
        if maximum_items < 100:
            raise ValueError("maximum_items must be at least 100")
        self._items: deque[MobileFeedItem] = deque(maxlen=maximum_items)
        self._event_ids: set[UUID] = set()
        self._content_hashes: set[str] = set()
        self._cursor = 0
        self._lock = RLock()

    def insert(self, device_id: UUID, signals: tuple[MobileSignal, ...]) -> SignalInsertResult:
        accepted = 0
        duplicates = 0
        observed_at = datetime.now(UTC)
        with self._lock:
            for signal in signals:
                content_hash = signal.content_sha256 or ""
                if signal.event_id in self._event_ids or (
                    content_hash and content_hash in self._content_hashes
                ):
                    duplicates += 1
                    continue
                if self._items.maxlen and len(self._items) == self._items.maxlen:
                    removed = self._items[0]
                    self._event_ids.discard(removed.signal.event_id)
                    if removed.signal.content_sha256:
                        self._content_hashes.discard(removed.signal.content_sha256)
                self._cursor += 1
                item = MobileFeedItem(
                    cursor=self._cursor,
                    device_id=device_id,
                    signal=signal,
                    observed_at=observed_at,
                )
                self._items.append(item)
                self._event_ids.add(signal.event_id)
                if content_hash:
                    self._content_hashes.add(content_hash)
                accepted += 1
            return SignalInsertResult(
                accepted=accepted,
                duplicates=duplicates,
                latest_cursor=self._cursor,
            )

    def list(
        self,
        *,
        after_cursor: int = 0,
        limit: int = 100,
    ) -> tuple[MobileFeedItem, ...]:
        with self._lock:
            matches = [item for item in self._items if item.cursor > after_cursor]
        return tuple(matches[-limit:])

    def latest_cursor(self) -> int:
        with self._lock:
            return self._cursor

    def total(self) -> int:
        with self._lock:
            return len(self._items)
