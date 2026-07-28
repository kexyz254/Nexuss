from __future__ import annotations

import argparse
import getpass

from nexuss.connectors.vault import DpapiSecretVault
from nexuss.engineering.errors import EngineeringError
from nexuss.engineering.provider_connections import (
    EngineeringProviderConnectionService,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Connect DeepSeek to the current Windows user "
            "through the Nexuss DPAPI vault."
        )
    )
    parser.add_argument(
        "--model",
        choices=(
            "deepseek-v4-pro",
            "deepseek-v4-flash",
        ),
        default="deepseek-v4-pro",
    )
    args = parser.parse_args()

    api_key = getpass.getpass(
        "DeepSeek API key (hidden): "
    )
    service = EngineeringProviderConnectionService(
        DpapiSecretVault()
    )

    try:
        status = service.connect_deepseek(
            api_key,
            model=args.model,
        )
    except EngineeringError as exc:
        print()
        print(f"FAILED: {exc.code}")
        print(exc.message)
        return 1
    finally:
        api_key = ""

    print()
    print("=" * 68)
    print("NEXUSS ENGINEERING PROVIDER")
    print("=" * 68)
    print(f"Provider:    {status.provider_id}")
    print(f"State:       {status.state.value}")
    print(f"Verified:    {status.verified}")
    print(f"Model:       {status.model}")
    print(f"API base:    {status.api_base}")
    print(f"Models seen: {len(status.available_models)}")
    print("Credential:  Windows DPAPI encrypted")
    print("Key exposed: False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
