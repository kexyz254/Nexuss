"""Core service for authenticated mobile communication signals and actions."""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from threading import RLock
from uuid import UUID, uuid4

from nexuss.mobile_fabric.models import (
    MobileActionDecision,
    MobileActionEvidence,
    MobileActionKind,
    MobileActionPrepareRequest,
    MobileActionProposal,
    MobileActionState,
    MobileActionView,
    MobileAttentionSummary,
    MobileCapabilityMatrix,
    MobileDecisionKind,
    MobileFeedSnapshot,
    MobileSignalBatch,
    MobileSignalIngestResult,
    MobileSignalKind,
    MobileSource,
)
from nexuss.mobile_fabric.policy import MobilePolicy, MobilePolicyError
from nexuss.mobile_fabric.store import MobileSignalStore


class MobileFabricError(RuntimeError):
    """Raised when a mobile-fabric operation fails closed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class _ActionRecord:
    proposal: MobileActionProposal
    token_sha256: str
    decision: MobileDecisionKind | None = None
    decided_at: datetime | None = None
    evidence: MobileActionEvidence | None = None


class MobileFabricService:
    def __init__(
        self,
        *,
        policy: MobilePolicy | None = None,
        signals: MobileSignalStore | None = None,
    ) -> None:
        self._policy = policy or MobilePolicy.default()
        self._signals = signals or MobileSignalStore()
        self._actions: dict[UUID, _ActionRecord] = {}
        self._lock = RLock()

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _canonical_action_payload(request: MobileActionPrepareRequest) -> bytes:
        payload = {
            "request_id": str(request.request_id),
            "device_id": str(request.device_id),
            "kind": request.kind.value,
            "source": request.source.value,
            "target_label": request.target_label,
            "destination": request.destination,
            "body": request.body,
            "notification_key": request.notification_key,
        }
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    @staticmethod
    def _preview(request: MobileActionPrepareRequest) -> str:
        if request.kind is MobileActionKind.DIAL_HANDOFF:
            return (
                f"Open the phone dialer for {request.destination}. "
                "No call is placed automatically."
            )
        if request.kind is MobileActionKind.SMS_COMPOSE:
            return (
                f"Open SMS composer for {request.destination} with exact body:\n"
                f"{request.body}"
            )
        if request.kind is MobileActionKind.NOTIFICATION_REPLY:
            return (
                f"Reply through {request.source.value} notification "
                f"{request.notification_key} to {request.target_label}:\n{request.body}"
            )
        return (
            f"Open {request.source.value} conversation {request.target_label} "
            f"from notification {request.notification_key}."
        )

    def ingest(
        self,
        *,
        device_id: UUID,
        batch: MobileSignalBatch,
    ) -> MobileSignalIngestResult:
        normalized = []
        rejected = 0
        for signal in batch.signals:
            try:
                normalized.append(self._policy.normalize_signal(signal))
            except MobilePolicyError:
                rejected += 1
        result = self._signals.insert(device_id, tuple(normalized))
        return MobileSignalIngestResult(
            batch_id=batch.batch_id,
            accepted=result.accepted,
            duplicates=result.duplicates,
            rejected=rejected,
            latest_cursor=result.latest_cursor,
            device_id=device_id,
        )

    def feed(
        self,
        *,
        after_cursor: int = 0,
        limit: int = 100,
        source: MobileSource | None = None,
    ) -> MobileFeedSnapshot:
        if after_cursor < 0:
            raise MobileFabricError("MOBILE_CURSOR_INVALID", "Cursor cannot be negative.")
        if not 1 <= limit <= 500:
            raise MobileFabricError("MOBILE_LIMIT_INVALID", "Limit must be 1-500.")
        items = self._signals.list(after_cursor=after_cursor, limit=500)
        if source is not None:
            items = tuple(item for item in items if item.signal.source is source)
        items = items[-limit:]
        sources = tuple(sorted({item.signal.source for item in items}, key=str))
        return MobileFeedSnapshot(
            items=items,
            latest_cursor=self._signals.latest_cursor(),
            total_available=self._signals.total(),
            sources=sources,
        )

    def attention_summary(self, *, limit: int = 12) -> MobileAttentionSummary:
        snapshot = self.feed(limit=500)
        source_counts = {source: 0 for source in MobileSource}
        unread_like_messages = 0
        missed_calls = 0
        reply_capable = 0
        for item in snapshot.items:
            signal = item.signal
            source_counts[signal.source] += 1
            if signal.kind is MobileSignalKind.MESSAGE_RECEIVED:
                unread_like_messages += 1
            if signal.kind is MobileSignalKind.MISSED_CALL:
                missed_calls += 1
            if signal.reply_supported:
                reply_capable += 1
        return MobileAttentionSummary(
            total_signals=len(snapshot.items),
            unread_like_messages=unread_like_messages,
            missed_calls=missed_calls,
            reply_capable_notifications=reply_capable,
            source_counts=source_counts,
            latest_items=snapshot.items[-limit:],
        )

    def capabilities(self) -> MobileCapabilityMatrix:
        return self._policy.capability_matrix()

    def prepare_action(
        self,
        request: MobileActionPrepareRequest,
        *,
        now: datetime | None = None,
    ) -> MobileActionView:
        prepared_at = now or datetime.now(UTC)
        try:
            self._policy.validate_action(request.kind, request.source)
        except MobilePolicyError as exc:
            raise MobileFabricError(str(exc), str(exc)) from exc

        token = secrets.token_urlsafe(32)
        payload_sha256 = hashlib.sha256(
            self._canonical_action_payload(request)
        ).hexdigest()
        proposal = MobileActionProposal(
            action_id=uuid4(),
            request_id=request.request_id,
            device_id=request.device_id,
            kind=request.kind,
            source=request.source,
            target_label=request.target_label,
            destination=request.destination,
            body=request.body,
            notification_key=request.notification_key,
            exact_preview=self._preview(request),
            payload_sha256=payload_sha256,
            approval_token=token,
            state=MobileActionState.PREPARED,
            created_at=prepared_at,
            expires_at=prepared_at + timedelta(seconds=request.expires_in_seconds),
        )
        with self._lock:
            self._actions[proposal.action_id] = _ActionRecord(
                proposal=proposal,
                token_sha256=self._token_hash(token),
            )
        return MobileActionView(proposal=proposal, state=proposal.state)

    def pending(
        self,
        device_id: UUID,
        *,
        now: datetime | None = None,
    ) -> tuple[MobileActionView, ...]:
        observed_at = now or datetime.now(UTC)
        views = []
        with self._lock:
            for action_id, record in tuple(self._actions.items()):
                record = self._expire_if_needed(action_id, record, observed_at)
                if (
                    record.proposal.device_id == device_id
                    and record.proposal.state is MobileActionState.PREPARED
                ):
                    views.append(self._view(record))
        return tuple(sorted(views, key=lambda item: item.proposal.created_at))

    def decide(
        self,
        *,
        device_id: UUID,
        action_id: UUID,
        decision: MobileActionDecision,
        now: datetime | None = None,
    ) -> MobileActionView:
        observed_at = now or datetime.now(UTC)
        with self._lock:
            record = self._require_action(action_id)
            record = self._expire_if_needed(action_id, record, observed_at)
            if record.proposal.device_id != device_id:
                raise MobileFabricError("MOBILE_ACTION_DEVICE_MISMATCH", "Wrong trusted device.")
            if record.proposal.state is not MobileActionState.PREPARED:
                raise MobileFabricError("MOBILE_ACTION_NOT_PENDING", "Action is not pending.")
            if record.proposal.payload_sha256 != decision.payload_sha256:
                raise MobileFabricError("MOBILE_ACTION_PAYLOAD_MISMATCH", "Payload hash mismatch.")
            if self._token_hash(decision.approval_token) != record.token_sha256:
                raise MobileFabricError("MOBILE_ACTION_TOKEN_INVALID", "Approval token invalid.")
            if decision.decision is MobileDecisionKind.APPROVE and not decision.biometric_verified:
                raise MobileFabricError(
                    "MOBILE_BIOMETRIC_REQUIRED",
                    "On-device biometric or device-credential confirmation is required.",
                )
            state = (
                MobileActionState.APPROVED
                if decision.decision is MobileDecisionKind.APPROVE
                else MobileActionState.REJECTED
            )
            proposal = record.proposal.model_copy(update={"state": state})
            updated = replace(
                record,
                proposal=proposal,
                decision=decision.decision,
                decided_at=decision.decided_at,
            )
            self._actions[action_id] = updated
            return self._view(updated)

    def approved(
        self,
        device_id: UUID,
        *,
        now: datetime | None = None,
    ) -> tuple[MobileActionView, ...]:
        observed_at = now or datetime.now(UTC)
        views = []
        with self._lock:
            for action_id, record in tuple(self._actions.items()):
                record = self._expire_if_needed(action_id, record, observed_at)
                if (
                    record.proposal.device_id == device_id
                    and record.proposal.state is MobileActionState.APPROVED
                ):
                    views.append(self._view(record))
        return tuple(sorted(views, key=lambda item: item.proposal.created_at))

    def record_evidence(
        self,
        *,
        device_id: UUID,
        action_id: UUID,
        evidence: MobileActionEvidence,
    ) -> MobileActionView:
        with self._lock:
            record = self._require_action(action_id)
            if record.proposal.device_id != device_id:
                raise MobileFabricError("MOBILE_ACTION_DEVICE_MISMATCH", "Wrong trusted device.")
            if record.proposal.state is not MobileActionState.APPROVED:
                raise MobileFabricError("MOBILE_ACTION_NOT_APPROVED", "Action is not approved.")
            if evidence.action_id != action_id:
                raise MobileFabricError("MOBILE_EVIDENCE_ACTION_MISMATCH", "Action ID mismatch.")
            if evidence.payload_sha256 != record.proposal.payload_sha256:
                raise MobileFabricError(
                    "MOBILE_EVIDENCE_PAYLOAD_MISMATCH",
                    "Payload hash mismatch.",
                )
            state = MobileActionState.VERIFIED if evidence.executed else MobileActionState.FAILED
            proposal = record.proposal.model_copy(update={"state": state})
            updated = replace(record, proposal=proposal, evidence=evidence)
            self._actions[action_id] = updated
            return self._view(updated)

    def get_action(self, action_id: UUID) -> MobileActionView:
        with self._lock:
            return self._view(self._require_action(action_id))

    def _require_action(self, action_id: UUID) -> _ActionRecord:
        try:
            return self._actions[action_id]
        except KeyError as exc:
            raise MobileFabricError("MOBILE_ACTION_NOT_FOUND", "Action not found.") from exc

    def _expire_if_needed(
        self,
        action_id: UUID,
        record: _ActionRecord,
        observed_at: datetime,
    ) -> _ActionRecord:
        if (
            record.proposal.state is MobileActionState.PREPARED
            and record.proposal.expires_at <= observed_at
        ):
            proposal = record.proposal.model_copy(update={"state": MobileActionState.EXPIRED})
            record = replace(record, proposal=proposal)
            self._actions[action_id] = record
        return record

    @staticmethod
    def _view(record: _ActionRecord) -> MobileActionView:
        external_write = bool(
            record.evidence and record.evidence.external_write_performed
        )
        verified = record.proposal.state is MobileActionState.VERIFIED
        return MobileActionView(
            proposal=record.proposal,
            state=record.proposal.state,
            decision=record.decision,
            decided_at=record.decided_at,
            evidence=record.evidence,
            external_write_performed=external_write,
            verified=verified,
        )
