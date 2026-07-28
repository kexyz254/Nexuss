from __future__ import annotations

import pytest

from nexuss.engineering.errors import EngineeringError
from nexuss.engineering.models import EngineeringTaskSpec, ProviderKind, TaskSensitivity
from nexuss.engineering.policy import EngineeringPolicy, ProviderProfile


def _external_profile() -> ProviderProfile:
    return ProviderProfile(
        provider_id="deepseek-main",
        kind=ProviderKind.DEEPSEEK,
        model="deepseek-chat",
        api_base="https://api.deepseek.com",
        external=True,
    )


def test_private_external_processing_requires_approval() -> None:
    task = EngineeringTaskSpec(
        goal="build landing page",
        provider_id="deepseek-main",
        sensitivity=TaskSensitivity.PRIVATE,
    )
    with pytest.raises(EngineeringError) as raised:
        EngineeringPolicy.authorize_provider(task, _external_profile())
    assert raised.value.code == "ENGINEERING_EXTERNAL_APPROVAL_REQUIRED"


def test_restricted_never_goes_external() -> None:
    task = EngineeringTaskSpec(
        goal="inspect secrets",
        provider_id="deepseek-main",
        sensitivity=TaskSensitivity.RESTRICTED,
        external_processing_approved=True,
    )
    with pytest.raises(EngineeringError) as raised:
        EngineeringPolicy.authorize_provider(task, _external_profile())
    assert raised.value.code == "ENGINEERING_EXTERNAL_RESTRICTED"
