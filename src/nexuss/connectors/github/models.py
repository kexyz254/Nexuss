"""Validated GitHub connector contracts."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    SecretStr,
    field_validator,
    model_validator,
)

_REPOSITORY_NAME = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


class GitHubConnectState(StrEnum):
    PENDING = "pending"
    SLOW_DOWN = "slow_down"
    CONNECTED = "connected"
    DENIED = "denied"
    EXPIRED = "expired"


class DeviceAuthorizationSecret(BaseModel):
    model_config = ConfigDict(frozen=True)

    device_code: SecretStr = Field(repr=False)
    user_code: str
    verification_uri: HttpUrl
    expires_at: datetime
    interval_seconds: int = Field(ge=1, le=60)


class GitHubConnectChallenge(BaseModel):
    model_config = ConfigDict(frozen=True)

    flow_id: UUID
    user_code: str
    verification_uri: HttpUrl
    expires_at: datetime
    poll_interval_seconds: int


class OAuthTokenBundle(BaseModel):
    model_config = ConfigDict(frozen=True)

    access_token: SecretStr = Field(repr=False)
    token_type: str = "bearer"
    access_token_expires_at: datetime | None = None
    refresh_token: SecretStr | None = Field(default=None, repr=False)
    refresh_token_expires_at: datetime | None = None

    def to_vault_payload(self) -> dict[str, object]:
        return {
            "access_token": self.access_token.get_secret_value(),
            "token_type": self.token_type,
            "access_token_expires_at": self.access_token_expires_at.isoformat() if self.access_token_expires_at else None,
            "refresh_token": self.refresh_token.get_secret_value() if self.refresh_token else None,
            "refresh_token_expires_at": self.refresh_token_expires_at.isoformat() if self.refresh_token_expires_at else None,
        }

    @classmethod
    def from_vault_payload(cls, payload: dict[str, object]) -> OAuthTokenBundle:
        access_token = str(payload.get("access_token", "")).strip()
        if not access_token:
            raise ValueError("access_token is missing")
        refresh_value = str(payload.get("refresh_token") or "").strip()
        return cls(
            access_token=SecretStr(access_token),
            token_type=str(payload.get("token_type", "bearer")),
            access_token_expires_at=_optional_datetime(payload.get("access_token_expires_at")),
            refresh_token=SecretStr(refresh_value) if refresh_value else None,
            refresh_token_expires_at=_optional_datetime(payload.get("refresh_token_expires_at")),
        )


class DevicePollResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    state: GitHubConnectState
    token: OAuthTokenBundle | None = None
    retry_after_seconds: int | None = None


class GitHubAccount(BaseModel):
    model_config = ConfigDict(frozen=True)

    account_id: int
    login: str
    account_type: str
    html_url: HttpUrl
    avatar_url: HttpUrl | None = None

    @field_validator("login")
    @classmethod
    def login_nonempty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("login must not be empty")
        return normalized


class GitHubConnectionProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    connector_id: str = "github"
    client_id: str
    account: GitHubAccount
    connected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    token_expires_at: datetime | None = None
    verified: bool = True


class GitHubConnectResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    state: GitHubConnectState
    profile: GitHubConnectionProfile | None = None
    retry_after_seconds: int | None = None


class GitHubRepository(BaseModel):
    model_config = ConfigDict(frozen=True)

    repository_id: int
    node_id: str
    name: str
    full_name: str
    owner_login: str
    private: bool
    archived: bool = False
    disabled: bool = False
    fork: bool = False
    html_url: HttpUrl
    api_url: HttpUrl
    default_branch: str | None = None
    size_kb: int = 0
    open_issues_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    pushed_at: datetime | None = None
    permissions: dict[str, bool] = Field(default_factory=dict)


class GitHubRepositoryInventory(BaseModel):
    model_config = ConfigDict(frozen=True)

    account_login: str
    total: int
    private_count: int
    public_count: int
    archived_count: int
    disabled_count: int
    fork_count: int
    repositories: tuple[GitHubRepository, ...]
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PreparedRepositoryCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: UUID = Field(default_factory=uuid4)
    owner_login: str
    requested_name: str
    repository_name: str
    private: bool = True
    auto_init: bool = False
    description: str = ""
    payload: dict[str, object]
    payload_sha256: str
    prepared_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("repository_name")
    @classmethod
    def repository_name_valid(cls, value: str) -> str:
        if not _REPOSITORY_NAME.fullmatch(value):
            raise ValueError("repository_name must be URL-safe and 1-100 characters")
        return value

    @model_validator(mode="after")
    def payload_matches_contract(self) -> PreparedRepositoryCreate:
        expected: dict[str, object] = {"name": self.repository_name, "private": True, "auto_init": False}
        if self.description:
            expected["description"] = self.description
        if self.payload != expected:
            raise ValueError("payload does not match the prepared repository contract")
        digest = hashlib.sha256(canonical_payload_bytes(self.payload)).hexdigest()
        if digest != self.payload_sha256:
            raise ValueError("payload_sha256 is invalid")
        return self


class RepositoryCreateApproval(BaseModel):
    model_config = ConfigDict(frozen=True)

    approval_id: UUID
    request_id: UUID
    account_login: str
    payload_sha256: str
    approved_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def expiry_valid(self) -> RepositoryCreateApproval:
        if self.expires_at <= self.approved_at:
            raise ValueError("approval expiry must follow approval time")
        return self


class VerifiedRepositoryCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: UUID
    approval_id: UUID
    payload_sha256: str
    repository: GitHubRepository
    private_verified: bool
    empty_repository_verified: bool
    owner_verified: bool
    name_verified: bool
    verified_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def canonical_payload_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _optional_datetime(value: object) -> datetime | None:
    if value in {None, ""}:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))
