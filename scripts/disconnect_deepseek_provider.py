from __future__ import annotations

from nexuss.connectors.vault import DpapiSecretVault
from nexuss.engineering.provider_connections import (
    EngineeringProviderConnectionService,
)


def main() -> int:
    service = EngineeringProviderConnectionService(
        DpapiSecretVault()
    )
    service.disconnect_deepseek()

    print("DeepSeek engineering provider disconnected.")
    print("Encrypted credential and provider configuration removed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
