from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from nexuss.orchestration.supervisor import AgentSupervisorService
from nexuss.orchestration.supervisor_models import (
    AgentStatus,
    SupervisorHeartbeatRequest,
)
from nexuss.orchestration.supervisor_store import SQLiteSupervisorStore


class FakeCore:
    def __init__(self) -> None:
        self.tasks: list[object] = []

    def list_tasks(self) -> tuple[object, ...]:
        return tuple(self.tasks)


def _task(
    *,
    state: str = "executing",
    capability_id: str = "engineering.verify_acceptance",
):
    now = datetime.now(UTC)
    return SimpleNamespace(
        task_id=uuid4(),
        state=state,
        plan=SimpleNamespace(
            steps=[SimpleNamespace(capability_id=capability_id)]
        ),
        approval=None,
        created_at=now,
        updated_at=now,
    )


def test_supervisor_registers_builtin_agents_and_valid_chain(tmp_path) -> None:
    service = AgentSupervisorService(
        core_service=FakeCore(),
        store=SQLiteSupervisorStore(tmp_path / "supervisor.sqlite3"),
    )
    snapshot = service.snapshot()
    assert {agent.agent_id for agent in snapshot.agents} == {
        "core.orchestrator",
        "engineering.agent",
        "intelligence.agent",
        "research.agent",
        "device.agent",
        "operations.agent",
        "collaboration.agent",
    }
    assert snapshot.healthy_count == 7
    assert snapshot.busy_count == 0
    assert snapshot.event_chain_valid is True
    assert snapshot.external_execution_authorized is False


def test_supervisor_projects_core_task_without_new_state_machine(tmp_path) -> None:
    core = FakeCore()
    task = _task()
    core.tasks.append(task)
    service = AgentSupervisorService(
        core_service=core,
        store=SQLiteSupervisorStore(tmp_path / "supervisor.sqlite3"),
    )

    running = service.snapshot()
    engineering = next(
        agent for agent in running.agents
        if agent.agent_id == "engineering.agent"
    )
    assert engineering.status is AgentStatus.BUSY
    assert engineering.current_task_id == task.task_id
    assert len(running.active_tasks) == 1
    assert running.active_tasks[0].assigned_agents == ("engineering.agent",)

    task.state = "completed"
    task.updated_at = datetime.now(UTC) + timedelta(seconds=1)

    completed = service.snapshot()
    engineering = next(
        agent for agent in completed.agents
        if agent.agent_id == "engineering.agent"
    )
    assert engineering.status is AgentStatus.HEALTHY
    assert completed.active_tasks == ()
    assert any(
        event.event_type == "task.state_changed"
        for event in completed.recent_events
    )
    assert completed.event_chain_valid is True


def test_external_agent_heartbeat_and_degradation_are_audited(tmp_path) -> None:
    service = AgentSupervisorService(
        core_service=FakeCore(),
        store=SQLiteSupervisorStore(tmp_path / "supervisor.sqlite3"),
    )
    registered = service.register_external_agent(
        agent_id="trading.agent",
        title="Trading Operations Agent",
        capabilities=("trading.*",),
        dependencies=("core.orchestrator",),
        stale_after_seconds=30,
        metadata={"runtime": "hetzner_bridge"},
    )
    assert registered.status is AgentStatus.HEALTHY

    degraded = service.heartbeat(
        "trading.agent",
        SupervisorHeartbeatRequest(
            status=AgentStatus.DEGRADED,
            detail="Market-data dependency is degraded.",
        ),
    )
    assert degraded.status is AgentStatus.DEGRADED
    assert service.store.verify_event_chain() is True
    events = service.store.recent_events(limit=10)
    assert any(
        event.source_agent_id == "trading.agent"
        and event.event_type == "agent.heartbeat"
        for event in events
    )
