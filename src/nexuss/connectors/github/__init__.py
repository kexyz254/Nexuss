"""GitHub connector for verified developer automation."""

from nexuss.connectors.github.client import GitHubApiClient
from nexuss.connectors.github.device_flow import GitHubDeviceFlowClient
from nexuss.connectors.github.models import (
    GitHubAccount,
    GitHubConnectChallenge,
    GitHubConnectionProfile,
    GitHubConnectResult,
    GitHubConnectState,
    GitHubRepository,
    GitHubRepositoryInventory,
    OAuthTokenBundle,
    PreparedRepositoryCreate,
    RepositoryCreateApproval,
    VerifiedRepositoryCreate,
)
from nexuss.connectors.github.service import GitHubConnectorService

__all__ = [
    "GitHubAccount",
    "GitHubApiClient",
    "GitHubConnectChallenge",
    "GitHubConnectResult",
    "GitHubConnectState",
    "GitHubConnectionProfile",
    "GitHubConnectorService",
    "GitHubDeviceFlowClient",
    "GitHubRepository",
    "GitHubRepositoryInventory",
    "OAuthTokenBundle",
    "PreparedRepositoryCreate",
    "RepositoryCreateApproval",
    "VerifiedRepositoryCreate",
]
