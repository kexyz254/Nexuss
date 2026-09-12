'''Provider-neutral planning and bounded autonomy API.'''

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request, status

from nexuss.ai.connections import AIProviderConnectionError, AIProviderConnectionResolver
from nexuss.ai.registry import AIProviderRegistryError, default_provider_registry
from nexuss.capabilities.broker import CapabilityBroker, CapabilityBrokerError
from nexuss.core.service import CoreSimulatorService
from nexuss.orchestration.autonomy import (
    BoundedAutonomyError,
    BoundedAutonomyService,
    certified_autonomy_capabilities,
)
from nexuss.orchestration.autonomy_models import AutonomousRunRequest, AutonomousRunResponse
from nexuss.orchestration.autonomy_store import SQLiteAutonomyStore
from nexuss.orchestration.models import (
    ActionPlanReceipt,
    UniversalActionPlanRequest,
    UniversalActionPlanResponse,
)
from nexuss.orchestration.receipt import build_action_plan_receipt
from nexuss.orchestration.service import UniversalActionPlanningError, UniversalActionPlanningService
from nexuss.orchestration.store import SQLiteOrchestrationStore


def register_orchestration_routes(
    app: FastAPI,
    *,
    require_local_control: Callable[[Request], None],
    core_service: CoreSimulatorService,
) -> None:
    providers = default_provider_registry()
    planning_store = SQLiteOrchestrationStore()
    autonomy_store = SQLiteAutonomyStore(planning_store)
    autonomy = BoundedAutonomyService(core_service=core_service)

    def validate_session(expected: UUID, actual: UUID, authenticated: bool) -> None:
        if not authenticated or expected != actual:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authenticated session does not match the request.",
            )

    def build_plan(request: UniversalActionPlanRequest) -> UniversalActionPlanResponse:
        existing = planning_store.get_by_request(request.request_id)
        if existing is not None:
            return existing
        provider = providers.select(provider_id=request.provider_id, mode=request.mode)
        resolved = AIProviderConnectionResolver().resolve(
            profile=provider,
            request_id=request.request_id,
            instruction=request.instruction,
            external_processing_approved=request.external_processing_approved,
        )
        broker = CapabilityBroker(maximum_actions=request.maximum_actions)
        service = UniversalActionPlanningService(
            provider=provider,
            model=resolved.model,
            proposer=resolved.proposer,
            broker=broker,
        )
        envelope, catalog = service.plan(instruction=request.instruction, mode=request.mode)
        receipt = build_action_plan_receipt(
            request_id=request.request_id,
            instruction=request.instruction,
            capability_catalog=catalog,
            envelope=envelope,
        )
        response = UniversalActionPlanResponse(envelope=envelope, receipt=receipt)
        planning_store.save(response)
        return response

    @app.get("/v1/ai/providers")
    def list_ai_providers() -> dict[str, object]:
        return {
            "providers": [profile.model_dump(mode="json") for profile in providers.list_profiles()],
            "automatic_fallback_enabled": False,
        }

    @app.get("/v1/ai/capabilities")
    def list_provider_visible_capabilities(http_request: Request) -> dict[str, object]:
        require_local_control(http_request)
        broker = CapabilityBroker()
        return {
            "capabilities": [item.model_dump(mode="json") for item in broker.catalog()],
            "provider_direct_execution": False,
            "bounded_autonomy": certified_autonomy_capabilities(),
        }

    @app.post("/v1/orchestrations/plans", response_model=UniversalActionPlanResponse)
    def create_action_plan(
        plan_request: UniversalActionPlanRequest,
        http_request: Request,
        session_id: Annotated[UUID, Header(alias="X-Nexuss-Session-ID")],
        session_authenticated: Annotated[bool, Header(alias="X-Nexuss-Session-Authenticated")],
    ) -> UniversalActionPlanResponse:
        require_local_control(http_request)
        validate_session(plan_request.user_session_id, session_id, session_authenticated)
        try:
            return build_plan(plan_request)
        except (AIProviderRegistryError, AIProviderConnectionError, CapabilityBrokerError, UniversalActionPlanningError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": exc.code, "message": str(exc), "execution_authorized": False},
            ) from exc

    @app.post("/v1/orchestrations/autonomous", response_model=AutonomousRunResponse)
    def create_autonomous_run(
        run_request: AutonomousRunRequest,
        http_request: Request,
        session_id: Annotated[UUID, Header(alias="X-Nexuss-Session-ID")],
        session_authenticated: Annotated[bool, Header(alias="X-Nexuss-Session-Authenticated")],
    ) -> AutonomousRunResponse:
        require_local_control(http_request)
        validate_session(run_request.user_session_id, session_id, session_authenticated)
        existing = autonomy_store.get_by_request(run_request.request_id)
        if existing is not None:
            return existing
        try:
            planning = build_plan(UniversalActionPlanRequest(
                request_id=run_request.request_id,
                user_session_id=run_request.user_session_id,
                instruction=run_request.instruction,
                mode=run_request.provider_mode,
                provider_id=run_request.provider_id,
                external_processing_approved=run_request.external_processing_approved,
                maximum_actions=run_request.maximum_actions,
            ))
            response = autonomy.run(
                planning=planning,
                user_session_id=run_request.user_session_id,
                autonomy_mode=run_request.autonomy_mode,
                maximum_runtime_seconds=run_request.maximum_runtime_seconds,
            )
            autonomy_store.save(response)
            return response
        except (AIProviderRegistryError, AIProviderConnectionError, CapabilityBrokerError, UniversalActionPlanningError, BoundedAutonomyError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": exc.code, "message": str(exc), "protected_auto_approval": False},
            ) from exc

    @app.get("/v1/orchestrations/autonomous/{run_id}", response_model=AutonomousRunResponse)
    def get_autonomous_run(run_id: UUID, http_request: Request) -> AutonomousRunResponse:
        require_local_control(http_request)
        response = autonomy_store.get_by_run(run_id)
        if response is None:
            raise HTTPException(status_code=404, detail="Autonomous run was not found.")
        return response

    @app.get("/v1/orchestrations/plans/{request_id}", response_model=UniversalActionPlanResponse)
    def get_action_plan(request_id: UUID, http_request: Request) -> UniversalActionPlanResponse:
        require_local_control(http_request)
        response = planning_store.get_by_request(request_id)
        if response is None:
            raise HTTPException(status_code=404, detail="Orchestration action plan was not found.")
        return response

    @app.get("/v1/orchestrations/receipts/{receipt_id}", response_model=ActionPlanReceipt)
    def get_action_plan_receipt(receipt_id: UUID, http_request: Request) -> ActionPlanReceipt:
        require_local_control(http_request)
        response = planning_store.get_by_receipt(receipt_id)
        if response is None:
            raise HTTPException(status_code=404, detail="Orchestration receipt was not found.")
        return response.receipt
