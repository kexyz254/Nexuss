from __future__ import annotations

import httpx

from nexuss.connectors.vault import InMemorySecretVault
from nexuss.engineering.provider_connections import (
    EngineeringProviderConnectionService,
    ProviderAccessCode,
)


class MutableDeepSeekTransport(httpx.BaseTransport):
    def __init__(
        self,
        *,
        balance_available: bool,
    ) -> None:
        self.balance_available = balance_available

    def handle_request(
        self,
        request: httpx.Request,
    ) -> httpx.Response:
        if request.url.path == "/models":
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [
                        {
                            "id": "deepseek-v4-pro",
                            "object": "model",
                            "owned_by": "deepseek",
                        }
                    ],
                },
            )
        if request.url.path == "/user/balance":
            return httpx.Response(
                200,
                json={
                    "is_available": self.balance_available,
                    "balance_infos": [],
                },
            )
        raise AssertionError(request.url.path)


def test_unpaid_provider_is_optional_and_safe() -> None:
    vault = InMemorySecretVault()
    transport = MutableDeepSeekTransport(
        balance_available=False
    )
    service = EngineeringProviderConnectionService(
        vault,
        transport=transport,
    )
    service.connect_deepseek("valid-key")

    access = service.deepseek_access()

    assert access.available is False
    assert access.optional is True
    assert access.code is (
        ProviderAccessCode.INSUFFICIENT_BALANCE
    )
    assert "Pay for DeepSeek API access" in (
        access.user_message
    )
    assert "no reconnection is required" in (
        access.user_message
    )
    assert "valid-key" not in access.model_dump_json()


def test_funded_provider_activates_without_reconnect() -> None:
    vault = InMemorySecretVault()
    transport = MutableDeepSeekTransport(
        balance_available=False
    )
    service = EngineeringProviderConnectionService(
        vault,
        transport=transport,
    )
    service.connect_deepseek("valid-key")

    before = service.deepseek_access()
    transport.balance_available = True
    after = service.deepseek_access()

    assert before.available is False
    assert before.code is (
        ProviderAccessCode.INSUFFICIENT_BALANCE
    )
    assert after.available is True
    assert after.code is ProviderAccessCode.READY

    # The original encrypted credential remains the one used.
    stored = vault.get_json(
        "engineering:provider:deepseek:api-key"
    )
    assert stored is not None
    assert stored["api_key"] == "valid-key"


def test_no_key_does_not_break_nexuss() -> None:
    service = EngineeringProviderConnectionService(
        InMemorySecretVault(),
        transport=MutableDeepSeekTransport(
            balance_available=True
        ),
    )

    access = service.deepseek_access()

    assert access.available is False
    assert access.optional is True
    assert access.code is ProviderAccessCode.NOT_CONNECTED
    assert "Nexuss remains available" in (
        access.user_message
    )


def test_temporary_outage_is_not_reported_as_system_failure() -> None:
    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        return httpx.Response(503, json={})

    vault = InMemorySecretVault()
    vault.put_json(
        "engineering:provider:deepseek:api-key",
        {
            "api_key": "valid-key",
            "format_version": 1,
        },
    )
    service = EngineeringProviderConnectionService(
        vault,
        transport=httpx.MockTransport(handler),
    )

    access = service.deepseek_access()

    assert access.available is False
    assert access.optional is True
    assert access.code is (
        ProviderAccessCode.TEMPORARILY_UNAVAILABLE
    )
    assert "Nexuss remains operational" in (
        access.user_message
    )
