"""Bounded read-only clients for Gmail, Calendar, and People APIs."""
from __future__ import annotations

import base64
from datetime import UTC, datetime
from email.utils import getaddresses, parsedate_to_datetime
from urllib.parse import quote

import httpx

from nexuss.connectors.errors import ConnectorError
from nexuss.connectors.google_workspace.models import (
    CalendarEventSummary,
    ContactSummary,
    GmailMessageSummary,
    GoogleCalendarSummary,
)


class GoogleWorkspaceApiClient:
    def __init__(
        self,
        access_token: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not access_token:
            raise ValueError("access_token is required")
        self._access_token = access_token
        self._transport = transport
        self._timeout = timeout_seconds

    def gmail_profile(self) -> dict[str, object]:
        result = self._get(
            "https://gmail.googleapis.com/gmail/v1/users/me/profile"
        )
        if not isinstance(result, dict):
            raise self._invalid("Gmail profile")
        return result

    def list_messages(
        self,
        *,
        query: str = "newer_than:14d",
        limit: int = 40,
    ) -> tuple[GmailMessageSummary, ...]:
        listing = self._get(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            params={"q": query, "maxResults": min(max(limit, 1), 100)},
        )
        records = listing.get("messages", []) if isinstance(listing, dict) else []
        result: list[GmailMessageSummary] = []
        for record in records[:limit]:
            if not isinstance(record, dict):
                continue
            message_id = str(record.get("id", ""))
            if not message_id:
                continue
            payload = self._get(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/"
                f"{quote(message_id, safe='')}",
                params={"format": "full"},
            )
            result.append(self._message(payload))
        return tuple(result)

    def list_calendars(
        self,
        *,
        limit: int = 20,
    ) -> tuple[GoogleCalendarSummary, ...]:
        payload = self._get(
            "https://www.googleapis.com/calendar/v3/users/me/calendarList",
            params={
                "maxResults": min(max(limit, 1), 250),
                "showDeleted": "false",
                "showHidden": "false",
            },
        )
        items = payload.get("items", []) if isinstance(payload, dict) else []
        return tuple(
            GoogleCalendarSummary(
                calendar_id=str(item.get("id", "")),
                title=str(
                    item.get("summaryOverride")
                    or item.get("summary")
                    or item.get("id")
                    or "Calendar"
                ),
                primary=bool(item.get("primary", False)),
                selected=bool(item.get("selected", True)),
                access_role=str(item.get("accessRole", "reader")),
            )
            for item in items[:limit]
            if isinstance(item, dict) and item.get("id")
        )

    def list_events(
        self,
        calendars: tuple[GoogleCalendarSummary, ...],
        *,
        time_min: datetime,
        time_max: datetime,
        per_calendar_limit: int = 60,
    ) -> tuple[CalendarEventSummary, ...]:
        events: list[CalendarEventSummary] = []
        for calendar in calendars[:12]:
            payload = self._get(
                "https://www.googleapis.com/calendar/v3/calendars/"
                f"{quote(calendar.calendar_id, safe='')}/events",
                params={
                    "timeMin": time_min.astimezone(UTC).isoformat(),
                    "timeMax": time_max.astimezone(UTC).isoformat(),
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "showDeleted": "false",
                    "maxResults": min(max(per_calendar_limit, 1), 2500),
                },
            )
            items = payload.get("items", []) if isinstance(payload, dict) else []
            for item in items:
                if isinstance(item, dict):
                    parsed = self._event(calendar.calendar_id, item)
                    if parsed is not None:
                        events.append(parsed)
        return tuple(sorted(events, key=lambda item: item.start))

    def list_contacts(
        self,
        *,
        limit: int = 250,
    ) -> tuple[ContactSummary, ...]:
        payload = self._get(
            "https://people.googleapis.com/v1/people/me/connections",
            params={
                "personFields": (
                    "names,emailAddresses,phoneNumbers,organizations"
                ),
                "pageSize": min(max(limit, 1), 1000),
                "sortOrder": "LAST_MODIFIED_DESCENDING",
            },
        )
        people = payload.get("connections", []) if isinstance(payload, dict) else []
        result: list[ContactSummary] = []
        for person in people[:limit]:
            if not isinstance(person, dict):
                continue
            names = person.get("names") or []
            emails = person.get("emailAddresses") or []
            phones = person.get("phoneNumbers") or []
            organizations = person.get("organizations") or []
            display_name = self._first_value(names, "displayName")
            if not display_name:
                display_name = self._first_value(emails, "value")
            if not display_name:
                continue
            result.append(
                ContactSummary(
                    resource_name=str(person.get("resourceName", "")),
                    display_name=display_name,
                    emails=tuple(
                        str(item.get("value"))
                        for item in emails
                        if isinstance(item, dict) and item.get("value")
                    ),
                    phones=tuple(
                        str(item.get("value"))
                        for item in phones
                        if isinstance(item, dict) and item.get("value")
                    ),
                    organization=(
                        self._first_value(organizations, "name")
                        or self._first_value(organizations, "title")
                    ),
                )
            )
        return tuple(result)

    def _get(
        self,
        url: str,
        *,
        params: dict[str, object] | None = None,
    ) -> object:
        try:
            with httpx.Client(
                transport=self._transport,
                timeout=self._timeout,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self._access_token}",
                    "User-Agent": "Nexuss-Google-Workspace/1.0",
                },
            ) as client:
                response = client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise ConnectorError(
                "GOOGLE_API_UNAVAILABLE",
                "Google Workspace could not be reached.",
                retryable=True,
            ) from exc
        if response.status_code == 401:
            raise ConnectorError(
                "GOOGLE_REAUTH_REQUIRED",
                "Google rejected the stored authorization.",
            )
        if response.status_code == 403:
            raise ConnectorError(
                "GOOGLE_SCOPE_OR_API_REQUIRED",
                "Google denied the read. Confirm the API and read scope.",
            )
        if response.status_code >= 400:
            raise ConnectorError(
                "GOOGLE_API_REQUEST_FAILED",
                "Google Workspace rejected a bounded read request.",
                safe_details={"status_code": response.status_code},
            )
        try:
            return response.json()
        except ValueError as exc:
            raise ConnectorError(
                "GOOGLE_API_RESPONSE_INVALID",
                "Google returned non-JSON content.",
            ) from exc

    @classmethod
    def _message(cls, payload: object) -> GmailMessageSummary:
        if not isinstance(payload, dict):
            raise cls._invalid("Gmail message")
        body = payload.get("payload")
        if not isinstance(body, dict):
            body = {}
        headers = body.get("headers") or []
        header_map = {
            str(item.get("name", "")).casefold(): str(item.get("value", ""))
            for item in headers
            if isinstance(item, dict)
        }
        recipients = tuple(
            address
            for _, address in getaddresses(
                [header_map.get("to", ""), header_map.get("cc", "")]
            )
            if address
        )
        labels = tuple(str(value) for value in payload.get("labelIds", []))
        return GmailMessageSummary(
            message_id=str(payload.get("id", "")),
            thread_id=str(payload.get("threadId", "")),
            subject=header_map.get("subject", "(no subject)"),
            sender=header_map.get("from", ""),
            recipients=recipients,
            received_at=cls._message_time(payload, header_map),
            snippet=str(payload.get("snippet", ""))[:4_000],
            body_text=cls._plain_text(body)[:12_000],
            labels=labels,
            unread="UNREAD" in labels,
        )

    @staticmethod
    def _message_time(
        payload: dict[str, object],
        headers: dict[str, str],
    ) -> datetime:
        internal = str(payload.get("internalDate", "")).strip()
        if internal.isdigit():
            return datetime.fromtimestamp(int(internal) / 1000, tz=UTC)
        date_header = headers.get("date", "")
        if date_header:
            try:
                value = parsedate_to_datetime(date_header)
                if value.tzinfo is None:
                    return value.replace(tzinfo=UTC)
                return value.astimezone(UTC)
            except (TypeError, ValueError, OverflowError):
                pass
        return datetime.now(UTC)

    @classmethod
    def _plain_text(cls, part: dict[str, object]) -> str:
        if str(part.get("mimeType", "")) == "text/plain":
            body = part.get("body")
            if isinstance(body, dict):
                encoded = str(body.get("data", ""))
                if encoded:
                    return cls._decode_urlsafe(encoded)
        texts: list[str] = []
        for child in part.get("parts", []) or []:
            if isinstance(child, dict):
                value = cls._plain_text(child)
                if value:
                    texts.append(value)
        return "\n".join(texts)

    @staticmethod
    def _decode_urlsafe(value: str) -> str:
        padding = "=" * (-len(value) % 4)
        try:
            return base64.urlsafe_b64decode(value + padding).decode(
                "utf-8", errors="replace"
            )
        except (ValueError, UnicodeError):
            return ""

    @classmethod
    def _event(
        cls,
        calendar_id: str,
        payload: dict[str, object],
    ) -> CalendarEventSummary | None:
        start_record = payload.get("start")
        end_record = payload.get("end")
        if not isinstance(start_record, dict) or not isinstance(end_record, dict):
            return None
        start = cls._calendar_time(start_record)
        end = cls._calendar_time(end_record)
        if start is None or end is None or end <= start:
            return None
        attendees = payload.get("attendees") or []
        organizer = payload.get("organizer")
        return CalendarEventSummary(
            event_id=str(payload.get("id", "")),
            calendar_id=calendar_id,
            title=str(payload.get("summary") or "(untitled event)"),
            start=start,
            end=end,
            attendees=tuple(
                str(item.get("email"))
                for item in attendees
                if isinstance(item, dict) and item.get("email")
            ),
            organizer=(
                str(organizer.get("email"))
                if isinstance(organizer, dict) and organizer.get("email")
                else None
            ),
            location=str(payload.get("location")) if payload.get("location") else None,
            status=str(payload.get("status", "confirmed")),
            html_url=str(payload.get("htmlLink")) if payload.get("htmlLink") else None,
            all_day="date" in start_record,
        )

    @staticmethod
    def _calendar_time(record: dict[str, object]) -> datetime | None:
        date_time = record.get("dateTime")
        if date_time:
            value = datetime.fromisoformat(str(date_time))
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        date_value = record.get("date")
        if not date_value:
            return None
        return datetime.fromisoformat(str(date_value)).replace(tzinfo=UTC)

    @staticmethod
    def _first_value(records: object, key: str) -> str | None:
        if not isinstance(records, list):
            return None
        for item in records:
            if isinstance(item, dict) and item.get(key):
                return str(item[key])
        return None

    @staticmethod
    def _invalid(label: str) -> ConnectorError:
        return ConnectorError(
            "GOOGLE_API_RESPONSE_INVALID",
            f"Google returned an invalid {label}.",
        )
