"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

HMAC signing helpers for local P4 device-node envelopes.
"""

from __future__ import annotations

import hashlib
import hmac
import json

from pydantic import BaseModel


class DeviceSignatureError(ValueError):
    """Raised when a signed device-node message cannot be authenticated."""


def canonical_payload(model: BaseModel) -> bytes:
    return json.dumps(
        model.model_dump(mode="json", exclude_none=True, by_alias=True),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sign_payload(model: BaseModel, secret: str) -> str:
    if len(secret) < 32:
        raise DeviceSignatureError("DEVICE_NODE_SECRET_TOO_SHORT")
    return hmac.new(
        secret.encode("utf-8"),
        canonical_payload(model),
        hashlib.sha256,
    ).hexdigest()


def verify_signature(model: BaseModel, secret: str, signature: str) -> None:
    expected = sign_payload(model, secret)
    if not hmac.compare_digest(expected, signature):
        raise DeviceSignatureError("DEVICE_NODE_SIGNATURE_INVALID")
