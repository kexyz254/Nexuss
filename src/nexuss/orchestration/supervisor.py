"""Agent registry, task projection, and health supervision for Nexuss."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from nexuss.orchestration.supervisor_models import (
    AgentKind,
    AgentStatus,
    EventSeverity,
    SupervisorAgent,
    SupervisorHeartbeatRequest,
    SupervisorSnapshot,
    SupervisorTaskProjection,
)
from nexuss.orchestration.supervisor_store import SQLiteSupervisorStore


class CoreTaskSource(Protocol):
    def list_tasks(self) -> tuple[object, ...]:
        ...


_TERMINAL_STATES = frozenset(
    {
        "completed",
        "partially_completed",
        "denied",
        "failed",
        "rolled_back",
    }
)

_CAPABILITY_OWNERS: tuple[tuple[str, str], ...] = (
    ("engineering.", "engineering.agent"),
    ("knowledge.", "research.agent"),
    ("media.", "research.agent"),
    ("device.", "device.agent"),
    ("mobile.", "device.agent"),
    ("phone.", "device.agent"),
    ("workspace.", "operations.agent"),
    ("github.", "operations.agent"),
    ("calendar.", "operations.agent"),
    ("email.", "operations.agent"),
    ("commitments.", "core.orchestrator"),
    ("google.", "core.orchestrator"),
    ("memory.", "core.orchestrator"),
    ("assistant.", "core.orchestrator"),
    ("communications.", "core.orchestrator"),
)

_BUILTIN_AGENTS: tuple[dict[str, object], ...] = (
    {
        "agent_id": "core.orchestrator",
        "title": "Core Orchestrator",
        "kind": AgentKind.CORE,
        "capabilities": (
            "assistant.*",
            "memory.*",
            "commitments.*",
            "google.*",
            "communications.*",
        ),
        "dependencies": (),
    },
    {
        "agent_id": "engineering.agent",
        "title": "Engineering Agent",
        "kind": AgentKind.ENGINEERING,
        "capabilities": ("engineering.*",),
        "dependencies": ("core.orchestrator",),
    },
    {
        "agent_id": "research.agent",
        "title": "Research Agent",
        "kind": AgentKind.RESEARCH,
        "capabilities": ("knowledge.*", "media.*"),
        "dependencies": ("core.orchestrator",),
    },
    {
        "agent_id": "device.agent",
        "title": "Device Agent",
        "kind": AgentKind.DEVICE,
        "capabilities": ("device.*", "mobile.*", "phone.*"),
        "dependencies": ("core.orchestrator",),
    },
    {
        "agent_id": "operations.agent",
        "title": "Operations Agent",
        "kind": AgentKind.OPERATIONS,
        "capabilities": ("workspace.*", "github.*", "calendar.*", "email.*"),
        "dependencies": ("core.orchestrator",),
    },
    {
        "agent_id": "collaboration.agent",
        "title": "Collaboration Agent",
        "kind": AgentKind.COLLABORATION,
        "capabilities": ("collaboration.protocol",),
        "dependencies": ("core.orchestrator",),
    },
)


class AgentSupervisorError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _state_value(value: object) -> str:
    raw = getattr(value, "value", value)
    return str(raw)


class AgentSupervisorService:
    def __init__(
        self,
        *,
        core_service: CoreTaskSource,
        store: SQLiteSupervisorStore | None = None,
    ) -> None:
        self._core = core_service
        self._store = store or SQLiteSupervisorStore()
        self._ensure_builtins()

    @property
    def store(self) -> SQLiteSupervisorStore:
        return self._store

    def _ensure_builtins(self) -> None:
        now = datetime.now(UTC)

        for spec in _BUILTIN_AGENTS:
            agent_id = str(spec["agent_id"])
            existing = self._store.get_agent(agent_id)

            if existing is None:
                agent = SupervisorAgent(
                    agent_id=agent_id,
                    title=str(spec["title"]),
                    kind=spec["kind"],
                    capabilities=tuple(spec["capabilities"]),
                    dependencies=tuple(spec["dependencies"]),
                    status=AgentStatus.HEALTHY,
                    heartbeat_at=now,
                    stale_after_seconds=30,
                    registered_at=now,
                    updated_at=now,
                    metadata={"runtime": "in_process"},
                )
                self._store.save_agent(agent)
                self._store.append_event(
                    event_type="agent.registered",
                    source_agent_id=agent.agent_id,
                    detail=f"{agent.title} joined the Nexuss supervisor.",
                )
                continue

            refreshed = existing.model_copy(
                update={
                    "status": AgentStatus.HEALTHY,
                    "heartbeat_at": now,
                    "current_task_id": None,
                    "current_task_state": None,
                    "updated_at": now,
                }
            )
            self._store.save_agent(refreshed)

    @staticmethod
    def _assigned_agents(capability_ids: tuple[str, ...]) -> tuple[str, ...]:
        assigned: list[str] = []

        for capability_id in capability_ids:
            owner = "core.orchestrator"
            for prefix, candidate in _CAPABILITY_OWNERS:
                if capability_id.startswith(prefix):
                    owner = candidate
                    break
            if owner not in assigned:
                assigned.append(owner)

        if not assigned:
            assigned.append("core.orchestrator")

        return tuple(assigned)

    def _project_task(self, task: object) -> SupervisorTaskProjection:
        plan = getattr(task, "plan", None)
        steps = getattr(plan, "steps", ()) or ()
        capability_ids = tuple(
            str(getattr(step, "capability_id", "unknown"))
            for step in steps
        )
        state = _state_value(getattr(task, "state", "unknown"))
        return SupervisorTaskProjection(
            task_id=getattr(task, "task_id"),
            state=state,
            capability_ids=capability_ids,
            assigned_agents=self._assigned_agents(capability_ids),
            approval_required=(state == "awaiting_approval"),
            created_at=getattr(task, "created_at"),
            updated_at=getattr(task, "updated_at"),
        )

    def reconcile_tasks(self) -> tuple[SupervisorTaskProjection, ...]:
        projections: list[SupervisorTaskProjection] = []

        for task in self._core.list_tasks():
            projection = self._project_task(task)
            previous = self._store.get_task_projection(
                projection.task_id
            )

            if previous is None:
                self._store.append_event(
                    event_type="task.discovered",
                    source_agent_id="core.orchestrator",
                    task_id=projection.task_id,
                    detail=(
                        f"Core task entered supervisor projection in "
                        f"{projection.state} state."
                    ),
                )
            elif (
                previous.state != projection.state
                or previous.assigned_agents
                != projection.assigned_agents
            ):
                severity = (
                    EventSeverity.ERROR
                    if projection.state == "failed"
                    else EventSeverity.INFO
                )
                self._store.append_event(
                    event_type="task.state_changed",
                    source_agent_id="core.orchestrator",
                    task_id=projection.task_id,
                    severity=severity,
                    detail=(
                        f"Task changed from {previous.state} "
                        f"to {projection.state}."
                    ),
                )

            self._store.save_task_projection(projection)
            projections.append(projection)

        return tuple(
            sorted(
                projections,
                key=lambda item: item.updated_at,
                reverse=True,
            )
        )

    def register_external_agent(
        self,
        *,
        agent_id: str,
        title: str,
        capabilities: tuple[str, ...],
        dependencies: tuple[str, ...],
        stale_after_seconds: int,
        metadata: dict[str, str],
    ) -> SupervisorAgent:
        if self._store.get_agent(agent_id) is not None:
            raise AgentSupervisorError(
                "SUPERVISOR_AGENT_EXISTS",
                f"Agent {agent_id!r} is already registered.",
            )

        now = datetime.now(UTC)
        agent = SupervisorAgent(
            agent_id=agent_id,
            title=title,
            kind=AgentKind.EXTERNAL,
            capabilities=capabilities,
            dependencies=dependencies,
            status=AgentStatus.HEALTHY,
            heartbeat_at=now,
            stale_after_seconds=stale_after_seconds,
            registered_at=now,
            updated_at=now,
            metadata=metadata,
        )
        self._store.save_agent(agent)
        self._store.append_event(
            event_type="agent.registered",
            source_agent_id=agent.agent_id,
            detail=f"External agent {agent.title} registered locally.",
        )
        return agent

    def heartbeat(
        self,
        agent_id: str,
        request: SupervisorHeartbeatRequest,
    ) -> SupervisorAgent:
        current = self._store.get_agent(agent_id)
        if current is None:
            raise AgentSupervisorError(
                "SUPERVISOR_AGENT_NOT_FOUND",
                f"Agent {agent_id!r} is not registered.",
            )

        if request.status not in {
            AgentStatus.HEALTHY,
            AgentStatus.DEGRADED,
        }:
            raise AgentSupervisorError(
                "SUPERVISOR_HEARTBEAT_STATUS_INVALID",
                "Heartbeat status must be healthy or degraded.",
            )

        now = datetime.now(UTC)
        updated = current.model_copy(
            update={
                "status": request.status,
                "heartbeat_at": now,
                "current_task_id": request.current_task_id,
                "current_task_state": request.current_task_state,
                "updated_at": now,
            }
        )
        self._store.save_agent(updated)

        if (
            request.detail
            or current.status != updated.status
        ):
            self._store.append_event(
                event_type="agent.heartbeat",
                source_agent_id=updated.agent_id,
                task_id=request.current_task_id,
                severity=(
                    EventSeverity.WARNING
                    if updated.status is AgentStatus.DEGRADED
                    else EventSeverity.INFO
                ),
                detail=(
                    request.detail
                    or f"{updated.title} heartbeat is {updated.status.value}."
                ),
            )

        return updated

    def snapshot(self, *, event_limit: int = 25) -> SupervisorSnapshot:
        now = datetime.now(UTC)
        tasks = self.reconcile_tasks()
        active_tasks = tuple(
            item
            for item in tasks
            if item.state not in _TERMINAL_STATES
        )
        active_by_agent: dict[str, SupervisorTaskProjection] = {}

        for task in active_tasks:
            for agent_id in task.assigned_agents:
                active_by_agent.setdefault(agent_id, task)

        agents: list[SupervisorAgent] = []

        for stored in self._store.list_agents():
            if stored.kind is not AgentKind.EXTERNAL:
                status = (
                    AgentStatus.BUSY
                    if stored.agent_id in active_by_agent
                    else AgentStatus.HEALTHY
                )
                task = active_by_agent.get(stored.agent_id)
                agent = stored.model_copy(
                    update={
                        "status": status,
                        "heartbeat_at": now,
                        "current_task_id": (
                            task.task_id if task is not None else None
                        ),
                        "current_task_state": (
                            task.state if task is not None else None
                        ),
                        "updated_at": now,
                    }
                )
                self._store.save_agent(agent)
                agents.append(agent)
                continue

            age_seconds = (
                now - stored.heartbeat_at
            ).total_seconds()
            if age_seconds > stored.stale_after_seconds:
                status = AgentStatus.OFFLINE
            elif stored.status is AgentStatus.DEGRADED:
                status = AgentStatus.DEGRADED
            elif stored.current_task_id is not None:
                status = AgentStatus.BUSY
            else:
                status = AgentStatus.HEALTHY

            if status != stored.status:
                severity = (
                    EventSeverity.ERROR
                    if status is AgentStatus.OFFLINE
                    else EventSeverity.INFO
                )
                self._store.append_event(
                    event_type="agent.status_changed",
                    source_agent_id=stored.agent_id,
                    severity=severity,
                    detail=(
                        f"{stored.title} changed from "
                        f"{stored.status.value} to {status.value}."
                    ),
                )

            agent = stored.model_copy(
                update={
                    "status": status,
                    "updated_at": now,
                }
            )
            self._store.save_agent(agent)
            agents.append(agent)

        return SupervisorSnapshot(
            agents=tuple(agents),
            active_tasks=active_tasks,
            recent_events=self._store.recent_events(
                limit=event_limit
            ),
            healthy_count=sum(
                item.status is AgentStatus.HEALTHY
                for item in agents
            ),
            busy_count=sum(
                item.status is AgentStatus.BUSY
                for item in agents
            ),
            degraded_count=sum(
                item.status is AgentStatus.DEGRADED
                for item in agents
            ),
            offline_count=sum(
                item.status is AgentStatus.OFFLINE
                for item in agents
            ),
            event_chain_valid=self._store.verify_event_chain(),
            observed_at=now,
        )
