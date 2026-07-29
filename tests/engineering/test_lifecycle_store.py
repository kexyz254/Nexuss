from __future__ import annotations

from pathlib import Path

from nexuss.engineering.lifecycle import (
    EngineeringLifecycleOutcome,
    EngineeringLifecycleState,
)
from nexuss.engineering.models import ProviderKind
from nexuss.engineering.provider_connections import (
    ProviderAccessCode,
    ProviderAccessDecision,
)
from nexuss.engineering.store import (
    JsonEngineeringLifecycleStore,
)


def test_store_round_trip(tmp_path: Path) -> None:
    access = ProviderAccessDecision(
        provider_id="deepseek",
        provider_kind=ProviderKind.DEEPSEEK,
        available=False,
        code=ProviderAccessCode.INSUFFICIENT_BALANCE,
        user_message="Pay for DeepSeek API access.",
        model="deepseek-v4-pro",
        identity_verified=True,
        billing_ready=False,
        credential_present=True,
    )
    outcome = EngineeringLifecycleOutcome(
        task_id=__import__("uuid").uuid4(),
        state=EngineeringLifecycleState.PROVIDER_BLOCKED,
        message=access.user_message,
        provider_access=access,
        events=(),
        workspace_created=False,
        github_changed=False,
        published=False,
        credentials_exposed=False,
    )
    store = JsonEngineeringLifecycleStore(tmp_path)

    path = store.save(outcome)
    loaded = store.load(outcome.task_id)

    assert path.exists()
    assert loaded == outcome
    assert "api_key" not in path.read_text(encoding="utf-8")
