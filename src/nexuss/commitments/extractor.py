"""Evidence-bound deterministic commitment extraction."""
from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime, time, timedelta
from email.utils import parseaddr
from zoneinfo import ZoneInfo

from nexuss.commitments.models import (
    CommitmentEvidence,
    CommitmentKind,
    CommitmentPriority,
    CommitmentRecord,
    CommitmentSource,
    CommitmentStatus,
)
from nexuss.connectors.google_workspace.models import (
    GmailMessageSummary,
    GoogleWorkspaceSnapshot,
)
from nexuss.mobile_fabric.models import MobileFeedSnapshot, MobileSignalKind

_PROMISE = re.compile(
    r"\b(i will|i'll|i can|i shall|let me|i promise|we will|we'll|"
    r"will send|will review|will confirm|will get back)\b",
    re.IGNORECASE,
)
_REQUEST = re.compile(
    r"\b(please|can you|could you|would you|need you to|send me|share|"
    r"review|confirm|reply|respond|follow up|complete|provide|submit|"
    r"deliver|check)\b",
    re.IGNORECASE,
)
_QUESTION = re.compile(r"\?|^(when|what|where|why|how|who)\b", re.IGNORECASE)
_ISO_DATE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_MONTH_DATE = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
    r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)\s+(\d{1,2})(?:,\s*(20\d{2}))?\b",
    re.IGNORECASE,
)
_BY_TIME = re.compile(
    r"\bby\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",
    re.IGNORECASE,
)
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

def extract_commitments(
    *,
    snapshot: GoogleWorkspaceSnapshot,
    mobile: MobileFeedSnapshot | None,
    now: datetime,
    timezone_name: str,
) -> tuple[CommitmentRecord, ...]:
    zone = ZoneInfo(timezone_name)
    local_now = now.astimezone(zone)
    self_email = (
        snapshot.profile.email.casefold()
        if snapshot.profile is not None
        else None
    )
    records: list[CommitmentRecord] = []
    for message in snapshot.messages:
        record = _from_email(
            message,
            self_email=self_email,
            local_now=local_now,
            zone=zone,
        )
        if record is not None:
            records.append(record)
    if mobile is not None:
        for item in mobile.items:
            record = _from_mobile(
                item.signal,
                local_now=local_now,
                zone=zone,
            )
            if record is not None:
                records.append(record)
    return _deduplicate(records)

def _from_email(
    message: GmailMessageSummary,
    *,
    self_email: str | None,
    local_now: datetime,
    zone: ZoneInfo,
) -> CommitmentRecord | None:
    _, sender_email = parseaddr(message.sender)
    authored_by_self = bool(
        self_email and sender_email and sender_email.casefold() == self_email
    )
    text = " ".join(
        value for value in (
            message.subject,
            message.snippet,
            message.body_text,
        ) if value
    )
    kind: CommitmentKind | None = None
    confidence = 0.0
    response_needed = False
    if authored_by_self and _PROMISE.search(text):
        kind = CommitmentKind.PROMISE
        confidence = 0.91
    elif not authored_by_self and _REQUEST.search(text):
        kind = CommitmentKind.REQUEST
        confidence = 0.87
        response_needed = message.unread
    elif not authored_by_self and message.unread and _QUESTION.search(text):
        kind = CommitmentKind.RESPONSE_NEEDED
        confidence = 0.76
        response_needed = True
    if kind is None:
        return None
    return _record(
        kind=kind,
        summary=_summary(message.subject, message.snippet),
        counterparty=message.sender,
        due_at=_deadline(text, local_now=local_now, zone=zone),
        confidence=confidence,
        response_needed=response_needed,
        source=CommitmentSource.GMAIL,
        source_id=message.message_id,
        excerpt=text,
        observed_at=message.received_at,
        now=local_now,
    )

def _from_mobile(signal, *, local_now: datetime, zone: ZoneInfo) -> CommitmentRecord | None:
    text = signal.text or ""
    if not text:
        return None
    kind: CommitmentKind | None = None
    confidence = 0.0
    response_needed = False
    if signal.kind is MobileSignalKind.MESSAGE_SENT and _PROMISE.search(text):
        kind = CommitmentKind.PROMISE
        confidence = 0.86
    elif signal.kind is MobileSignalKind.MESSAGE_RECEIVED and _REQUEST.search(text):
        kind = CommitmentKind.REQUEST
        confidence = 0.83
        response_needed = True
    elif signal.kind is MobileSignalKind.MESSAGE_RECEIVED and _QUESTION.search(text):
        kind = CommitmentKind.RESPONSE_NEEDED
        confidence = 0.72
        response_needed = True
    if kind is None:
        return None
    return _record(
        kind=kind,
        summary=_summary(
            signal.conversation_label or signal.sender_label or "Mobile message",
            text,
        ),
        counterparty=signal.sender_label or signal.conversation_label,
        due_at=_deadline(text, local_now=local_now, zone=zone),
        confidence=confidence,
        response_needed=response_needed,
        source=CommitmentSource.MOBILE,
        source_id=str(signal.event_id),
        excerpt=text,
        observed_at=signal.occurred_at,
        now=local_now,
    )

