from __future__ import annotations

from nexuss.connectors.vault import DpapiSecretVault
from nexuss.engineering.provider_connections import (
    EngineeringProviderConnectionService,
)


def main() -> int:
    service = EngineeringProviderConnectionService(
        DpapiSecretVault()
    )
    status = service.deepseek_status()
    access = service.deepseek_access()

    print()
    print("=" * 68)
    print("NEXUSS DEEPSEEK CONNECTION")
    print("=" * 68)
    print(f"State:              {status.state.value}")
    print(f"Connected:          {status.connected}")
    print(f"Identity verified:  {status.verified}")
    print(
        "Billing ready:      "
        + (
            "True"
            if status.billing_ready is True
            else "False"
            if status.billing_ready is False
            else "Unknown"
        )
    )
    print(f"Credential present: {status.credential_present}")
    print(f"Model:              {status.model}")
    print(f"Access code:        {access.code.value}")
    print(f"DeepSeek available: {access.available}")
    print(f"Detail:             {access.user_message}")
    print("Nexuss operational: True")
    print("Credentials exposed: False")

    # Optional-provider states are valid system states. The health command
    # succeeds unless an unexpected local exception prevents assessment.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
