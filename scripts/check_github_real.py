from __future__ import annotations

from nexuss.connectors.github import (
    GitHubConnectorService,
)
from nexuss.connectors.vault import DpapiSecretVault

service = GitHubConnectorService(
    vault=DpapiSecretVault(),
)

health = service.health()

print()
print("=" * 68)
print("NEXUSS GITHUB CONNECTOR")
print("=" * 68)
print(f"Status:     {health.status.value}")
print(f"Configured: {health.configured}")
print(f"Detail:     {health.detail}")

if health.identity is None:
    raise SystemExit(
        "No verified GitHub identity is available."
    )

print(f"Account:    {health.identity.account_label}")
print(f"Verified:   {health.identity.verified}")

inventory = service.list_repositories()

print()
print("REPOSITORY INVENTORY")
print(f"Total:     {inventory.total}")
print(f"Private:   {inventory.private_count}")
print(f"Public:    {inventory.public_count}")
print(f"Archived:  {inventory.archived_count}")
print(f"Disabled:  {inventory.disabled_count}")
print(f"Forks:     {inventory.fork_count}")

print()
print("RECENT REPOSITORIES")
for repository in inventory.repositories[:15]:
    visibility = (
        "private"
        if repository.private
        else "public"
    )
    print(
        f"- {repository.full_name} "
        f"[{visibility}]"
    )
