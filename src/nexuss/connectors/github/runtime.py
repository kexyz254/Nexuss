"""Process-local access to the encrypted GitHub connector."""

from __future__ import annotations

from functools import lru_cache

from nexuss.connectors.github.service import GitHubConnectorService
from nexuss.connectors.vault import DpapiSecretVault


@lru_cache(maxsize=1)
def get_github_connector() -> GitHubConnectorService:
    return GitHubConnectorService(vault=DpapiSecretVault())
