"""Authenticated proactive schedule and alert APIs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request, status

from nexuss.conversation.store import SQLiteConversationStore
from nexuss.proactive.models import AlertRecord, CreateScheduleRequest, ScheduleRecord
from nexuss.proactive.scheduler import ProactiveScheduler
from nexuss.proactive.store import ProactiveStoreError, SQLiteProactiveStore
from nexuss.work.store import SQLiteWorkStore


def register_proactive_routes(
    app: FastAPI,
    *,
    require_local_control: Callable[[Request], None],
) -> ProactiveScheduler:
    store = SQLiteProactiveStore()
    work = SQLiteWorkStore()
    conversations = SQLiteConversationStore()
    scheduler = ProactiveScheduler(
        proactive_store=store,
        work_store=work,
        conversation_store=conversations,
    )

    def require_session(authenticated: bool) -> None:
        if not authenticated:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authenticated session is required.",
            )

    def validate_conversation(conversation_id: UUID, session_id: UUID) -> None:
        conversation = conversations.get(conversation_id)
        if conversation is None or conversation.user_session_id != session_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation was not found for this session.",
            )

    @app.post("/v1/proactive/schedules", response_model=ScheduleRecord, status_code=201)
    def create_schedule(
        body: CreateScheduleRequest,
        request: Request,
        session_id: Annotated[UUID, Header(alias="X-Nexuss-Session-ID")],
        authenticated: Annotated[bool, Header(alias="X-Nexuss-Session-Authenticated")],
    ) -> ScheduleRecord:
        require_local_control(request)
        require_session(authenticated)
        validate_conversation(body.conversation_id, session_id)
        try:
            return store.create_schedule(
                conversation_id=body.conversation_id,
                user_session_id=session_id,
                title=body.title,
                prompt=body.prompt,
                next_run_at=body.next_run_at,
                interval_seconds=body.interval_seconds,
            )
        except ProactiveStoreError as exc:
            raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc

    @app.get("/v1/proactive/schedules", response_model=list[ScheduleRecord])
    def list_schedules(
        request: Request,
        session_id: Annotated[UUID, Header(alias="X-Nexuss-Session-ID")],
        authenticated: Annotated[bool, Header(alias="X-Nexuss-Session-Authenticated")],
    ) -> list[ScheduleRecord]:
        require_local_control(request)
        require_session(authenticated)
        return list(store.list_schedules(session_id))

    @app.get("/v1/proactive/alerts", response_model=list[AlertRecord])
    def list_alerts(
        request: Request,
        session_id: Annotated[UUID, Header(alias="X-Nexuss-Session-ID")],
        authenticated: Annotated[bool, Header(alias="X-Nexuss-Session-Authenticated")],
    ) -> list[AlertRecord]:
        require_local_control(request)
        require_session(authenticated)
        return list(store.unacknowledged_alerts(session_id))

    @app.post("/v1/proactive/alerts/{alert_id}/ack", status_code=204)
    def acknowledge_alert(
        alert_id: UUID,
        request: Request,
        session_id: Annotated[UUID, Header(alias="X-Nexuss-Session-ID")],
        authenticated: Annotated[bool, Header(alias="X-Nexuss-Session-Authenticated")],
    ) -> None:
        require_local_control(request)
        require_session(authenticated)
        if not store.acknowledge(alert_id, session_id):
            raise HTTPException(status_code=404, detail="Alert was not found.")

    app.add_event_handler("startup", scheduler.start)
    app.add_event_handler("shutdown", scheduler.stop)
    return scheduler
