"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Durable storage for paired phone sessions.

The gateway keeps devices in memory for the hot path and mirrors every write
here, so a Core restart no longer forces the operator to re-pair. Only the
token digest is persisted; the bearer token itself never leaves the phone
after pairing.

Two adapters, following the provider pattern already used for the device node
client: an in-memory store that keeps the test suite hermetic, and a SQLite
store selected by environment for real runs.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Protocol
from uuid import UUID

_SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS paired_devices (
    device_id    TEXT PRIMARY KEY,
    device_label TEXT NOT NULL,
    session_id   TEXT NOT NULL,
    token_sha256 TEXT NOT NULL,
    paired_at    TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    expires_at   TEXT NOT NULL
);
"""


@dataclass(frozen=True, slots=True)
class StoredDevice:
    """A paired phone as it is held at rest."""

    device_id: UUID
    device_label: str
    session_id: UUID
    token_sha256: str
    paired_at: datetime
    last_seen_at: datetime
    expires_at: datetime


class DeviceStore(Protocol):
    """Persistence port for paired devices."""

    def load_all(self) -> tuple[StoredDevice, ...]:
        """Return every device currently on record."""
        ...

    def upsert(self, device: StoredDevice) -> None:
        """Insert or replace a device record."""
        ...

    def delete(self, device_id: UUID) -> None:
        """Remove a device record permanently."""
        ...


class InMemoryDeviceStore:
    """Non-durable store. Default, and what the test suite runs against."""

    def __init__(self) -> None:
        self._devices: dict[UUID, StoredDevice] = {}
        self._lock = RLock()

    def load_all(self) -> tuple[StoredDevice, ...]:
        with self._lock:
            return tuple(self._devices.values())

    def upsert(self, device: StoredDevice) -> None:
        with self._lock:
            self._devices[device.device_id] = device

    def delete(self, device_id: UUID) -> None:
        with self._lock:
            self._devices.pop(device_id, None)


class SqliteDeviceStore:
    """SQLite-backed store.

    A connection is opened per operation rather than shared across threads.
    Pairing traffic is low enough that connection setup is irrelevant, and it
    removes an entire class of threading bug from a security-relevant path.
    """

    def __init__(self, database_path: Path) -> None:
        self._path = database_path
        self._lock = RLock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=5.0)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialise(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(_SCHEMA)
            row = connection.execute("SELECT version FROM schema_version").fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO schema_version (version) VALUES (?)",
                    (_SCHEMA_VERSION,),
                )
            elif int(row[0]) != _SCHEMA_VERSION:
                raise RuntimeError(
                    "STOP: paired-device store schema version "
                    f"{row[0]} is not supported by this build "
                    f"(expected {_SCHEMA_VERSION})."
                )

    def load_all(self) -> tuple[StoredDevice, ...]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT device_id, device_label, session_id, token_sha256, "
                "paired_at, last_seen_at, expires_at FROM paired_devices"
            ).fetchall()

        return tuple(
            StoredDevice(
                device_id=UUID(row[0]),
                device_label=str(row[1]),
                session_id=UUID(row[2]),
                token_sha256=str(row[3]),
                paired_at=datetime.fromisoformat(row[4]),
                last_seen_at=datetime.fromisoformat(row[5]),
                expires_at=datetime.fromisoformat(row[6]),
            )
            for row in rows
        )

    def upsert(self, device: StoredDevice) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO paired_devices ("
                "device_id, device_label, session_id, token_sha256, "
                "paired_at, last_seen_at, expires_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(device_id) DO UPDATE SET "
                "device_label=excluded.device_label, "
                "session_id=excluded.session_id, "
                "token_sha256=excluded.token_sha256, "
                "last_seen_at=excluded.last_seen_at, "
                "expires_at=excluded.expires_at",
                (
                    str(device.device_id),
                    device.device_label,
                    str(device.session_id),
                    device.token_sha256,
                    device.paired_at.isoformat(),
                    device.last_seen_at.isoformat(),
                    device.expires_at.isoformat(),
                ),
            )

    def delete(self, device_id: UUID) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM paired_devices WHERE device_id = ?",
                (str(device_id),),
            )


def device_store_from_environment() -> DeviceStore:
    """Select a store from NEXUSS_MOBILE_DEVICE_STORE.

    Unset means in-memory, matching how the device-node client degrades when
    it is not configured. Tests therefore never touch the filesystem unless
    they ask to.
    """
    configured = os.getenv("NEXUSS_MOBILE_DEVICE_STORE", "").strip()
    if not configured:
        return InMemoryDeviceStore()
    return SqliteDeviceStore(Path(configured))
