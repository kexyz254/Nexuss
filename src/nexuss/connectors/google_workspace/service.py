"""Encrypted, read-only Google Workspace connector service."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from nexuss.connectors.errors import ConnectorError
from nexuss.connectors.google_workspace.client import GoogleWorkspaceApiClient
from nexuss.connectors.google_workspace.models import (
    GoogleOAuthTokenBundle,
    GoogleWorkspaceHealth,
    GoogleWorkspaceProfile,
    GoogleWorkspaceSnapshot,
)
from nexuss.connectors.google_workspace.oauth import (
    GOOGLE_READ_ONLY_SCOPES,
    GoogleOAuthClient,
)
from nexuss.connectors.vault import DpapiSecretVault, SecretVault


class GoogleWorkspaceConnectorService:
    _CLIENT_ID = "google-workspace:oauth-client"
    _TOKEN_ID = "google-workspace:oauth-token"
    _PROFILE_ID = "google-workspace:profile"

    def __init__(
        self,
        *,
        vault: SecretVault | None,
        oauth: GoogleOAuthClient | None = None,
        api_transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._vault = vault
        self._oauth = oauth or GoogleOAuthClient()
        self._api_transport = api_transport

    @classmethod
    def from_environment(cls) -> GoogleWorkspaceConnectorService:
        try:
            vault: SecretVault | None = DpapiSecretVault()
        except ConnectorError:
            vault = None
        return cls(vault=vault)

    @property
    def connected(self) -> bool:
        return (
            self._vault is not None
            and self._vault.exists(self._TOKEN_ID)
            and self._vault.exists(self._PROFILE_ID)
            and self._vault.exists(self._CLIENT_ID)
        )

    def connect(
        self,
        *,
        client_id: str,
        client_secret: str | None,
        token: GoogleOAuthTokenBundle,
    ) -> GoogleWorkspaceProfile:
        vault = self._require_vault()
        missing = set(GOOGLE_READ_ONLY_SCOPES) - set(token.scopes)
        if missing:
            raise ConnectorError(
                "GOOGLE_REQUIRED_SCOPE_MISSING",
                "Google did not grant every required read-only scope.",
                safe_details={"missing_scopes": sorted(missing)},
            )
        client = GoogleWorkspaceApiClient(
            token.access_token.get_secret_value(),
            transport=self._api_transport,
        )
        profile_payload = client.gmail_profile()
        email = str(profile_payload.get("emailAddress", "")).strip()
        if not email:
            raise ConnectorError(
                "GOOGLE_PROFILE_INVALID",
                "Google did not return the connected Gmail identity.",
            )
        profile = GoogleWorkspaceProfile(
            email=email,
            granted_scopes=token.scopes,
        )
        vault.put_json(
            self._CLIENT_ID,
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "format_version": 1,
            },
        )
        vault.put_json(self._TOKEN_ID, token.to_vault_payload())
        vault.put_json(self._PROFILE_ID, profile.model_dump(mode="json"))
        return profile

    def disconnect(self) -> None:
        vault = self._require_vault()
        vault.delete(self._TOKEN_ID)
        vault.delete(self._PROFILE_ID)
        vault.delete(self._CLIENT_ID)

    def health(self) -> GoogleWorkspaceHealth:
        if not self.connected:
            return GoogleWorkspaceHealth(
                connected=False,
                encrypted_storage=(
                    "windows_dpapi" if self._vault is not None else "unavailable"
                ),
            )
        profile = self._profile()
        scopes = set(profile.granted_scopes)
        return GoogleWorkspaceHealth(
            connected=True,
            account_email=profile.email,
            gmail_read="https://www.googleapis.com/auth/gmail.readonly" in scopes,
            calendar_read=(
                "https://www.googleapis.com/auth/calendar.events.readonly"
                in scopes
            ),
            contacts_read=(
                "https://www.googleapis.com/auth/contacts.readonly" in scopes
            ),
            encrypted_storage="windows_dpapi",
        )

    def snapshot(
        self,
        *,
        time_min: datetime,
        time_max: datetime,
        gmail_query: str = "newer_than:14d",
    ) -> GoogleWorkspaceSnapshot:
        if time_min.tzinfo is None or time_max.tzinfo is None:
            raise ValueError("snapshot times must be timezone-aware")
        if time_max <= time_min:
            raise ValueError("time_max must follow time_min")
        client = self._authenticated_client()
        calendars = client.list_calendars()
        return GoogleWorkspaceSnapshot(
            profile=self._profile(),
            messages=client.list_messages(query=gmail_query),
            calendars=calendars,
            events=client.list_events(
                calendars,
                time_min=time_min,
                time_max=time_max,
            ),
            contacts=client.list_contacts(),
        )

    def _authenticated_client(
        self,
        *,
        now: datetime | None = None,
    ) -> GoogleWorkspaceApiClient:
        checked_at = now or datetime.now(UTC)
        token = self._token()
        if token.expires_at <= checked_at + timedelta(seconds=90):
            token = self._refresh(token, now=checked_at)
        return GoogleWorkspaceApiClient(
            token.access_token.get_secret_value(),
            transport=self._api_transport,
        )

    def _refresh(
        self,
        token: GoogleOAuthTokenBundle,
        *,
        now: datetime,
    ) -> GoogleOAuthTokenBundle:
        if token.refresh_token is None:
            raise ConnectorError(
                "GOOGLE_REAUTH_REQUIRED",
                "The Google authorization cannot be refreshed.",
            )
        client_record = self._client_record()
        refreshed = self._oauth.refresh(
            client_id=str(client_record["client_id"]),
            client_secret=(
                str(client_record.get("client_secret"))
                if client_record.get("client_secret")
                else None
            ),
            refresh_token=token.refresh_token.get_secret_value(),
            scopes=token.scopes,
            now=now,
        )
        self._require_vault().put_json(
            self._TOKEN_ID,
            refreshed.to_vault_payload(),
        )
        return refreshed

    def _profile(self) -> GoogleWorkspaceProfile:
        payload = self._require_vault().get_json(self._PROFILE_ID)
        if payload is None:
            raise ConnectorError(
                "GOOGLE_WORKSPACE_NOT_CONNECTED",
                "Google Workspace is not connected.",
            )
        try:
            return GoogleWorkspaceProfile.model_validate(payload)
        except ValueError as exc:
            raise ConnectorError(
                "GOOGLE_PROFILE_RECORD_INVALID",
                "The encrypted Google profile is invalid.",
            ) from exc

    def _token(self) -> GoogleOAuthTokenBundle:
        payload = self._require_vault().get_json(self._TOKEN_ID)
        if payload is None:
            raise ConnectorError(
                "GOOGLE_WORKSPACE_NOT_CONNECTED",
                "Google Workspace is not connected.",
            )
        try:
            return GoogleOAuthTokenBundle.from_vault_payload(payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise ConnectorError(
                "GOOGLE_TOKEN_RECORD_INVALID",
                "The encrypted Google token record is invalid.",
            ) from exc

    def _client_record(self) -> dict[str, object]:
        payload = self._require_vault().get_json(self._CLIENT_ID)
        if payload is None or not str(payload.get("client_id", "")).strip():
            raise ConnectorError(
                "GOOGLE_CLIENT_RECORD_INVALID",
                "The encrypted Google OAuth client record is invalid.",
            )
        return payload

    def _require_vault(self) -> SecretVault:
        if self._vault is None:
            raise ConnectorError(
                "GOOGLE_SECRET_STORAGE_UNAVAILABLE",
                "Windows DPAPI secret storage is unavailable.",
            )
        return self._vault
