"""GitHub App OAuth device flow and token refresh."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from pydantic import SecretStr

from nexuss.connectors.errors import ConnectorError
from nexuss.connectors.github.models import (
    DeviceAuthorizationSecret,
    DevicePollResult,
    GitHubConnectState,
    OAuthTokenBundle,
)


class GitHubDeviceFlowClient:
    device_code_url = "https://github.com/login/device/code"
    token_url = "https://github.com/login/oauth/access_token"

    def __init__(
        self,
        *,
        timeout_seconds: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    def begin(self, client_id: str, *, now: datetime | None = None) -> DeviceAuthorizationSecret:
        checked_at = now or datetime.now(UTC)
        response = self._post(self.device_code_url, {"client_id": client_id})
        try:
            return DeviceAuthorizationSecret(
                device_code=SecretStr(str(response["device_code"])),
                user_code=str(response["user_code"]),
                verification_uri=str(response["verification_uri"]),
                expires_at=checked_at + timedelta(seconds=int(response["expires_in"])),
                interval_seconds=int(response.get("interval", 5)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ConnectorError(
                "GITHUB_DEVICE_FLOW_RESPONSE_INVALID",
                "GitHub returned an invalid device-flow response.",
            ) from exc

    def poll(
        self,
        client_id: str,
        device_code: str,
        *,
        interval_seconds: int,
        now: datetime | None = None,
    ) -> DevicePollResult:
        checked_at = now or datetime.now(UTC)
        response = self._post(
            self.token_url,
            {
                "client_id": client_id,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
        )
        error = str(response.get("error", "")).strip()
        if error:
            return self._poll_error(error, interval_seconds)
        return DevicePollResult(
            state=GitHubConnectState.CONNECTED,
            token=self._token_from_response(response, checked_at),
        )

    def refresh(
        self,
        client_id: str,
        refresh_token: str,
        *,
        now: datetime | None = None,
    ) -> OAuthTokenBundle:
        checked_at = now or datetime.now(UTC)
        response = self._post(
            self.token_url,
            {
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
        if str(response.get("error", "")).strip():
            raise ConnectorError(
                "GITHUB_REAUTH_REQUIRED",
                "The GitHub refresh token is no longer usable.",
            )
        return self._token_from_response(response, checked_at)

    def _post(self, url: str, data: dict[str, str]) -> dict[str, object]:
        try:
            with httpx.Client(
                timeout=self._timeout_seconds,
                transport=self._transport,
                headers={"Accept": "application/json", "User-Agent": "Nexuss-GitHub-Connector/1.0"},
            ) as client:
                response = client.post(url, data=data)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ConnectorError(
                "GITHUB_AUTH_SERVICE_UNAVAILABLE",
                "GitHub authorization is unavailable.",
                retryable=True,
            ) from exc
        if not isinstance(payload, dict):
            raise ConnectorError(
                "GITHUB_DEVICE_FLOW_RESPONSE_INVALID",
                "GitHub returned a non-object authorization response.",
            )
        return payload

    @staticmethod
    def _poll_error(error: str, interval_seconds: int) -> DevicePollResult:
        if error == "authorization_pending":
            return DevicePollResult(
                state=GitHubConnectState.PENDING,
                retry_after_seconds=interval_seconds,
            )
        if error == "slow_down":
            return DevicePollResult(
                state=GitHubConnectState.SLOW_DOWN,
                retry_after_seconds=interval_seconds + 5,
            )
        if error == "access_denied":
            return DevicePollResult(state=GitHubConnectState.DENIED)
        if error in {"expired_token", "incorrect_device_code", "bad_verification_code"}:
            return DevicePollResult(state=GitHubConnectState.EXPIRED)
        raise ConnectorError(
            "GITHUB_DEVICE_FLOW_FAILED",
            "GitHub rejected the device authorization.",
            safe_details={"github_error": error},
        )

    @staticmethod
    def _token_from_response(response: dict[str, object], now: datetime) -> OAuthTokenBundle:
        access_token = str(response.get("access_token", "")).strip()
        if not access_token:
            raise ConnectorError(
                "GITHUB_TOKEN_RESPONSE_INVALID",
                "GitHub did not return an access token.",
            )
        expires_in = response.get("expires_in")
        refresh_expires_in = response.get("refresh_token_expires_in")
        refresh_value = str(response.get("refresh_token") or "").strip()
        return OAuthTokenBundle(
            access_token=SecretStr(access_token),
            token_type=str(response.get("token_type", "bearer")),
            access_token_expires_at=(
                now + timedelta(seconds=int(expires_in)) if expires_in is not None else None
            ),
            refresh_token=SecretStr(refresh_value) if refresh_value else None,
            refresh_token_expires_at=(
                now + timedelta(seconds=int(refresh_expires_in))
                if refresh_expires_in is not None
                else None
            ),
        )
