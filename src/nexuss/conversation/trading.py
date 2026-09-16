"""Evidence-backed TAS chat, independent of a paid model or its tool guesses."""
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import re

import httpx

from nexuss.connectors.trading import trading_client_from_environment


@dataclass(frozen=True)
class TradingReply:
    text: str
    tools_executed: int = 0


def configured_client():
    return trading_client_from_environment()


def source_report():
    from nexuss.connectors.github.operation_models import RepositorySelection
    from nexuss.connectors.github.workspace_control import GitHubWorkspaceControlPlane
    plane = GitHubWorkspaceControlPlane.from_environment()
    selection = RepositorySelection(
        repository_full_name="kexyz254/trading-analysis-platform",
        requested_ref=os.getenv("NEXUSS_TAS_SOURCE_REF", "integration/nexuss-p617"),
    )
    snapshot = plane.create_snapshot(selection)
    report = plane.analyze_snapshot(snapshot.snapshot_id)
    return {"commit": report.resolved_commit_sha, "snapshot": str(snapshot.snapshot_id),
            "source_files": report.source_files, "test_files": report.test_files,
            "build_systems": list(report.build_systems), "ref": selection.requested_ref}


def _number(value):
    return str(round(value, 2)) if type(value) in (int, float) else "unavailable"


def _boolean(value):
    return "yes" if value is True else "no" if value is False else "unknown"


def _time(value):
    # Render only valid dates, not arbitrary upstream free text.
    try:
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            return "unavailable"
        return result.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return "unavailable"


def handle_trading_chat(text, *, client_factory=configured_client, inspect_source=source_report):
    normalized = " ".join(text.casefold().split())
    if not re.search(r"\b(tas|ats|trading analysis (?:system|platform))\b", normalized):
        return None
    if re.search(r"\b(buy|sell|place|cancel|execute|reset|restart|deploy|modify|upgrade|fix|repair|improve)\b", normalized):
        return TradingReply(
            "TAS engineering request received. Chat can inspect live health, decisions, offline "
            "observations and a versioned source snapshot. A TAS patch/test/deployment executor "
            "is not connected yet, so I have not changed the system or requested a misleading "
            "approval. Ask ‘inspect TAS code’ or ‘check TAS’ to gather evidence for that work. "
            "TAS retains trade execution authority."
        )
    if re.search(r"\b(code|source|repository|repo)\b", normalized):
        try:
            info = inspect_source()
            commit = info["commit"]
            if not re.fullmatch(r"[0-9a-f]{40}", commit):
                raise ValueError("Invalid source identity")
            return TradingReply(
                f"TAS source inspected: kexyz254/trading-analysis-platform at commit {commit}.\n"
                f"Snapshot: {info['snapshot']}. Source files: {int(info['source_files'])}; "
                f"test files: {int(info['test_files'])}.\n"
                "This is the committed repository snapshot, not proof of what is deployed. "
                "Server-only configuration changes are not included. No repository code was "
                "executed or modified; inspection receipts are retained by the GitHub workspace service.", 2)
        except Exception:
            # GitHub/provider exceptions can carry tokens or URLs; never copy them to chat.
            return TradingReply("TAS source inspection is unavailable. Configure GitHub access "
                                "inside Nexuss for kexyz254/trading-analysis-platform. The GitHub "
                                "connection in this ChatGPT session is separate. No source was modified.")
    try:
        client = client_factory()
        if re.search(r"\b(decision|decisions|signal|signals)\b", normalized):
            match = re.search(r"\b([a-z0-9]{1,20}/[a-z0-9]{1,20})\b", normalized)
            if match is None:
                return TradingReply("Which pair should I inspect? For example: ‘show TAS decisions for BTC/USDT’.")
            symbol = match[1].upper()
            envelope = client.evidence("decisions", symbol)
            rows = envelope.get("data", {}).get("decisions")
            if not isinstance(rows, list):
                raise ValueError("Invalid decisions")
            lines = [f"TAS recorded decisions for {symbol}; retrieved {_time(envelope.get('retrieved_at'))}."]
            for row in rows[:10]:
                if not isinstance(row, dict):
                    continue
                signal = row.get("signal")
                signal = signal.lower() if isinstance(signal, str) else "unknown"
                if signal not in {"buy", "sell", "hold", "neutral", "long", "short"}:
                    signal = "unclassified"
                lines.append(f"{_time(row.get('timestamp'))}: {signal}; confidence "
                             f"{_number(row.get('confidence'))}; price {_number(row.get('price'))}.")
            if not rows:
                lines.append("No recorded decisions returned.")
            lines.append("These are historical TAS records, not new trading instructions.")
            return TradingReply("\n".join(lines), 1)
        if re.search(r"\b(observations|events|offline|worker)\b", normalized):
            state = client.request("GET", "/agent/v1/worker/status")
            batch = client.observations(0, 10)
            checked = state.get("last_checked")
            age = max(0, datetime.now(timezone.utc).timestamp() - checked) if type(checked) in (int, float) else None
            worker_state = state.get("status")
            if worker_state not in {"observing", "not_started", "backlog_full"}:
                worker_state = "unknown"
            lines = [f"TAS offline worker: {worker_state}. Last check age: {_number(age)} seconds.",
                     f"Stored observations: {_number(state.get('stored_events'))}."]
            if age is None or age > 180:
                lines.append("Worker liveness is unverified or stale.")
            rows = batch.get("events", [])
            if not isinstance(rows, list):
                raise ValueError("Invalid observations")
            for row in rows[:10]:
                data = row.get("data", {})
                lines.append(f"Observation {_number(row.get('id'))}: health {_number(data.get('score'))}; "
                             f"breaker tripped: {_boolean(data.get('circuit_breaker_tripped'))}.")
            lines.append("Showing the first stored page; this is not automatic replay or repair.")
            return TradingReply("\n".join(lines), 2)
        if re.search(r"\b(check|health|status|inspect|diagnose|diagnostic|connected|connection)\b", normalized):
            envelope = client.evidence("health")
            data = envelope.get("data", {})
            if not isinstance(data, dict):
                raise ValueError("Invalid health")
            lines = [f"TAS health score: {_number(data.get('score'))}/100.",
                     f"Circuit breaker tripped: {_boolean(data.get('circuit_breaker_tripped'))}.",
                     f"Heartbeat age: {_number(data.get('staleness_seconds'))} seconds.",
                     f"Evidence retrieved: {_time(envelope.get('retrieved_at'))}."]
            if data.get("circuit_breaker_tripped") is True:
                lines.append("TAS reports a tripped circuit breaker. This response does not establish "
                             "why it tripped; it has not been reset.")
            lines.append("This is a live read through the authenticated bridge. No trading or configuration changes made.")
            return TradingReply("\n".join(lines), 1)
        return TradingReply("TAS is available through these chat requests: ‘check TAS’, ‘show TAS "
                            "decisions for BTC/USDT’, ‘show TAS offline observations’, and ‘inspect TAS code’. "
                            "Live editing, deployment and automatic research are not connected yet.")
    except (KeyError, OSError, ValueError, TypeError, AttributeError, httpx.HTTPError):
        return TradingReply("TAS evidence is unavailable. Check the bridge connection and Nexuss's "
                            "private runtime configuration. I have not substituted cached health, "
                            "invented results or changed TAS.")
