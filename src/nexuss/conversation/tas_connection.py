"""Read-only connection/health checks; constraints never become mutations."""
from datetime import datetime, timezone
import math

from nexuss.connectors.trading_tunnel import managed_tunnel
from nexuss.interactions.progress import emit
from .tas_workflow import evidence_failure


def check_connection(client_factory, *, connection=True, health=True, status_reader=None):
    lines = []
    calls = 0
    blocked = False
    emit("workflow_plan", "planned", "Check requested TAS connection and health evidence. No restart, reset or deployment is planned.")
    if connection:
        emit("workflow_step", "running", "Reading Nexuss's local SSH supervisor status.")
        status = (status_reader or managed_tunnel.status)()
        state = status.get("state")
        states = {"disabled", "configuration_invalid", "ssh_unavailable", "starting", "connecting",
                  "forwarding", "external_listener", "retry_wait", "launch_failed", "supervisor_error", "stopped"}
        if state not in states:
            state = "unknown"
        lines.append(f"Managed SSH transport: {state}.")
        if state == "disabled":
            lines.append("Nexuss SSH supervision is not enabled. A manual tunnel or a direct private connection may still be configured.")
        elif state == "external_listener":
            lines.append("The local listener belongs to another process; Nexuss does not manage it.")
        elif state == "forwarding":
            lines.append("Nexuss owns the SSH forward. This alone does not verify the remote bridge or TAS health.")
        else:
            lines.append("Use the signed health result below to assess live access; transport status alone is insufficient.")
        calls += 1
        emit("workflow_step", "completed", "Local transport status recorded.")
    if health:
        emit("workflow_step", "running", "Requesting live TAS health through the signed bridge.")
        try:
            envelope = client_factory().evidence("health")
            data = envelope["data"]
            score, tripped, age = data.get("score"), data.get("circuit_breaker_tripped"), data.get("staleness_seconds")
            captured = datetime.fromisoformat(envelope["retrieved_at"])
            if (type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 100
                    or type(tripped) is not bool or captured.tzinfo is None):
                raise ValueError("Invalid health evidence")
            age = str(round(age, 2)) if type(age) in (int, float) and math.isfinite(age) else "unavailable"
            lines.extend(["Live bridge evidence: available.", f"TAS health score: {score}/100.",
                          f"Circuit breaker tripped: {'yes' if tripped else 'no'}.",
                          f"Heartbeat age: {age} seconds.", f"Evidence retrieved: {captured.astimezone(timezone.utc).isoformat()}."])
            if tripped:
                lines.append("This does not establish why it tripped; the breaker has not been reset.")
            calls += 1
            emit("workflow_step", "completed", "Live health evidence received; availability is separate from system health.")
        except Exception as exc:
            blocked = True
            failure = evidence_failure(exc)["reason"]
            lines.extend(["Live bridge evidence: unavailable.", failure])
            emit("workflow_step", "blocked", failure)
    lines.append("No TAS restart, breaker reset, trade or configuration change was made.")
    return "\n".join(lines), calls, blocked
