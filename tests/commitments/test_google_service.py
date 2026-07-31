from datetime import UTC, datetime, timedelta

import httpx
from pydantic import SecretStr

from nexuss.connectors.google_workspace.models import GoogleOAuthTokenBundle
from nexuss.connectors.google_workspace.oauth import GOOGLE_READ_ONLY_SCOPES
from nexuss.connectors.google_workspace.service import (
    GoogleWorkspaceConnectorService,
)
from nexuss.connectors.vault import InMemorySecretVault


def test_service_stores_verified_identity_without_exposing_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/profile")
        return httpx.Response(
            200,
            json={"emailAddress": "owner@example.com"},
        )

    service = GoogleWorkspaceConnectorService(
        vault=InMemorySecretVault(),
        api_transport=httpx.MockTransport(handler),
    )
    service.connect(
        client_id="client",
        client_secret="secret",
        token=GoogleOAuthTokenBundle(
            access_token=SecretStr("access"),
            refresh_token=SecretStr("refresh"),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            scopes=GOOGLE_READ_ONLY_SCOPES,
        ),
    )
    health = service.health()
    assert health.connected is True
    assert health.account_email == "owner@example.com"
    assert health.external_write_authority_added is False
    assert health.credentials_exposed is False
