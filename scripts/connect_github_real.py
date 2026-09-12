from __future__ import annotations

import os
import time
import webbrowser
from datetime import UTC, datetime

from nexuss.connectors.github import (
    GitHubConnectorService,
    GitHubConnectState,
)
from nexuss.connectors.vault import DpapiSecretVault

client_id = os.environ.get(
    "NEXUSS_GITHUB_CLIENT_ID",
    "",
).strip()

if not client_id:
    raise SystemExit(
        "NEXUSS_GITHUB_CLIENT_ID is not configured."
    )

service = GitHubConnectorService(
    vault=DpapiSecretVault(),
)

challenge = service.begin_connection(
    client_id,
    now=datetime.now(UTC),
)

print()
print("=" * 68)
print("NEXUSS GITHUB AUTHORIZATION")
print("=" * 68)
print(f"Verification page: {challenge.verification_uri}")
print(f"One-time code:     {challenge.user_code}")
print(f"Expires at:        {challenge.expires_at}")
print()
print(
    "Complete sign-in and 2FA directly on GitHub. "
    "Nexuss never receives those credentials."
)

webbrowser.open(str(challenge.verification_uri))

interval = challenge.poll_interval_seconds

while True:
    time.sleep(interval)

    result = service.poll_connection(
        challenge.flow_id,
        now=datetime.now(UTC),
    )

    if result.state is GitHubConnectState.PENDING:
        continue

    if result.state is GitHubConnectState.SLOW_DOWN:
        interval = (
            result.retry_after_seconds
            or interval + 5
        )
        continue

    if result.state is GitHubConnectState.DENIED:
        raise SystemExit(
            "GitHub authorization was denied."
        )

    if result.state is GitHubConnectState.EXPIRED:
        raise SystemExit(
            "GitHub authorization expired. Run again."
        )

    if result.profile is None:
        raise SystemExit(
            "GitHub connected without a verified profile."
        )

    account = result.profile.account

    print()
    print("CONNECTED AND VERIFIED")
    print(f"Account:      {account.login}")
    print(f"Account ID:   {account.account_id}")
    print(f"Account type: {account.account_type}")
    print("Token vault:  Windows DPAPI")
    print("Password:     Never handled")
    print("2FA:          Never handled")
    break
