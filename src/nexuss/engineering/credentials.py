"""Encrypted provider credential storage."""

from __future__ import annotations

from typing import Protocol

from pydantic import SecretStr

from nexuss.engineering.errors import EngineeringError


class SecretVault(Protocol):
    def put_json(self, secret_id: str, payload: dict[str, object]) -> None: ...

    def get_json(self, secret_id: str) -> dict[str, object] | None: ...

    def delete(self, secret_id: str) -> None: ...


class ProviderCredentialStore:
    def __init__(self, vault: SecretVault) -> None:
        self._vault = vault

    @staticmethod
    def _secret_id(provider_id: str) -> str:
        return f"engineering:provider:{provider_id}:api-key"

    def put_api_key(self, provider_id: str, api_key: str) -> None:
        normalized = api_key.strip()
        if not normalized:
            raise EngineeringError(
                "ENGINEERING_API_KEY_EMPTY",
                "The provider API key is empty.",
            )
        self._vault.put_json(
            self._secret_id(provider_id),
            {"api_key": normalized, "format_version": 1},
        )

    def get_api_key(self, provider_id: str) -> SecretStr:
        payload = self._vault.get_json(self._secret_id(provider_id))
        if payload is None:
            raise EngineeringError(
                "ENGINEERING_PROVIDER_NOT_CONNECTED",
                "The requested model provider is not connected.",
            )
        value = str(payload.get("api_key", "")).strip()
        if not value:
            raise EngineeringError(
                "ENGINEERING_PROVIDER_CREDENTIAL_INVALID",
                "The encrypted provider credential is invalid.",
            )
        return SecretStr(value)

    def delete(self, provider_id: str) -> None:
        self._vault.delete(self._secret_id(provider_id))
