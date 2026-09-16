"""Durable, owner-scoped TAS investigations. Evidence never authorizes execution."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
from uuid import uuid4
from datetime import datetime, timezone


def state_path():
    root = Path(os.getenv("LOCALAPPDATA") or Path.home() / ".local" / "share")
    return root / "Nexuss" / "workflows" / "tas.sqlite3"


class InvestigationStore:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else state_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, owner TEXT NOT NULL, created TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS steps (run TEXT, name TEXT, status TEXT, payload TEXT, digest TEXT, PRIMARY KEY(run,name))")

    def connect(self):
        return sqlite3.connect(self.path, timeout=20)

    def create(self, owner):
        if not owner:
            raise ValueError("An authenticated conversation is required")
        run_id = str(uuid4())
        with self.connect() as db:
            db.execute("INSERT INTO runs VALUES (?,?,?)", (run_id, owner, datetime.now(timezone.utc).isoformat()))
        return run_id

    def get(self, run_id, owner):
        with self.connect() as db:
            run = db.execute("SELECT created FROM runs WHERE id=? AND owner=?", (run_id, owner)).fetchone()
            if run is None:
                raise ValueError("Investigation not found in this conversation")
            rows = db.execute("SELECT name,status,payload,digest FROM steps WHERE run=? ORDER BY rowid", (run_id,)).fetchall()
        result = {}
        for name, status, payload, digest in rows:
            if hashlib.sha256(payload.encode()).hexdigest() != digest:
                raise ValueError("Investigation receipt failed integrity check")
            result[name] = {"status": status, "data": json.loads(payload), "sha256": digest}
        return result

    def save(self, run_id, owner, name, status, data):
        self.get(run_id, owner)
        payload = json.dumps(data, sort_keys=True, allow_nan=False)
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO steps VALUES (?,?,?,?,?)", (run_id, name, status, payload, hashlib.sha256(payload.encode()).hexdigest()))


def _finite(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def _date(value):
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(timezone.utc).isoformat() if parsed.tzinfo else None
    except (ValueError, TypeError):
        return None


def normalize_health(envelope):
    data = envelope["data"]
    tripped = data.get("circuit_breaker_tripped")
    return {"score": _finite(data.get("score")), "breaker_tripped": tripped if type(tripped) is bool else None,
            "heartbeat_age": _finite(data.get("staleness_seconds")), "retrieved_at": _date(envelope.get("retrieved_at"))}


def normalize_incident(envelope):
    data = envelope["data"]
    reason = data.get("reason_code")
    if reason not in {"execution_errors", "other", "no_event"}:
        raise ValueError("Unknown incident schema")
    return {"reason_code": reason, "event_at": _date(data.get("event_at")),
            "error_count": _finite(data.get("error_count")), "retrieved_at": _date(envelope.get("retrieved_at"))}


def normalize_source(info):
    if not re.fullmatch(r"[0-9a-f]{40}", info["commit"]):
        raise ValueError("Source identity is missing")
    facts = info.get("breaker_facts", {})
    return {"commit": info["commit"], "source_files": int(info["source_files"]),
            "test_files": int(info["test_files"]),
            "breaker_facts": {key: facts.get(key) is True for key in ("restores_persisted_trip", "records_results", "explicit_reset")},
            "deployed_source_verified": False}


def investigate(owner, client_factory, inspect_source, *, store=None, run_id=None):
    store = store or InvestigationStore()
    run_id = run_id or store.create(owner)
    steps = store.get(run_id, owner)
    calls = 0
    tasks = (
        ("Maintenance / health", lambda: normalize_health(client_factory().evidence("health"))),
        ("Research / incident", lambda: normalize_incident(client_factory().evidence("incident"))),
        ("Engineering / source", lambda: normalize_source(inspect_source())),
    )
    for name, operation in tasks:
        # Resume retries failed reads; completed evidence remains bound to this run.
        if steps.get(name, {}).get("status") == "completed":
            continue
        try:
            data = operation()
            calls += 1
            store.save(run_id, owner, name, "completed", data)
        except Exception:
            # Provider/transport exceptions can contain credentials.
            store.save(run_id, owner, name, "blocked", {"reason": "Evidence unavailable or invalid"})
    steps = store.get(run_id, owner)
    health = steps["Maintenance / health"].get("data", {})
    incident = steps["Research / incident"].get("data", {})
    source = steps["Engineering / source"].get("data", {})
    issues = []
    if health.get("breaker_tripped") is True:
        issues.append("Circuit breaker is tripped; clearing it can resume new position entries.")
    if health.get("heartbeat_age") is None or health.get("heartbeat_age", 0) > 180:
        issues.append("Heartbeat freshness is unverified or stale.")
    issues.append("Repository snapshot has not been matched to the deployed source and local configuration.")
    store.save(run_id, owner, "Risk / assessment", "completed", {"findings": issues})
    store.save(run_id, owner, "Security / boundary", "completed", {
        "checks": ["Only typed evidence retained", "No raw exceptions persisted", "No source execution", "No credentials sent to a model"],
        "scope": "Investigation boundary checks only; not a system security audit"})
    store.save(run_id, owner, "Validation / repair", "blocked", {
        "reason": "No defect demonstrated, no candidate patch or isolated test receipt; deployment approval unavailable"})
    lines = [f"TAS investigation {run_id}"]
    for name, value in store.get(run_id, owner).items():
        lines.append(f"{name}: {value['status']}.")
    if health.get("score") is not None:
        lines.append(f"Health: {health['score']}/100.")
    if health.get("retrieved_at"):
        lines.append(f"Health evidence captured: {health['retrieved_at']}. Resume preserves this observation.")
    if incident.get("reason_code") == "execution_errors":
        lines.append(f"Latest journal event reports consecutive execution errors (count: {incident.get('error_count')}). This identifies the trip trigger, not the underlying execution failure.")
    elif incident.get("reason_code") == "other":
        lines.append("Latest journal event has a reason outside the supported structured categories; cause remains unresolved.")
    if source.get("commit"):
        lines.append(f"Source commit: {source['commit']}.")
    if source.get("breaker_facts", {}).get("restores_persisted_trip"):
        lines.append("Source inspection found a journal-event read in the breaker restoration method; a restart is not evidence of recovery.")
    lines.extend(issues)
    lines.append("Evidence collection alone establishes no defect and tests no patch. No TAS changes made.")
    lines.append(f"Prepare a bounded repair: 'prepare TAS repair {run_id}'. This requires configured AI consent and a local isolated test image; deployment is not connected yet.")
    lines.append(f"Resume failed evidence steps: 'resume TAS investigation {run_id}'. For fresh evidence, start a new investigation.")
    return "\n".join(lines), calls
