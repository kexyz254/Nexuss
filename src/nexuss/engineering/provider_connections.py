"""Encrypted, optional model-provider connections for Nexuss engineering."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from nexuss.engineering.credentials import ProviderCredentialStore, SecretVault
from nexuss.engineering.errors import EngineeringError
from nexuss.engineering.models import ProviderKind
from nexuss.engineering.policy import ProviderProfile
from nexuss.engineering.providers.openai_compatible import (
    OpenAICompatibleProvider,
)
from nexuss.engineering.router import EngineeringProviderRouter

_DEEPSEEK_PROVIDER_ID = "deepseek"
_DEEPSEEK_API_BASE = "https://api.deepseek.com"
_DEEPSEEK_DEFAULT_MODEL = "deepseek-v4-pro"
_DEEPSEEK_MODELS = frozenset(
    {
        "deepseek-v4-pro",
        "deepseek-v4-flash",
    }
)
_DEEPSEEK_CONFIGURATION_ID = (
    "engineering:provider:deepseek:configuration"
)


class ProviderConnectionState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    DEGRADED = "degraded"


class ProviderAccessCode(StrEnum):
    READY = "ready"
    NOT_CONNECTED = "not_connected"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    REAUTHENTICATION_REQUIRED = "reauthentication_required"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"


class ProviderConnectionStatus(BaseModel):
    """Credential-free provider connection evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: str
    provider_kind: ProviderKind
    state: ProviderConnectionState
    connected: bool
    verified: bool
    credential_present: bool
    model: str
    api_base: str
    available_models: tuple[str, ...] = ()
    billing_ready: bool | None = None
    failure_code: str | None = None
    detail: str
    credentials_exposed: bool = False
    checked_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )


