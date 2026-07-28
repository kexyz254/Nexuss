from __future__ import annotations

import json

import httpx
import pytest

from nexuss.connectors.vault import InMemorySecretVault
from nexuss.engineering.errors import EngineeringError
from nexuss.engineering.provider_connections import (
    EngineeringProviderConnectionService,
    ProviderConnectionState,
)


def _transport(
    *,
    model_status: int = 200,
    balance_status: int = 200,
    balance_available: bool = True,
    models: tuple[str, ...] = (
        "deepseek-v4-flash",
        "deepseek-v4-pro",
    ),
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"].startswith(
            "Bearer "
        )
        if request.url.path == "/models":
            return httpx.Response(
                model_status,
                json={
                    "object": "list",
                    "data": [
                        {
                            "id": model,
                            "object": "model",
                            "owned_by": "deepseek",
                        }
                        for model in models
                    ],
                },
            )
        if request.url.path == "/user/balance":
            return httpx.Response(
                balance_status,
                json={
                    "is_available": balance_available,
                    "balance_infos": [],
                },
            )
        raise AssertionError(
            f"Unexpected path: {request.url.path}"
        )

    return httpx.MockTransport(handler)


def test_connect_stores_after_identity_probe() -> None:
    vault = InMemorySecretVault()
    service = EngineeringProviderConnectionService(
        vault,
        transport=_transport(),
    )

    status = service.connect_deepseek(
        "ds-secret-value",
    )

    assert status.state is ProviderConnectionState.CONNECTED
    assert status.verified is True
    assert status.billing_ready is True
    assert status.credentials_exposed is False

    stored = vault.get_json(
        "engineering:provider:deepseek:api-key"
    )
    assert stored is not None
    assert stored["api_key"] == "ds-secret-value"


def test_valid_key_is_persisted_when_balance_is_empty() -> None:
    vault = InMemorySecretVault()
    service = EngineeringProviderConnectionService(
        vault,
        transport=_transport(balance_available=False),
    )

    status = service.connect_deepseek("valid-key")

    assert status.state is ProviderConnectionState.DEGRADED
    assert status.verified is True
    assert status.billing_ready is False
    assert (
        vault.get_json(
            "engineering:provider:deepseek:api-key"
        )
        is not None
    )


def test_rejected_credential_is_not_persisted() -> None:
    vault = InMemorySecretVault()
    service = EngineeringProviderConnectionService(
        vault,
        transport=_transport(model_status=401),
    )

    with pytest.raises(EngineeringError) as captured:
        service.connect_deepseek("rejected-key")

    assert captured.value.code == (
        "ENGINEERING_PROVIDER_CREDENTIAL_REJECTED"
    )
    assert (
        vault.get_json(
            "engineering:provider:deepseek:api-key"
        )
        is None
    )


def test_status_is_disconnected_without_credential() -> None:
    service = EngineeringProviderConnectionService(
        InMemorySecretVault(),
        transport=_transport(),
    )

    status = service.deepseek_status()

    assert status.state is (
        ProviderConnectionState.DISCONNECTED
    )
    assert status.credential_present is False
    assert status.billing_ready is None


def test_status_reports_insufficient_balance() -> None:
    vault = InMemorySecretVault()
    vault.put_json(
        "engineering:provider:deepseek:api-key",
        {
            "api_key": "stored-key",
            "format_version": 1,
        },
    )
    service = EngineeringProviderConnectionService(
        vault,
        transport=_transport(balance_available=False),
    )

    status = service.deepseek_status()

    assert status.state is ProviderConnectionState.DEGRADED
    assert status.verified is True
    assert status.billing_ready is False
    assert "stored-key" not in status.model_dump_json()


def test_router_refuses_when_balance_is_empty() -> None:
    vault = InMemorySecretVault()
    vault.put_json(
        "engineering:provider:deepseek:api-key",
        {
            "api_key": "stored-key",
            "format_version": 1,
        },
    )
    service = EngineeringProviderConnectionService(
        vault,
        transport=_transport(balance_available=False),
    )

    with pytest.raises(EngineeringError) as captured:
        service.build_deepseek_router()

    assert captured.value.code == (
        "ENGINEERING_PROVIDER_INSUFFICIENT_BALANCE"
    )


def test_legacy_deepseek_model_alias_is_rejected() -> None:
    with pytest.raises(EngineeringError) as captured:
        EngineeringProviderConnectionService.deepseek_profile(
            "deepseek-chat"
        )

    assert captured.value.code == (
        "ENGINEERING_PROVIDER_MODEL_UNSUPPORTED"
    )


def test_disconnect_removes_key_and_configuration() -> None:
    vault = InMemorySecretVault()
    service = EngineeringProviderConnectionService(
        vault,
        transport=_transport(),
    )
    service.connect_deepseek("valid-key")

    service.disconnect_deepseek()

    assert (
        vault.get_json(
            "engineering:provider:deepseek:api-key"
        )
        is None
    )
    assert (
        vault.get_json(
            "engineering:provider:deepseek:configuration"
        )
        is None
    )


def test_router_never_exposes_key() -> None:
    vault = InMemorySecretVault()
    service = EngineeringProviderConnectionService(
        vault,
        transport=_transport(),
    )
    service.connect_deepseek("valid-key")

    router = service.build_deepseek_router()
    profile = router.profile("deepseek")

    assert "valid-key" not in repr(router)
    assert "valid-key" not in json.dumps(
        profile.model_dump(mode="json")
    )
