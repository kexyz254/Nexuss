"""Stateful, replay-resistant Nexuss collaboration protocol."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import BaseModel, ValidationError

from nexuss.collaboration.crypto import (
    ZERO_HASH,
    build_message_hash,
    sha256_json,
)
from nexuss.collaboration.models import (
    ActionPlanPayload,
    ApprovalStatePayload,
    CapabilityLeasePayload,
    CollaborationSession,
    CollaborationState,
    EvidencePayload,
    FinalResponsePayload,
    IntentPayload,
    MessageKind,
    ProtocolMessage,
    ProtocolSender,
    StopPayload,
)
from nexuss.collaboration.store import SQLiteCollaborationStore


class CollaborationProtocolError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


_PAYLOAD_MODELS: dict[MessageKind, type[BaseModel]] = {
    MessageKind.INTENT: IntentPayload,
    MessageKind.CAPABILITY_LEASE: CapabilityLeasePayload,
    MessageKind.ACTION_PLAN: ActionPlanPayload,
    MessageKind.EVIDENCE: EvidencePayload,
    MessageKind.APPROVAL_STATE: ApprovalStatePayload,
    MessageKind.FINAL_RESPONSE: FinalResponsePayload,
    MessageKind.STOP: StopPayload,
}

_ALLOWED_TRANSITIONS: dict[
    tuple[ProtocolSender, MessageKind],
    set[tuple[ProtocolSender, MessageKind]],
] = {
    (ProtocolSender.NEXUSS, MessageKind.INTENT): {
        (ProtocolSender.NEXUSS, MessageKind.CAPABILITY_LEASE),
    },
    (ProtocolSender.NEXUSS, MessageKind.CAPABILITY_LEASE): {
        (ProtocolSender.PROVIDER, MessageKind.ACTION_PLAN),
        (ProtocolSender.PROVIDER, MessageKind.FINAL_RESPONSE),
        (ProtocolSender.PROVIDER, MessageKind.STOP),
    },
    (ProtocolSender.PROVIDER, MessageKind.ACTION_PLAN): {
        (ProtocolSender.NEXUSS, MessageKind.EVIDENCE),
        (ProtocolSender.NEXUSS, MessageKind.APPROVAL_STATE),
        (ProtocolSender.NEXUSS, MessageKind.STOP),
    },
    (ProtocolSender.NEXUSS, MessageKind.EVIDENCE): {
        (ProtocolSender.PROVIDER, MessageKind.ACTION_PLAN),
        (ProtocolSender.PROVIDER, MessageKind.FINAL_RESPONSE),
        (ProtocolSender.PROVIDER, MessageKind.STOP),
    },
    (ProtocolSender.NEXUSS, MessageKind.APPROVAL_STATE): {
        (ProtocolSender.PROVIDER, MessageKind.ACTION_PLAN),
        (ProtocolSender.PROVIDER, MessageKind.FINAL_RESPONSE),
        (ProtocolSender.PROVIDER, MessageKind.STOP),
    },
}


class CollaborationProtocolService:
    def __init__(
        self,
        *,
        store: SQLiteCollaborationStore,
        message_ttl_seconds: int = 300,
        session_ttl_seconds: int = 3_600,
    ) -> None:
        self._store = store
        self._message_ttl = timedelta(
            seconds=message_ttl_seconds
        )
        self._session_ttl = timedelta(
            seconds=session_ttl_seconds
        )

    def create_session(
        self,
        *,
        request_id: UUID,
        user_session_id: UUID,
        provider_id: str,
        model: str,
        intent: IntentPayload,
        lease: CapabilityLeasePayload,
    ) -> tuple[
        CollaborationSession,
        ProtocolMessage,
        ProtocolMessage,
    ]:
        existing = self._store.get_by_request(request_id)
        if existing is not None:
            messages = self._store.messages(existing.session_id)
            if len(messages) < 2:
                raise CollaborationProtocolError(
                    "NCP_SESSION_INCOMPLETE",
                    "Existing protocol session is incomplete.",
                )
            return existing, messages[0], messages[1]

        now = datetime.now(UTC)
        session_id = uuid4()
        session = CollaborationSession(
            session_id=session_id,
            request_id=request_id,
            user_session_id=user_session_id,
            provider_id=provider_id,
            model=model,
            state=CollaborationState.WAITING_FOR_PROVIDER,
            next_sequence=1,
            maximum_rounds=intent.maximum_rounds,
            completed_rounds=0,
            last_message_sha256=ZERO_HASH,
            created_at=now,
            updated_at=now,
            expires_at=now + self._session_ttl,
        )
        self._store.save_session(session)

        intent_message, session = self._append(
            session=session,
            sender=ProtocolSender.NEXUSS,
            kind=MessageKind.INTENT,
            payload=intent,
            reply_to_message_id=None,
        )
        lease_message, session = self._append(
            session=session,
            sender=ProtocolSender.NEXUSS,
            kind=MessageKind.CAPABILITY_LEASE,
            payload=lease,
            reply_to_message_id=intent_message.message_id,
        )
        return session, intent_message, lease_message

    def accept_provider_message(
        self,
        *,
        session_id: UUID,
        kind: MessageKind,
        payload: BaseModel,
        reply_to_message_id: UUID,
    ) -> tuple[CollaborationSession, ProtocolMessage]:
        session = self._required_session(session_id)
        self._assert_not_expired(session)
        if session.state is not CollaborationState.WAITING_FOR_PROVIDER:
            raise CollaborationProtocolError(
                "NCP_PROVIDER_TURN_NOT_EXPECTED",
                "Nexuss is not waiting for a provider message.",
            )
        if kind not in {
            MessageKind.ACTION_PLAN,
            MessageKind.FINAL_RESPONSE,
            MessageKind.STOP,
        }:
            raise CollaborationProtocolError(
                "NCP_PROVIDER_MESSAGE_KIND_DENIED",
                f"Provider message kind {kind.value!r} is denied.",
            )
        self._validate_payload(kind, payload)

        message, updated = self._append(
            session=session,
            sender=ProtocolSender.PROVIDER,
            kind=kind,
            payload=payload,
            reply_to_message_id=reply_to_message_id,
        )

        state = CollaborationState.WAITING_FOR_NEXUSS
        rounds = updated.completed_rounds
        if kind is MessageKind.ACTION_PLAN:
            rounds += 1
            if rounds > updated.maximum_rounds:
                raise CollaborationProtocolError(
                    "NCP_ROUND_BUDGET_EXHAUSTED",
                    "Provider exceeded the collaboration round budget.",
                )
        elif kind is MessageKind.FINAL_RESPONSE:
            state = CollaborationState.COMPLETED
        elif kind is MessageKind.STOP:
            state = CollaborationState.FAILED

        updated = updated.model_copy(
            update={
                "state": state,
                "completed_rounds": rounds,
                "updated_at": datetime.now(UTC),
            }
        )
        self._store.save_session(updated)
        return updated, message

    def send_nexuss_message(
        self,
        *,
        session_id: UUID,
        kind: MessageKind,
        payload: BaseModel,
        reply_to_message_id: UUID,
    ) -> tuple[CollaborationSession, ProtocolMessage]:
        session = self._required_session(session_id)
        self._assert_not_expired(session)
        if session.state is not CollaborationState.WAITING_FOR_NEXUSS:
            raise CollaborationProtocolError(
                "NCP_NEXUSS_TURN_NOT_EXPECTED",
                "Nexuss is not expected to send the next message.",
            )
        if kind not in {
            MessageKind.EVIDENCE,
            MessageKind.APPROVAL_STATE,
            MessageKind.STOP,
        }:
            raise CollaborationProtocolError(
                "NCP_NEXUSS_MESSAGE_KIND_DENIED",
                f"Nexuss message kind {kind.value!r} is denied.",
            )
        self._validate_payload(kind, payload)

        message, updated = self._append(
            session=session,
            sender=ProtocolSender.NEXUSS,
            kind=kind,
            payload=payload,
            reply_to_message_id=reply_to_message_id,
        )

        state = (
            CollaborationState.FAILED
            if kind is MessageKind.STOP
            else (
                CollaborationState.AWAITING_APPROVAL
                if kind is MessageKind.APPROVAL_STATE
                else CollaborationState.WAITING_FOR_PROVIDER
            )
        )
        if kind is MessageKind.APPROVAL_STATE:
            approval = ApprovalStatePayload.model_validate(payload)
            if approval.state in {"approved", "denied", "expired"}:
                state = CollaborationState.WAITING_FOR_PROVIDER

        updated = updated.model_copy(
            update={
                "state": state,
                "updated_at": datetime.now(UTC),
            }
        )
        self._store.save_session(updated)
        return updated, message

    def transcript(
        self,
        session_id: UUID,
    ) -> tuple[ProtocolMessage, ...]:
        self._required_session(session_id)
        messages = self._store.messages(session_id)
        previous = ZERO_HASH
        for expected_sequence, message in enumerate(messages, start=1):
            if message.sequence != expected_sequence:
                raise CollaborationProtocolError(
                    "NCP_SEQUENCE_GAP",
                    "Protocol transcript contains a sequence gap.",
                )
            if message.previous_message_sha256 != previous:
                raise CollaborationProtocolError(
                    "NCP_HASH_CHAIN_INVALID",
                    "Protocol transcript hash chain is invalid.",
                )
            recalculated = build_message_hash(
                header=self._header(message),
                payload_sha256=message.payload_sha256,
                previous_message_sha256=(
                    message.previous_message_sha256
                ),
            )
            if recalculated != message.message_sha256:
                raise CollaborationProtocolError(
                    "NCP_MESSAGE_HASH_INVALID",
                    "Protocol message integrity check failed.",
                )
            previous = message.message_sha256
        return messages

    def _append(
        self,
        *,
        session: CollaborationSession,
        sender: ProtocolSender,
        kind: MessageKind,
        payload: BaseModel,
        reply_to_message_id: UUID | None,
    ) -> tuple[ProtocolMessage, CollaborationSession]:
        messages = self._store.messages(session.session_id)
        if messages:
            last = messages[-1]
            allowed = _ALLOWED_TRANSITIONS.get(
                (last.sender, last.kind),
                set(),
            )
            if (sender, kind) not in allowed:
                raise CollaborationProtocolError(
                    "NCP_TRANSITION_DENIED",
                    (
                        f"Protocol transition {last.sender.value}/"
                        f"{last.kind.value} -> {sender.value}/"
                        f"{kind.value} is denied."
                    ),
                )
            if reply_to_message_id != last.message_id:
                raise CollaborationProtocolError(
                    "NCP_REPLY_BINDING_INVALID",
                    "Message must reply to the current protocol turn.",
                )

        issued_at = datetime.now(UTC)
        payload_dict = payload.model_dump(mode="json")
        payload_hash = sha256_json(payload_dict)
        header = {
            "protocol_version": "ncp/1.0",
            "message_id": str(uuid4()),
            "session_id": str(session.session_id),
            "request_id": str(session.request_id),
            "sender": sender.value,
            "kind": kind.value,
            "sequence": session.next_sequence,
            "reply_to_message_id": (
                str(reply_to_message_id)
                if reply_to_message_id
                else None
            ),
            "provider_id": session.provider_id,
            "model": session.model,
            "issued_at": issued_at.isoformat(),
            "expires_at": (
                issued_at + self._message_ttl
            ).isoformat(),
            "nonce": str(uuid4()),
        }
        message_hash = build_message_hash(
            header=header,
            payload_sha256=payload_hash,
            previous_message_sha256=(
                session.last_message_sha256
            ),
        )
        message = ProtocolMessage(
            **header,
            payload=payload_dict,
            payload_sha256=payload_hash,
            previous_message_sha256=(
                session.last_message_sha256
            ),
            message_sha256=message_hash,
        )
        self._store.append_message(message)
        updated = session.model_copy(
            update={
                "next_sequence": session.next_sequence + 1,
                "last_message_sha256": message_hash,
                "updated_at": issued_at,
            }
        )
        self._store.save_session(updated)
        return message, updated

    def _required_session(
        self,
        session_id: UUID,
    ) -> CollaborationSession:
        session = self._store.get_session(session_id)
        if session is None:
            raise CollaborationProtocolError(
                "NCP_SESSION_NOT_FOUND",
                "Collaboration session was not found.",
            )
        return session

    @staticmethod
    def _assert_not_expired(
        session: CollaborationSession,
    ) -> None:
        if session.expires_at <= datetime.now(UTC):
            raise CollaborationProtocolError(
                "NCP_SESSION_EXPIRED",
                "Collaboration session has expired.",
            )

    @staticmethod
    def _validate_payload(
        kind: MessageKind,
        payload: BaseModel,
    ) -> None:
        model = _PAYLOAD_MODELS.get(kind)
        if model is None:
            raise CollaborationProtocolError(
                "NCP_PAYLOAD_KIND_UNSUPPORTED",
                f"No payload schema exists for {kind.value!r}.",
            )
        try:
            model.model_validate(payload)
        except ValidationError as exc:
            raise CollaborationProtocolError(
                "NCP_PAYLOAD_SCHEMA_INVALID",
                "Protocol payload failed strict validation.",
            ) from exc

    @staticmethod
    def _header(message: ProtocolMessage) -> dict[str, object]:
        return {
            "protocol_version": message.protocol_version,
            "message_id": str(message.message_id),
            "session_id": str(message.session_id),
            "request_id": str(message.request_id),
            "sender": message.sender.value,
            "kind": message.kind.value,
            "sequence": message.sequence,
            "reply_to_message_id": (
                str(message.reply_to_message_id)
                if message.reply_to_message_id
                else None
            ),
            "provider_id": message.provider_id,
            "model": message.model,
            "issued_at": message.issued_at.isoformat(),
            "expires_at": message.expires_at.isoformat(),
            "nonce": str(message.nonce),
        }
