"""Shared provider parsing."""

from __future__ import annotations

import json

from pydantic import ValidationError

from nexuss.engineering.errors import EngineeringError
from nexuss.engineering.models import ModelProposal


def parse_proposal_text(text: str) -> ModelProposal:
    normalized = text.strip()
    if normalized.startswith("```"):
        lines = normalized.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        normalized = "\n".join(lines).strip()

    try:
        payload = json.loads(normalized)
        return ModelProposal.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise EngineeringError(
            "ENGINEERING_PROVIDER_OUTPUT_INVALID",
            "The provider returned an invalid engineering proposal.",
        ) from exc