class ProviderAccessDecision(BaseModel):
    """A safe capability-level decision, never a system-wide failure."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: str
    provider_kind: ProviderKind
    available: bool
    optional: bool = True
    code: ProviderAccessCode
    user_message: str
    recommended_action: str | None = None
    model: str
    identity_verified: bool
    billing_ready: bool | None
    credential_present: bool
    credentials_exposed: bool = False
    checked_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )


class EngineeringProviderConnectionService:
    """Manage encrypted engineering-provider credentials and probes."""

    def __init__(
        self,
        vault: SecretVault,
        *,
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._vault = vault
        self._credentials = ProviderCredentialStore(vault)
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    @staticmethod
    def deepseek_profile(
        model: str = _DEEPSEEK_DEFAULT_MODEL,
    ) -> ProviderProfile:
        normalized = model.strip()
        if normalized not in _DEEPSEEK_MODELS:
            raise EngineeringError(
                "ENGINEERING_PROVIDER_MODEL_UNSUPPORTED",
                "The requested DeepSeek model is not approved by "
                "the current Nexuss provider catalog.",
                safe_details={
                    "approved_models": sorted(_DEEPSEEK_MODELS)
                },
            )
        return ProviderProfile(
            provider_id=_DEEPSEEK_PROVIDER_ID,
            kind=ProviderKind.DEEPSEEK,
            model=normalized,
            api_base=_DEEPSEEK_API_BASE,
            external=True,
            enabled=True,
            max_output_tokens=16_000,
        )

    def connect_deepseek(
        self,
        api_key: str,
        *,
        model: str = _DEEPSEEK_DEFAULT_MODEL,
    ) -> ProviderConnectionStatus:
        normalized_key = api_key.strip()
        if not normalized_key:
            raise EngineeringError(
                "ENGINEERING_API_KEY_EMPTY",
                "The DeepSeek API key is empty.",
            )

        profile = self.deepseek_profile(model)
        secret = SecretStr(normalized_key)
        identity_status = self._probe_deepseek_identity(
            secret,
            profile,
        )

        # Persist after identity/model verification. An empty balance does not
        # invalidate the credential and must not force reconnection later.
        self._credentials.put_api_key(
            _DEEPSEEK_PROVIDER_ID,
            normalized_key,
        )
        self._vault.put_json(
            _DEEPSEEK_CONFIGURATION_ID,
            {
                "model": profile.model,
                "api_base": profile.api_base,
                "format_version": 1,
            },
        )
        return self._attach_billing_status(
            secret,
            profile,
            identity_status,
        )

    def deepseek_status(self) -> ProviderConnectionStatus:
        profile = self._configured_deepseek_profile()
        try:
            api_key = self._credentials.get_api_key(
                _DEEPSEEK_PROVIDER_ID
            )
        except EngineeringError as exc:
            if exc.code != "ENGINEERING_PROVIDER_NOT_CONNECTED":
                raise
            return ProviderConnectionStatus(
                provider_id=profile.provider_id,
                provider_kind=profile.kind,
                state=ProviderConnectionState.DISCONNECTED,
                connected=False,
                verified=False,
                credential_present=False,
                model=profile.model,
                api_base=profile.api_base,
                failure_code=(
                    "ENGINEERING_PROVIDER_NOT_CONNECTED"
                ),
                detail=(
                    "DeepSeek is optional and is not connected. "
                    "Nexuss remains operational."
                ),
            )

        try:
            identity_status = self._probe_deepseek_identity(
                api_key,
                profile,
            )
        except EngineeringError as exc:
            return ProviderConnectionStatus(
                provider_id=profile.provider_id,
                provider_kind=profile.kind,
                state=ProviderConnectionState.DEGRADED,
                connected=False,
                verified=False,
                credential_present=True,
                model=profile.model,
                api_base=profile.api_base,
                failure_code=exc.code,
                detail=(
                    "An encrypted DeepSeek credential exists, but "
                    f"the identity probe failed: {exc.code}."
                ),
            )

        return self._attach_billing_status(
            api_key,
            profile,
            identity_status,
        )

    def deepseek_access(self) -> ProviderAccessDecision:
        """Resolve DeepSeek availability on demand for every task."""

        status = self.deepseek_status()

        if (
            status.verified
            and status.billing_ready is True
        ):
            return ProviderAccessDecision(
                provider_id=status.provider_id,
                provider_kind=status.provider_kind,
                available=True,
                code=ProviderAccessCode.READY,
                user_message=(
                    "DeepSeek is connected and ready for "
                    "engineering work."
                ),
                model=status.model,
                identity_verified=True,
                billing_ready=True,
                credential_present=True,
            )

        if not status.credential_present:
            return ProviderAccessDecision(
                provider_id=status.provider_id,
                provider_kind=status.provider_kind,
                available=False,
                code=ProviderAccessCode.NOT_CONNECTED,
                user_message=(
                    "DeepSeek is not connected. Add a DeepSeek "
                    "API key to enable DeepSeek engineering access. "
                    "Nexuss remains available without it."
                ),
                recommended_action=(
                    "Connect a DeepSeek API key."
                ),
                model=status.model,
                identity_verified=False,
                billing_ready=None,
                credential_present=False,
            )

        if (
            status.verified
            and status.billing_ready is False
        ):
            return ProviderAccessDecision(
                provider_id=status.provider_id,
                provider_kind=status.provider_kind,
                available=False,
                code=(
                    ProviderAccessCode.INSUFFICIENT_BALANCE
                ),
                user_message=(
                    "Pay for DeepSeek API access by adding funds "
                    "to your DeepSeek API account. Nexuss will "
                    "detect the balance automatically on your next "
                    "DeepSeek task; no reconnection is required. "
                    "All other Nexuss capabilities remain available."
                ),
                recommended_action=(
                    "Add funds to the DeepSeek API account."
                ),
                model=status.model,
                identity_verified=True,
                billing_ready=False,
                credential_present=True,
            )

        if status.failure_code in {
            "ENGINEERING_PROVIDER_CREDENTIAL_REJECTED",
            "ENGINEERING_PROVIDER_MODEL_UNAVAILABLE",
        }:
            return ProviderAccessDecision(
                provider_id=status.provider_id,
                provider_kind=status.provider_kind,
                available=False,
                code=(
                    ProviderAccessCode.REAUTHENTICATION_REQUIRED
                ),
                user_message=(
                    "DeepSeek needs to be reconnected or its "
                    "configured model must be updated. Nexuss "
                    "remains available without DeepSeek."
                ),
                recommended_action=(
                    "Reconnect the DeepSeek provider."
                ),
                model=status.model,
                identity_verified=False,
                billing_ready=status.billing_ready,
                credential_present=True,
            )

        return ProviderAccessDecision(
            provider_id=status.provider_id,
            provider_kind=status.provider_kind,
            available=False,
            code=ProviderAccessCode.TEMPORARILY_UNAVAILABLE,
            user_message=(
                "DeepSeek is temporarily unavailable. Try the "
                "DeepSeek task again later or use another connected "
                "engineering provider. Nexuss remains operational."
            ),
            recommended_action=(
                "Retry later or select another provider."
            ),
            model=status.model,
            identity_verified=status.verified,
            billing_ready=status.billing_ready,
            credential_present=status.credential_present,
        )

    def disconnect_deepseek(self) -> None:
        self._credentials.delete(_DEEPSEEK_PROVIDER_ID)
        self._vault.delete(_DEEPSEEK_CONFIGURATION_ID)

    def build_deepseek_router(
        self,
    ) -> EngineeringProviderRouter:
        access = self.deepseek_access()
        if not access.available:
            if (
                access.code
                is ProviderAccessCode.INSUFFICIENT_BALANCE
            ):
                error_code = (
                    "ENGINEERING_PROVIDER_INSUFFICIENT_BALANCE"
                )
            elif (
                access.code
                is ProviderAccessCode.NOT_CONNECTED
            ):
                error_code = (
                    "ENGINEERING_PROVIDER_NOT_CONNECTED"
                )
            elif (
                access.code
                is ProviderAccessCode.REAUTHENTICATION_REQUIRED
            ):
                error_code = (
                    "ENGINEERING_PROVIDER_REAUTHENTICATION_REQUIRED"
                )
            else:
                error_code = (
                    "ENGINEERING_PROVIDER_TEMPORARILY_UNAVAILABLE"
                )
            raise EngineeringError(
                error_code,
                access.user_message,
                retryable=(
                    access.code
                    is ProviderAccessCode.TEMPORARILY_UNAVAILABLE
                ),
            )

        profile = self._configured_deepseek_profile()
        api_key = self._credentials.get_api_key(
            _DEEPSEEK_PROVIDER_ID
        )
        provider = OpenAICompatibleProvider(
            profile,
            api_key,
            timeout_seconds=self._timeout_seconds,
            transport=self._transport,
        )
        return EngineeringProviderRouter((provider,))

    def _configured_deepseek_profile(
        self,
    ) -> ProviderProfile:
        payload = self._vault.get_json(
            _DEEPSEEK_CONFIGURATION_ID
        )
        if payload is None:
            return self.deepseek_profile()

        model = str(
            payload.get("model", _DEEPSEEK_DEFAULT_MODEL)
        ).strip()
        return self.deepseek_profile(model)

    def _probe_deepseek_identity(
        self,
        api_key: SecretStr,
        profile: ProviderProfile,
    ) -> ProviderConnectionStatus:
        payload = self._get_json(
            api_key,
            profile,
            "/models",
            context="identity",
        )
        available_models = self._parse_models(payload)
        if profile.model not in available_models:
            raise EngineeringError(
                "ENGINEERING_PROVIDER_MODEL_UNAVAILABLE",
                "The configured DeepSeek model is not available "
                "to this provider account.",
                safe_details={
                    "configured_model": profile.model,
                    "available_models": available_models,
                },
            )

        return ProviderConnectionStatus(
            provider_id=profile.provider_id,
            provider_kind=profile.kind,
            state=ProviderConnectionState.CONNECTED,
            connected=True,
            verified=True,
            credential_present=True,
            model=profile.model,
            api_base=profile.api_base,
            available_models=available_models,
            detail=(
                "DeepSeek credential and configured model "
                "were verified through the official API."
            ),
        )

    def _attach_billing_status(
        self,
        api_key: SecretStr,
        profile: ProviderProfile,
        identity_status: ProviderConnectionStatus,
    ) -> ProviderConnectionStatus:
        try:
            payload = self._get_json(
                api_key,
                profile,
                "/user/balance",
                context="billing",
            )
            billing_ready = self._parse_balance(payload)
        except EngineeringError as exc:
            return identity_status.model_copy(
                update={
                    "state": ProviderConnectionState.DEGRADED,
                    "billing_ready": None,
                    "failure_code": exc.code,
                    "detail": (
                        "DeepSeek identity is verified, but billing "
                        f"readiness could not be verified: {exc.code}."
                    ),
                    "checked_at": datetime.now(UTC),
                }
            )

        if not billing_ready:
            return identity_status.model_copy(
                update={
                    "state": ProviderConnectionState.DEGRADED,
                    "billing_ready": False,
                    "failure_code": (
                        "ENGINEERING_PROVIDER_INSUFFICIENT_BALANCE"
                    ),
                    "detail": (
                        "DeepSeek identity is verified, but the API "
                        "account has insufficient balance."
                    ),
                    "checked_at": datetime.now(UTC),
                }
            )

        return identity_status.model_copy(
            update={
                "billing_ready": True,
                "failure_code": None,
                "detail": (
                    "DeepSeek identity, configured model, and API "
                    "billing readiness were verified."
                ),
                "checked_at": datetime.now(UTC),
            }
        )

    def _get_json(
        self,
        api_key: SecretStr,
        profile: ProviderProfile,
        path: str,
        *,
        context: str,
    ) -> object:
        try:
            with httpx.Client(
                base_url=profile.api_base.rstrip("/"),
                timeout=self._timeout_seconds,
                transport=self._transport,
                headers={
                    "Authorization": (
                        "Bearer "
                        f"{api_key.get_secret_value()}"
                    ),
                    "Accept": "application/json",
                    "User-Agent": "Nexuss-Engineering/1.3",
                },
            ) as client:
                response = client.get(path)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code == 402:
                code = (
                    "ENGINEERING_PROVIDER_INSUFFICIENT_BALANCE"
                )
                message = (
                    "DeepSeek reported insufficient API balance."
                )
                retryable = False
            elif status_code in {401, 403}:
                code = (
                    "ENGINEERING_PROVIDER_CREDENTIAL_REJECTED"
                )
                message = (
                    "DeepSeek rejected the encrypted credential."
                )
                retryable = False
            elif status_code == 429:
                code = "ENGINEERING_PROVIDER_RATE_LIMITED"
                message = (
                    "DeepSeek rate-limited the provider probe."
                )
                retryable = True
            else:
                code = "ENGINEERING_PROVIDER_UNAVAILABLE"
                message = (
                    "DeepSeek returned an unavailable response."
                )
                retryable = status_code >= 500
            raise EngineeringError(
                code,
                message,
                retryable=retryable,
                safe_details={
                    "status_code": status_code,
                    "probe_context": context,
                },
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise EngineeringError(
                "ENGINEERING_PROVIDER_UNAVAILABLE",
                "DeepSeek could not be reached or returned "
                "an invalid provider response.",
                retryable=True,
                safe_details={"probe_context": context},
            ) from exc

    @staticmethod
    def _parse_models(
        payload: object,
    ) -> tuple[str, ...]:
        if not isinstance(payload, dict):
            raise EngineeringError(
                "ENGINEERING_PROVIDER_RESPONSE_INVALID",
                "The provider model-list response was not an object.",
            )
        data = payload.get("data")
        if not isinstance(data, list):
            raise EngineeringError(
                "ENGINEERING_PROVIDER_RESPONSE_INVALID",
                "The provider model-list response omitted its data list.",
            )

        models = sorted(
            {
                str(item.get("id", "")).strip()
                for item in data
                if isinstance(item, dict)
                and str(item.get("id", "")).strip()
            }
        )
        if not models:
            raise EngineeringError(
                "ENGINEERING_PROVIDER_RESPONSE_INVALID",
                "The provider returned no available models.",
            )
        return tuple(models)

    @staticmethod
    def _parse_balance(payload: object) -> bool:
        if (
            not isinstance(payload, dict)
            or not isinstance(
                payload.get("is_available"),
                bool,
            )
        ):
            raise EngineeringError(
                "ENGINEERING_PROVIDER_RESPONSE_INVALID",
                "The provider balance response omitted "
                "its availability flag.",
            )
        return bool(payload["is_available"])
