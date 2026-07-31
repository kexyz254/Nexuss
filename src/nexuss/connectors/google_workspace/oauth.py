"""Google desktop OAuth 2.0 authorization-code flow with PKCE."""
from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from pydantic import SecretStr

from nexuss.connectors.errors import ConnectorError
from nexuss.connectors.google_workspace.models import GoogleOAuthTokenBundle

GOOGLE_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_READ_ONLY_SCOPES = (
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
    "https://www.googleapis.com/auth/calendar.events.readonly",
    "https://www.googleapis.com/auth/contacts.readonly",
)

_GOOGLE_SCOPE_ALIASES = {
    "https://www.googleapis.com/auth/userinfo.email": "email",
    "https://www.googleapis.com/auth/userinfo.profile": "profile",
}


def normalize_google_scopes(
    scopes: tuple[str, ...] | list[str],
) -> tuple[str, ...]:
    """Normalize equivalent Google identity scope names."""
    return tuple(
        dict.fromkeys(
            _GOOGLE_SCOPE_ALIASES.get(scope, scope)
            for scope in scopes
        )
    )

def generate_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge

def build_authorization_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    scopes: tuple[str, ...] = GOOGLE_READ_ONLY_SCOPES,
) -> str:
    query = urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    })
    return f"{GOOGLE_AUTHORIZATION_URL}?{query}"

class GoogleOAuthClient:
    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._transport = transport
        self._timeout = timeout_seconds

    def exchange_code(
        self,
        *,
        client_id: str,
        client_secret: str | None,
        code: str,
        code_verifier: str,
        redirect_uri: str,
        scopes: tuple[str, ...] = GOOGLE_READ_ONLY_SCOPES,
        now: datetime | None = None,
    ) -> GoogleOAuthTokenBundle:
        payload = {
            "client_id": client_id,
            "code": code,
            "code_verifier": code_verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
        if client_secret:
            payload["client_secret"] = client_secret
        return self._bundle(self._post(payload), scopes=scopes, now=now)

    def refresh(
        self,
        *,
        client_id: str,
        client_secret: str | None,
        refresh_token: str,
        scopes: tuple[str, ...],
        now: datetime | None = None,
    ) -> GoogleOAuthTokenBundle:
        payload = {
            "client_id": client_id,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        if client_secret:
            payload["client_secret"] = client_secret
        response = self._post(payload)
        response.setdefault("refresh_token", refresh_token)
        return self._bundle(response, scopes=scopes, now=now)

    def _post(self, payload: dict[str, str]) -> dict[str, object]:
        try:
            with httpx.Client(
                transport=self._transport,
                timeout=self._timeout,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "Nexuss-Google-Workspace/1.0",
                },
            ) as client:
                response = client.post(GOOGLE_TOKEN_URL, data=payload)
                response.raise_for_status()
                result = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ConnectorError(
                "GOOGLE_OAUTH_UNAVAILABLE",
                "Google authorization could not complete.",
                retryable=True,
            ) from exc
        if not isinstance(result, dict):
            raise ConnectorError(
                "GOOGLE_OAUTH_RESPONSE_INVALID",
                "Google returned an invalid authorization response.",
            )
        if result.get("error"):
            raise ConnectorError(
                "GOOGLE_OAUTH_REJECTED",
                "Google rejected the authorization request.",
                safe_details={"google_error": str(result.get("error"))},
            )
        return result

    @staticmethod
    def _bundle(
        response: dict[str, object],
        *,
        scopes: tuple[str, ...],
        now: datetime | None,
    ) -> GoogleOAuthTokenBundle:
        access_token = str(response.get("access_token", "")).strip()
        if not access_token:
            raise ConnectorError(
                "GOOGLE_TOKEN_RESPONSE_INVALID",
                "Google did not return an access token.",
            )
        checked_at = now or datetime.now(UTC)
        refresh_value = str(response.get("refresh_token") or "").strip()
        response_scope = str(response.get("scope") or "").split()
        return GoogleOAuthTokenBundle(
            access_token=SecretStr(access_token),
            refresh_token=SecretStr(refresh_value) if refresh_value else None,
            token_type=str(response.get("token_type", "Bearer")),
            expires_at=checked_at + timedelta(
                seconds=int(response.get("expires_in", 3600))
            ),
            scopes=normalize_google_scopes(response_scope or scopes),
        )
