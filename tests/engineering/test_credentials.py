from __future__ import annotations

from nexuss.engineering.credentials import ProviderCredentialStore


class FakeVault:
    def __init__(self) -> None:
        self.items: dict[str, dict[str, object]] = {}

    def put_json(self, secret_id: str, payload: dict[str, object]) -> None:
        self.items[secret_id] = dict(payload)

    def get_json(self, secret_id: str) -> dict[str, object] | None:
        value = self.items.get(secret_id)
        return dict(value) if value is not None else None

    def delete(self, secret_id: str) -> None:
        self.items.pop(secret_id, None)


def test_provider_key_is_secret_wrapped_and_deletable() -> None:
    vault = FakeVault()
    store = ProviderCredentialStore(vault)
    store.put_api_key("deepseek-main", "sk-secret")

    secret = store.get_api_key("deepseek-main")
    assert "sk-secret" not in repr(secret)
    assert secret.get_secret_value() == "sk-secret"

    store.delete("deepseek-main")
    assert "engineering:provider:deepseek-main:api-key" not in vault.items
