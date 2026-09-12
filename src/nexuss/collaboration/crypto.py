"""Canonical encoding and tamper-evident protocol hashing."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel


ZERO_HASH = "0" * 64


def _normalise(value: object) -> object:
    if isinstance(value, BaseModel):
        return _normalise(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {
            str(key): _normalise(item)
            for key, item in sorted(
                value.items(),
                key=lambda pair: str(pair[0]),
            )
        }
    if isinstance(value, (list, tuple)):
        return [_normalise(item) for item in value]
    if isinstance(value, (datetime, UUID)):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    return value


def canonical_json(value: object) -> str:
    return json.dumps(
        _normalise(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def sha256_json(value: object) -> str:
    return hashlib.sha256(
        canonical_json(value).encode("utf-8")
    ).hexdigest()


def build_message_hash(
    *,
    header: dict[str, object],
    payload_sha256: str,
    previous_message_sha256: str,
) -> str:
    return sha256_json(
        {
            "header": header,
            "payload_sha256": payload_sha256,
            "previous_message_sha256": previous_message_sha256,
        }
    )
