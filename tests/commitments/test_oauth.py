from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import httpx

from nexuss.connectors.google_workspace.oauth import (
    GOOGLE_READ_ONLY_SCOPES,
    GoogleOAuthClient,
    build_authorization_url,
    generate_pkce_pair,
)


def test_authorization_url_is_pkce_and_read_only() -> None:
    verifier, challenge = generate_pkce_pair()
    assert len(verifier) >= 43
    url = build_authorization_url(
        client_id="client",
        redirect_uri="http://127.0.0.1:8765/callback",
        state="state",
        code_challenge=challenge,
    )
    query = parse_qs(urlparse(url).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["access_type"] == ["offline"]
    assert set(query["scope"][0].split()) == set(GOOGLE_READ_ONLY_SCOPES)


def test_code_exchange_returns_token_bundle() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_in": 3600,
                "scope": " ".join(GOOGLE_READ_ONLY_SCOPES),
                "token_type": "Bearer",
            },
        )
    )
    bundle = GoogleOAuthClient(transport=transport).exchange_code(
        client_id="client",
        client_secret="secret",
        code="code",
        code_verifier="verifier",
        redirect_uri="http://127.0.0.1/callback",
        now=datetime(2026, 7, 31, tzinfo=UTC),
    )
    assert bundle.access_token.get_secret_value() == "access"
    assert bundle.refresh_token is not None

def test_code_exchange_normalizes_google_identity_scope_aliases() -> None:
    returned_scopes = (
        "openid "
        "https://www.googleapis.com/auth/userinfo.email "
        "https://www.googleapis.com/auth/userinfo.profile "
        "https://www.googleapis.com/auth/gmail.readonly "
        "https://www.googleapis.com/auth/calendar.calendarlist.readonly "
        "https://www.googleapis.com/auth/calendar.events.readonly "
        "https://www.googleapis.com/auth/contacts.readonly"
    )

    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_in": 3600,
                "scope": returned_scopes,
                "token_type": "Bearer",
            },
        )
    )

    bundle = GoogleOAuthClient(transport=transport).exchange_code(
        client_id="client",
        client_secret="secret",
        code="code",
        code_verifier="verifier",
        redirect_uri="http://127.0.0.1/callback",
        now=datetime(2026, 7, 31, tzinfo=UTC),
    )

    assert set(bundle.scopes) == set(GOOGLE_READ_ONLY_SCOPES)
