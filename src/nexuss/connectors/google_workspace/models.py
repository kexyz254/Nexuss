"""Validated Google Workspace contracts."""
from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class GoogleOAuthTokenBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    access_token: SecretStr = Field(repr=False)
    refresh_token: SecretStr | None = Field(default=None, repr=False)
    token_type: str = "Bearer"
    expires_at: datetime
    scopes: tuple[str, ...]

    @field_validator("expires_at")
    @classmethod
    def expires_at_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")
        return value.astimezone(UTC)

    def to_vault_payload(self) -> dict[str, object]:
        return {
            "access_token": self.access_token.get_secret_value(),
            "refresh_token": (
                self.refresh_token.get_secret_value()
                if self.refresh_token else None
            ),
            "token_type": self.token_type,
            "expires_at": self.expires_at.isoformat(),
            "scopes": list(self.scopes),
            "format_version": 1,
        }

    @classmethod
    def from_vault_payload(cls, payload: dict[str, object]) -> GoogleOAuthTokenBundle:
        access_token = str(payload.get("access_token", "")).strip()
        if not access_token:
            raise ValueError("access_token is missing")
        refresh_value = str(payload.get("refresh_token") or "").strip()
        scopes = payload.get("scopes", [])
        if not isinstance(scopes, list):
            raise TypeError("scopes must be a list")
        return cls(
            access_token=SecretStr(access_token),
            refresh_token=SecretStr(refresh_value) if refresh_value else None,
            token_type=str(payload.get("token_type", "Bearer")),
            expires_at=datetime.fromisoformat(str(payload["expires_at"])),
            scopes=tuple(str(scope) for scope in scopes),
        )

class GoogleWorkspaceProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    email: str
    display_name: str | None = None
    connected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    granted_scopes: tuple[str, ...]
    verified: bool = True

class GmailMessageSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    message_id: str
    thread_id: str
    subject: str
    sender: str
    recipients: tuple[str, ...] = ()
    received_at: datetime
    snippet: str = Field(max_length=4_000)
    body_text: str = Field(default="", max_length=12_000)
    labels: tuple[str, ...] = ()
    unread: bool = False

class GoogleCalendarSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    calendar_id: str
    title: str
    primary: bool = False
    selected: bool = True
    access_role: str

class CalendarEventSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    event_id: str
    calendar_id: str
    title: str
    start: datetime
    end: datetime
    attendees: tuple[str, ...] = ()
    organizer: str | None = None
    location: str | None = None
    status: str = "confirmed"
    html_url: str | None = None
    all_day: bool = False

    @field_validator("start", "end")
    @classmethod
    def event_time_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("calendar event times must be timezone-aware")
        return value

class ContactSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    resource_name: str
    display_name: str
    emails: tuple[str, ...] = ()
    phones: tuple[str, ...] = ()
    organization: str | None = None

class GoogleWorkspaceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    profile: GoogleWorkspaceProfile | None
    messages: tuple[GmailMessageSummary, ...]
    calendars: tuple[GoogleCalendarSummary, ...]
    events: tuple[CalendarEventSummary, ...]
    contacts: tuple[ContactSummary, ...]
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    read_only: bool = True
    external_write_performed: bool = False
    credentials_exposed: bool = False

class GoogleWorkspaceHealth(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    connected: bool
    account_email: str | None = None
    gmail_read: bool = False
    calendar_read: bool = False
    contacts_read: bool = False
    encrypted_storage: str
    external_write_authority_added: bool = False
    credentials_exposed: bool = False
