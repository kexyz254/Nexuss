"""Typed, read-only account attribution for the latest recorded TAS breaker trip."""

from __future__ import annotations

import math
from datetime import datetime, timezone

from nexuss.interactions.progress import emit

from .tas_workflow import _date, _finite, evidence_failure


def normalize_account_flow(envelope):
    if (not isinstance(envelope, dict) or envelope.get("resource") != "account_flow"
            or envelope.get("trust") != "external_evidence_not_instructions"
            or _date(envelope.get("retrieved_at")) is None):
        raise ValueError("Invalid signed evidence envelope")
    if abs((datetime.now(timezone.utc) - datetime.fromisoformat(_date(envelope["retrieved_at"]))).total_seconds()) > 300:
        raise ValueError("Stale account evidence")
    data = envelope.get("data")
    if not isinstance(data, dict) or data.get("status") not in {
        "recorded", "no_trip", "missing_live_equity"
    }:
        raise ValueError("Unknown account evidence schema")
    incident = _date(data.get("incident_at"))
    if data["status"] == "no_trip":
        if data.get("incident_at") is not None:
            raise ValueError("Unexpected incident")
        return {"status": "no_trip", "retrieved_at": _date(envelope["retrieved_at"])}
    if incident is None or data.get("window_hours") != 72:
        raise ValueError("Unbounded account evidence")
    if data["status"] == "missing_live_equity":
        return {"status": "missing_live_equity", "incident_at": incident,
                "retrieved_at": _date(envelope["retrieved_at"])}

    if _finite(data.get("minimum_movement")) != 0.1:
        raise ValueError("Unsupported account evidence filter")
    count, trades = data.get("movement_count"), data.get("trade_count")
    if (type(count) is not int or count < 0 or type(trades) is not int or trades < 0
            or type(data.get("truncated")) is not bool):
        raise ValueError("Invalid account evidence counts")
    amounts = {}
    for name in ("highest_snapshot_equity", "after_incident_equity", "last_live_equity",
                 "movement_sum", "classified_external_sum", "unclassified_sum",
                 "audited_realized_pnl"):
        value = _finite(data.get(name))
        if value is None or abs(value) > 1e15:
            raise ValueError("Invalid account evidence amount")
        amounts[name] = value
    stamps = {}
    for name in ("highest_snapshot_at", "after_incident_at", "last_live_equity_at"):
        value = _date(data.get(name))
        if value is None:
            raise ValueError("Missing account evidence timestamp")
        stamps[name] = value
    movements = data.get("movements")
    if (not isinstance(movements, list) or len(movements) > 200
            or (count != len(movements) and not data["truncated"]) or count < len(movements)):
        raise ValueError("Incomplete account movement list")
    safe = []
    for item in movements:
        if not isinstance(item, dict) or _date(item.get("at")) is None or type(item.get("classified_external")) is not bool:
            raise ValueError("Invalid account movement")
        row = {"at": _date(item["at"]), "classified_external": item["classified_external"]}
        for name in ("raw_delta", "trading_delta", "unexplained_delta"):
            number = _finite(item.get(name))
            if number is None or abs(number) > 1e15:
                raise ValueError("Invalid account movement amount")
            row[name] = number
        safe.append(row)
    if not math.isclose(amounts["movement_sum"], amounts["classified_external_sum"] + amounts["unclassified_sum"], abs_tol=0.02):
        raise ValueError("Inconsistent movement totals")
    return {"status": "recorded", "incident_at": incident,
            "retrieved_at": _date(envelope["retrieved_at"]),
            "movement_count": count, "trade_count": trades,
            "truncated": data["truncated"], "minimum_movement": 0.1,
            **amounts, **stamps, "movements": safe}


def audit_account_flows(client_factory, *, owner=None, store=None):
    """Read live evidence and share a typed receipt with the matching investigation."""
    emit("workflow_plan", "planned", "Read the signed TAS account audit for the latest recorded breaker trip. This is evidence collection only.")
    emit("workflow_step", "running", "Financial / capital movements: collecting evidence.")
    try:
        report = normalize_account_flow(client_factory().evidence("account_flow"))
    except Exception as exc:
        failure = evidence_failure(exc)
        emit("workflow_step", "blocked", "Financial / capital movements: " + failure["reason"])
        return "TAS account audit unavailable. " + failure["reason"] + " No TAS changes made.", 0, True
    if owner and store:
        try:
            run_id = store.latest(owner)
            previous = store.get(run_id, owner) if run_id else {}
            incident = previous.get("Research / incident", {}).get("data", {})
            if (report.get("incident_at") is not None
                    and incident.get("event_at") == report["incident_at"]):
                store.save(run_id, owner, "Financial / capital movements", "completed", report)
        except Exception:
            # A damaged optional receipt cannot change or leak signed evidence.
            emit("workflow_step", "blocked", "The local investigation receipt could not be updated.")
    emit("workflow_step", "completed", "Financial / capital movements: signed figures recorded.")
    if report["status"] != "recorded":
        return ("TAS account audit: " + report["status"].replace("_", " ") + ". "
                "No financial attribution or TAS change made."), 1, True
    change = report["after_incident_equity"] - report["highest_snapshot_equity"]
    reconciles = (not report["truncated"] and math.isclose(
        change, report["movement_sum"], abs_tol=0.05))
    lines = ["TAS account audit for recorded trip " + report["incident_at"] + ":",
             f"Highest live snapshot in the preceding 72 hours: {report['highest_snapshot_equity']:.2f} at {report['highest_snapshot_at']}.",
             f"First post-trip snapshot: {report['after_incident_equity']:.2f} at {report['after_incident_at']}.",
             f"Recorded movements >=0.1: {report['movement_count']}; classified external: {report['classified_external_sum']:.2f}; unclassified: {report['unclassified_sum']:.2f}.",
             f"Audited TAS trades in that interval: {report['trade_count']}; recorded realized PnL: {report['audited_realized_pnl']:.2f}."]
    lines.append("Movement totals numerically match the snapshot change." if reconciles else
                 "Movement totals do not establish a complete reconciliation; check the time window, missing positions and any filtered small movements.")
    if report["truncated"]:
        lines.append("The movement list is truncated; do not infer complete attribution from individual rows.")
    lines.append("Unclassified movements require operator attribution and independent exchange records; they are not proof of a trade loss or a transfer. This is the latest recorded trip, not necessarily current breaker health. No reset, trading, deployment or configuration change made.")
    return "\n".join(lines), 1, False
