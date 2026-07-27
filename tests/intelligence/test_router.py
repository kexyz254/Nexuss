from __future__ import annotations

from uuid import uuid4

import pytest

from nexuss.intelligence.errors import IntelligenceError
from nexuss.intelligence.models import (
    ContentSensitivity,
    IntelligenceMode,
    IntelligenceRequest,
)
from nexuss.intelligence.provider import ExtractiveReasoningProvider
from nexuss.intelligence.router import ProviderRouter


def test_external_mode_requires_explicit_approval() -> None:
    router = ProviderRouter(
        local_provider=ExtractiveReasoningProvider(),
        external_provider=ExtractiveReasoningProvider(),
    )
    request = IntelligenceRequest(
        session_id=uuid4(),
        query="Explain inflation.",
        mode=IntelligenceMode.EXTERNAL_ALLOWED,
        external_processing_approved=False,
    )

    with pytest.raises(
        IntelligenceError,
        match="explicit approval",
    ) as raised:
        router.select(request)

    assert raised.value.code == (
        "INTELLIGENCE_EXTERNAL_APPROVAL_REQUIRED"
    )


def test_private_content_stays_local() -> None:
    local = ExtractiveReasoningProvider()
    router = ProviderRouter(local_provider=local)
    request = IntelligenceRequest(
        session_id=uuid4(),
        query="Summarize my private document.",
        mode=IntelligenceMode.EXTERNAL_ALLOWED,
        sensitivity=ContentSensitivity.PRIVATE,
        external_processing_approved=True,
    )

    assert router.select(request) is local