def _record(
    *,
    kind: CommitmentKind,
    summary: str,
    counterparty: str | None,
    due_at: datetime | None,
    confidence: float,
    response_needed: bool,
    source: CommitmentSource,
    source_id: str,
    excerpt: str,
    observed_at: datetime,
    now: datetime,
) -> CommitmentRecord:
    status, priority = _status_priority(
        due_at=due_at,
        response_needed=response_needed,
        now=now,
    )
    normalized_excerpt = " ".join(excerpt.split())[:800]
    evidence_hash = hashlib.sha256(
        (
            f"{source.value}|{source_id}|{normalized_excerpt}|"
            f"{observed_at.isoformat()}"
        ).encode()
    ).hexdigest()
    evidence = CommitmentEvidence(
        source=source,
        source_id=source_id,
        counterparty=counterparty,
        excerpt=normalized_excerpt,
        observed_at=observed_at.astimezone(UTC),
        evidence_sha256=evidence_hash,
    )
    return CommitmentRecord(
        kind=kind,
        summary=summary,
        counterparty=counterparty,
        due_at=due_at,
        priority=priority,
        status=status,
        confidence=confidence,
        evidence=(evidence,),
        response_needed=response_needed,
        source_count=1,
    )

def _deadline(
    text: str,
    *,
    local_now: datetime,
    zone: ZoneInfo,
) -> datetime | None:
    folded = text.casefold()
    target_date = None
    if "tomorrow" in folded:
        target_date = local_now.date() + timedelta(days=1)
    elif "today" in folded or "eod" in folded or "end of day" in folded:
        target_date = local_now.date()
    iso = _ISO_DATE.search(text)
    if iso:
        try:
            target_date = date(
                int(iso.group(1)),
                int(iso.group(2)),
                int(iso.group(3)),
            )
        except ValueError:
            target_date = None
    month = _MONTH_DATE.search(text)
    if month:
        try:
            target_date = date(
                int(month.group(3) or local_now.year),
                _MONTHS[month.group(1)[:3].casefold()],
                int(month.group(2)),
            )
        except ValueError:
            target_date = None
    target_time = time(hour=17)
    time_match = _BY_TIME.search(text)
    if time_match:
        hour = int(time_match.group(1)) % 12
        if time_match.group(3).casefold() == "pm":
            hour += 12
        target_time = time(hour=hour, minute=int(time_match.group(2) or 0))
        target_date = target_date or local_now.date()
    if target_date is None:
        return None
    return datetime.combine(target_date, target_time, tzinfo=zone)

def _status_priority(
    *,
    due_at: datetime | None,
    response_needed: bool,
    now: datetime,
) -> tuple[CommitmentStatus, CommitmentPriority]:
    if due_at is not None:
        local_due = due_at.astimezone(now.tzinfo)
        if local_due < now:
            return CommitmentStatus.OVERDUE, CommitmentPriority.CRITICAL
        if local_due <= now + timedelta(hours=24):
            return CommitmentStatus.OPEN, CommitmentPriority.HIGH
        if local_due <= now + timedelta(days=3):
            return CommitmentStatus.OPEN, CommitmentPriority.MEDIUM
    if response_needed:
        return CommitmentStatus.OPEN, CommitmentPriority.MEDIUM
    return CommitmentStatus.OPEN, CommitmentPriority.LOW

def _summary(subject: str, text: str) -> str:
    subject = " ".join(subject.split()).strip()
    body = " ".join(text.split()).strip()
    if subject and subject != "(no subject)":
        return subject[:500]
    if not body:
        return "Communication follow-up"
    return re.split(r"(?<=[.!?])\s+", body, maxsplit=1)[0][:500]

def _deduplicate(records: list[CommitmentRecord]) -> tuple[CommitmentRecord, ...]:
    merged: dict[tuple[CommitmentKind, str, str], CommitmentRecord] = {}
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    for record in records:
        key = (
            record.kind,
            (record.counterparty or "").casefold(),
            re.sub(r"\W+", " ", record.summary.casefold()).strip()[:120],
        )
        existing = merged.get(key)
        if existing is None:
            merged[key] = record
            continue
        evidence_by_hash = {
            item.evidence_sha256: item
            for item in (*existing.evidence, *record.evidence)
        }
        due_candidates = [
            value
            for value in (existing.due_at, record.due_at)
            if value is not None
        ]
        priority = min(
            (existing.priority, record.priority),
            key=lambda value: order[value.value],
        )
        merged[key] = existing.model_copy(
            update={
                "due_at": min(due_candidates) if due_candidates else None,
                "confidence": max(existing.confidence, record.confidence),
                "evidence": tuple(evidence_by_hash.values()),
                "source_count": len(evidence_by_hash),
                "response_needed": (
                    existing.response_needed or record.response_needed
                ),
                "priority": priority,
            }
        )
    return tuple(
        sorted(
            merged.values(),
            key=lambda item: (
                order[item.priority.value],
                item.due_at or datetime.max.replace(tzinfo=UTC),
            ),
        )
    )
