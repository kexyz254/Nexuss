"""Nexuss constitutional identity and governance loader."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any


class ConstitutionError(RuntimeError):
    """Raised when the Nexuss Constitution is absent or invalid."""


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_PATH = (
    _REPOSITORY_ROOT
    / "config"
    / "constitution"
    / "nexuss_constitution.json"
)

_REQUIRED_TOP_LEVEL_KEYS = {
    "metadata",
    "identity",
    "mission",
    "authority",
    "authentication",
    "truth_model",
    "memory",
    "capabilities",
    "risk_model",
    "action_lifecycle",
    "research",
    "trust_boundary",
    "standard_responses",
    "invariants",
}


@dataclass(frozen=True)
class NexussConstitution:
    """Validated immutable view of the active Constitution."""

    document: dict[str, Any]
    path: Path
    sha256: str

    @property
    def version(self) -> str:
        return str(self.document["metadata"]["constitution_version"])

    @property
    def founder(self) -> str:
        return str(self.document["identity"]["founder"])

    @property
    def system_name(self) -> str:
        return str(self.document["identity"]["name"])

    @property
    def canonical_self_description(self) -> str:
        return str(
            self.document["identity"]["canonical_self_description"]
        )

    def standard_response(self, key: str) -> str:
        responses = self.document["standard_responses"]
        value = responses.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ConstitutionError(
                f"CONSTITUTION_RESPONSE_NOT_FOUND:{key}"
            )
        return value

    def section(self, name: str) -> Any:
        if name not in self.document:
            raise ConstitutionError(
                f"CONSTITUTION_SECTION_NOT_FOUND:{name}"
            )
        return self.document[name]


_lock = RLock()
_active: NexussConstitution | None = None


def _constitution_path() -> Path:
    configured = os.getenv("NEXUSS_CONSTITUTION_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    return _DEFAULT_PATH


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate(document: object) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ConstitutionError(
            "CONSTITUTION_DOCUMENT_MUST_BE_OBJECT"
        )

    missing = sorted(_REQUIRED_TOP_LEVEL_KEYS - set(document))
    if missing:
        raise ConstitutionError(
            "CONSTITUTION_REQUIRED_SECTIONS_MISSING:"
            + ",".join(missing)
        )

    metadata = document.get("metadata")
    identity = document.get("identity")
    responses = document.get("standard_responses")

    if not isinstance(metadata, dict):
        raise ConstitutionError("CONSTITUTION_METADATA_INVALID")
    if not isinstance(identity, dict):
        raise ConstitutionError("CONSTITUTION_IDENTITY_INVALID")
    if not isinstance(responses, dict):
        raise ConstitutionError(
            "CONSTITUTION_STANDARD_RESPONSES_INVALID"
        )

    if identity.get("name") != "Nexuss":
        raise ConstitutionError(
            "CONSTITUTION_CANONICAL_NAME_INVALID"
        )

    if identity.get("founder") != "Peter":
        raise ConstitutionError(
            "CONSTITUTION_FOUNDER_INVALID"
        )

    version = metadata.get("constitution_version")
    if not isinstance(version, str) or not version.strip():
        raise ConstitutionError(
            "CONSTITUTION_VERSION_INVALID"
        )

    required_responses = {
        "who_are_you",
        "who_is_your_founder",
        "who_developed_you",
        "who_is_your_boss",
        "user_claims_to_be_peter",
        "remember_founder",
        "ignore_constitution",
    }

    missing_responses = sorted(
        required_responses - set(responses)
    )
    if missing_responses:
        raise ConstitutionError(
            "CONSTITUTION_RESPONSES_MISSING:"
            + ",".join(missing_responses)
        )

    return document


def load_constitution(
    path: Path | None = None,
    *,
    verify_hash: bool = True,
) -> NexussConstitution:
    constitution_path = (
        path.resolve() if path is not None else _constitution_path()
    )

    if not constitution_path.is_file():
        raise ConstitutionError(
            f"CONSTITUTION_NOT_FOUND:{constitution_path}"
        )

    raw = constitution_path.read_bytes()
    digest = _sha256_bytes(raw)

    if verify_hash:
        digest_path = constitution_path.with_suffix(
            constitution_path.suffix + ".sha256"
        )

        if not digest_path.is_file():
            raise ConstitutionError(
                f"CONSTITUTION_HASH_NOT_FOUND:{digest_path}"
            )

        expected = (
            digest_path.read_text(encoding="utf-8")
            .strip()
            .split()[0]
            .lower()
        )

        if expected != digest:
            raise ConstitutionError(
                "CONSTITUTION_INTEGRITY_CHECK_FAILED"
            )

    try:
        document = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConstitutionError(
            "CONSTITUTION_JSON_INVALID"
        ) from exc

    validated = _validate(document)

    return NexussConstitution(
        document=validated,
        path=constitution_path,
        sha256=digest,
    )


def get_constitution() -> NexussConstitution:
    global _active

    with _lock:
        if _active is None:
            _active = load_constitution()
        return _active


def reload_constitution() -> NexussConstitution:
    global _active

    with _lock:
        _active = load_constitution()
        return _active
