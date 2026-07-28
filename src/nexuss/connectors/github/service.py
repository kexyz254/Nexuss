"""High-level GitHub connector orchestration."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx

from nexuss.connectors.contracts import (
    ConnectorHealth,
    ConnectorIdentity,
    ConnectorStatus,
)
from nexuss.connectors.errors import ConnectorError
from nexuss.connectors.github.client import GitHubApiClient
from nexuss.connectors.github.device_flow import GitHubDeviceFlowClient
from nexuss.connectors.github.models import (
    GitHubConnectChallenge,
    GitHubConnectionProfile,
    GitHubConnectResult,
    GitHubConnectState,
    GitHubRepositoryInventory,
    OAuthTokenBundle,
    PreparedRepositoryCreate,
    RepositoryCreateApproval,
    VerifiedRepositoryCreate,
    canonical_payload_bytes,
)
from nexuss.connectors.vault import SecretVault

_VALID_REPOSITORY_NAME = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_INVALID_REPOSITORY_CHARACTER = re.compile(r"[^A-Za-z0-9._-]+")


class GitHubConnectorService:
    connector_id = "github"

    _TOKEN_ID = "github:user:token"
    _PROFILE_ID = "github:user:profile"
    _PENDING_PREFIX = "github:pending:"

    def __init__(
        self,
        *,
        vault: SecretVault,
        device_flow: GitHubDeviceFlowClient | None = None,
        api_transport: httpx.BaseTransport | None = None,
        api_base: str = "https://api.github.com",
    ) -> None:
        self._vault = vault
        self._device_flow = device_flow or GitHubDeviceFlowClient()
        self._api_transport = api_transport
        self._api_base = api_base

    def begin_connection(self, client_id: str, *, now: datetime | None = None) -> GitHubConnectChallenge:
        normalized = client_id.strip()
        if not normalized:
            raise ConnectorError("GITHUB_CLIENT_ID_MISSING", "The GitHub App client ID is not configured.")
        authorization = self._device_flow.begin(normalized, now=now)
        flow_id = uuid4()
        self._vault.put_json(
            self._pending_id(flow_id),
            {
                "client_id": normalized,
                "device_code": authorization.device_code.get_secret_value(),
                "expires_at": authorization.expires_at.isoformat(),
                "interval_seconds": authorization.interval_seconds,
            },
        )
        return GitHubConnectChallenge(
            flow_id=flow_id,
            user_code=authorization.user_code,
            verification_uri=authorization.verification_uri,
            expires_at=authorization.expires_at,
            poll_interval_seconds=authorization.interval_seconds,
        )

    def poll_connection(self, flow_id: UUID, *, now: datetime | None = None) -> GitHubConnectResult:
        checked_at = now or datetime.now(UTC)
        pending = self._vault.get_json(self._pending_id(flow_id))
        if pending is None:
            raise ConnectorError("GITHUB_DEVICE_FLOW_NOT_FOUND", "The GitHub connection flow was not found.")
        expires_at = datetime.fromisoformat(str(pending["expires_at"]))
        if checked_at >= expires_at:
            self._vault.delete(self._pending_id(flow_id))
            return GitHubConnectResult(state=GitHubConnectState.EXPIRED)
        result = self._device_flow.poll(
            str(pending["client_id"]),
            str(pending["device_code"]),
            interval_seconds=int(pending["interval_seconds"]),
            now=checked_at,
        )
        if result.state in {GitHubConnectState.PENDING, GitHubConnectState.SLOW_DOWN}:
            return GitHubConnectResult(state=result.state, retry_after_seconds=result.retry_after_seconds)
        if result.state in {GitHubConnectState.DENIED, GitHubConnectState.EXPIRED}:
            self._vault.delete(self._pending_id(flow_id))
            return GitHubConnectResult(state=result.state)
        if result.token is None:
            raise ConnectorError("GITHUB_TOKEN_RESPONSE_INVALID", "GitHub connected without returning a token.")
        account = self._client_for_token(result.token).authenticated_user()
        profile = GitHubConnectionProfile(
            client_id=str(pending["client_id"]),
            account=account,
            connected_at=checked_at,
            token_expires_at=result.token.access_token_expires_at,
        )
        self._vault.put_json(self._TOKEN_ID, result.token.to_vault_payload())
        self._vault.put_json(self._PROFILE_ID, profile.model_dump(mode="json"))
        self._vault.delete(self._pending_id(flow_id))
        return GitHubConnectResult(state=GitHubConnectState.CONNECTED, profile=profile)

    def health(self, *, now: datetime | None = None) -> ConnectorHealth:
        checked_at = now or datetime.now(UTC)
        profile = self._load_profile()
        if profile is None:
            return ConnectorHealth(
                connector_id=self.connector_id,
                status=ConnectorStatus.DISCONNECTED,
                configured=False,
                detail="GitHub is not connected.",
                checked_at=checked_at,
            )
        try:
            account = self._authenticated_client(now=checked_at).authenticated_user()
        except ConnectorError as exc:
            return ConnectorHealth(
                connector_id=self.connector_id,
                status=(ConnectorStatus.REAUTH_REQUIRED if exc.code == "GITHUB_REAUTH_REQUIRED" else ConnectorStatus.DEGRADED),
                configured=True,
                identity=ConnectorIdentity(
                    connector_id=self.connector_id,
                    external_account_id=str(profile.account.account_id),
                    account_label=profile.account.login,
                    account_type=profile.account.account_type,
                    verified=False,
                    observed_at=checked_at,
                ),
                detail=exc.message,
                checked_at=checked_at,
            )
        self._require_account_match(profile, account.account_id, account.login)
        return ConnectorHealth(
            connector_id=self.connector_id,
            status=ConnectorStatus.CONNECTED,
            configured=True,
            identity=ConnectorIdentity(
                connector_id=self.connector_id,
                external_account_id=str(account.account_id),
                account_label=account.login,
                account_type=account.account_type,
                verified=True,
                observed_at=checked_at,
            ),
            detail="GitHub identity and authorization are verified.",
            checked_at=checked_at,
        )

    def disconnect(self) -> None:
        self._vault.delete(self._TOKEN_ID)
        self._vault.delete(self._PROFILE_ID)

    def list_repositories(self, *, now: datetime | None = None) -> GitHubRepositoryInventory:
        checked_at = now or datetime.now(UTC)
        profile = self._require_profile()
        api = self._authenticated_client(now=checked_at)
        account = api.authenticated_user()
        self._require_account_match(profile, account.account_id, account.login)
        repositories = api.list_repositories()
        return GitHubRepositoryInventory(
            account_login=account.login,
            total=len(repositories),
            private_count=sum(repository.private for repository in repositories),
            public_count=sum(not repository.private for repository in repositories),
            archived_count=sum(repository.archived for repository in repositories),
            disabled_count=sum(repository.disabled for repository in repositories),
            fork_count=sum(repository.fork for repository in repositories),
            repositories=repositories,
            observed_at=checked_at,
        )

    def prepare_private_repository(
        self,
        requested_name: str,
        *,
        description: str = "",
        now: datetime | None = None,
    ) -> PreparedRepositoryCreate:
        profile = self._require_profile()
        requested = " ".join(requested_name.split()).strip()
        if not requested:
            raise ConnectorError("GITHUB_NAME_INVALID", "A repository name is required.")
        repository_name = self.suggest_repository_name(requested)
        payload: dict[str, object] = {"name": repository_name, "private": True, "auto_init": False}
        normalized_description = description.strip()
        if normalized_description:
            payload["description"] = normalized_description
        digest = hashlib.sha256(canonical_payload_bytes(payload)).hexdigest()
        return PreparedRepositoryCreate(
            owner_login=profile.account.login,
            requested_name=requested,
            repository_name=repository_name,
            description=normalized_description,
            payload=payload,
            payload_sha256=digest,
            prepared_at=now or datetime.now(UTC),
        )

    def create_private_repository(
        self,
        prepared: PreparedRepositoryCreate,
        approval: RepositoryCreateApproval,
        *,
        now: datetime | None = None,
    ) -> VerifiedRepositoryCreate:
        checked_at = now or datetime.now(UTC)
        profile = self._require_profile()
        if approval.request_id != prepared.request_id:
            raise ConnectorError("GITHUB_APPROVAL_REQUEST_MISMATCH", "The approval belongs to a different request.")
        if approval.payload_sha256 != prepared.payload_sha256:
            raise ConnectorError("GITHUB_APPROVAL_PAYLOAD_MISMATCH", "The approved payload does not match.")
        if approval.account_login.casefold() != prepared.owner_login.casefold():
            raise ConnectorError("GITHUB_APPROVAL_ACCOUNT_MISMATCH", "The approval names a different GitHub account.")
        if checked_at >= approval.expires_at:
            raise ConnectorError("GITHUB_APPROVAL_EXPIRED", "The GitHub repository approval expired.")
        if checked_at < approval.approved_at:
            raise ConnectorError("GITHUB_APPROVAL_TIME_INVALID", "The approval timestamp is in the future.")
        if not prepared.private:
            raise ConnectorError("GITHUB_VISIBILITY_NOT_ALLOWED", "This capability creates private repositories only.")
        if prepared.auto_init:
            raise ConnectorError("GITHUB_INITIALIZATION_NOT_ALLOWED", "Repository initialization was not approved.")

        api = self._authenticated_client(now=checked_at)
        account = api.authenticated_user()
        self._require_account_match(profile, account.account_id, account.login)
        if account.login.casefold() != prepared.owner_login.casefold():
            raise ConnectorError("GITHUB_ACCOUNT_MISMATCH", "The connected GitHub account changed.")
        if api.repository_exists(account.login, prepared.repository_name):
            raise ConnectorError("GITHUB_REPOSITORY_ALREADY_EXISTS", "A repository with this name already exists.")

        api.create_repository(prepared.payload)
        repository = api.get_repository(account.login, prepared.repository_name)
        empty = api.repository_is_empty(account.login, prepared.repository_name)
        private_verified = repository.private is True
        owner_verified = repository.owner_login.casefold() == account.login.casefold()
        name_verified = repository.name.casefold() == prepared.repository_name.casefold()
        if not (private_verified and owner_verified and name_verified and empty):
            raise ConnectorError(
                "GITHUB_CREATION_NOT_VERIFIED",
                "GitHub repository creation failed verification.",
                safe_details={
                    "private_verified": private_verified,
                    "owner_verified": owner_verified,
                    "name_verified": name_verified,
                    "empty_verified": empty,
                },
            )
        return VerifiedRepositoryCreate(
            request_id=prepared.request_id,
            approval_id=approval.approval_id,
            payload_sha256=prepared.payload_sha256,
            repository=repository,
            private_verified=private_verified,
            empty_repository_verified=empty,
            owner_verified=owner_verified,
            name_verified=name_verified,
            verified_at=checked_at,
        )

    @staticmethod
    def suggest_repository_name(requested_name: str) -> str:
        requested = " ".join(requested_name.split()).strip()
        if _VALID_REPOSITORY_NAME.fullmatch(requested):
            return requested
        suggested = _INVALID_REPOSITORY_CHARACTER.sub("-", requested).strip("-._")
        suggested = re.sub(r"-{2,}", "-", suggested)[:100]
        if not suggested or not _VALID_REPOSITORY_NAME.fullmatch(suggested):
            raise ConnectorError("GITHUB_NAME_INVALID", "The requested repository name cannot be normalized safely.")
        return suggested

    def _authenticated_client(self, *, now: datetime) -> GitHubApiClient:
        profile = self._require_profile()
        token = self._load_token()
        if token.access_token_expires_at is not None and now >= token.access_token_expires_at:
            token = self._refresh_token(profile, token, now=now)
        return self._client_for_token(token)

    def _refresh_token(
        self,
        profile: GitHubConnectionProfile,
        token: OAuthTokenBundle,
        *,
        now: datetime,
    ) -> OAuthTokenBundle:
        if token.refresh_token is None:
            raise ConnectorError("GITHUB_REAUTH_REQUIRED", "The GitHub access token expired.")
        if token.refresh_token_expires_at is not None and now >= token.refresh_token_expires_at:
            raise ConnectorError("GITHUB_REAUTH_REQUIRED", "The GitHub refresh token expired.")
        refreshed = self._device_flow.refresh(
            profile.client_id,
            token.refresh_token.get_secret_value(),
            now=now,
        )
        self._vault.put_json(self._TOKEN_ID, refreshed.to_vault_payload())
        updated_profile = profile.model_copy(update={"token_expires_at": refreshed.access_token_expires_at})
        self._vault.put_json(self._PROFILE_ID, updated_profile.model_dump(mode="json"))
        return refreshed

    def _client_for_token(self, token: OAuthTokenBundle) -> GitHubApiClient:
        return GitHubApiClient(
            token.access_token.get_secret_value(),
            api_base=self._api_base,
            transport=self._api_transport,
        )

    def _load_token(self) -> OAuthTokenBundle:
        payload = self._vault.get_json(self._TOKEN_ID)
        if payload is None:
            raise ConnectorError("GITHUB_NOT_CONNECTED", "GitHub is not connected.")
        try:
            return OAuthTokenBundle.from_vault_payload(payload)
        except (TypeError, ValueError) as exc:
            raise ConnectorError("GITHUB_TOKEN_RECORD_INVALID", "The stored GitHub authorization is invalid.") from exc

    def _load_profile(self) -> GitHubConnectionProfile | None:
        payload = self._vault.get_json(self._PROFILE_ID)
        if payload is None:
            return None
        try:
            return GitHubConnectionProfile.model_validate(payload)
        except ValueError as exc:
            raise ConnectorError("GITHUB_PROFILE_RECORD_INVALID", "The stored GitHub profile is invalid.") from exc

    def _require_profile(self) -> GitHubConnectionProfile:
        profile = self._load_profile()
        if profile is None:
            raise ConnectorError("GITHUB_NOT_CONNECTED", "GitHub is not connected.")
        return profile

    @staticmethod
    def _require_account_match(profile: GitHubConnectionProfile, live_account_id: int, live_login: str) -> None:
        if profile.account.account_id != live_account_id or profile.account.login.casefold() != live_login.casefold():
            raise ConnectorError("GITHUB_ACCOUNT_MISMATCH", "The live GitHub account differs from the approved account.")

    @classmethod
    def _pending_id(cls, flow_id: UUID) -> str:
        return f"{cls._PENDING_PREFIX}{flow_id}"
