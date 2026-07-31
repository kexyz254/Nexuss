"""Live read-only Google Workspace connector check."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from nexuss.connectors.google_workspace.service import (
    GoogleWorkspaceConnectorService,
)


def main() -> int:
    service = GoogleWorkspaceConnectorService.from_environment()
    health = service.health()
    print("Health:", health.model_dump(mode="json"))
    if not health.connected:
        raise SystemExit(
            "STOP: Google Workspace is not connected. "
            "Run connect_google_workspace.py first."
        )
    now = datetime.now(UTC)
    snapshot = service.snapshot(
        time_min=now - timedelta(days=1),
        time_max=now + timedelta(days=14),
        gmail_query="newer_than:14d",
    )
    print(
        "Snapshot:",
        {
            "account": snapshot.profile.email if snapshot.profile else None,
            "messages": len(snapshot.messages),
            "calendars": len(snapshot.calendars),
            "events": len(snapshot.events),
            "contacts": len(snapshot.contacts),
        },
    )
    assert snapshot.read_only is True
    assert snapshot.external_write_performed is False
    assert snapshot.credentials_exposed is False
    print("PASS: Google Workspace read-only connector verified.")
    print("External write performed: False")
    print("Credentials exposed: False")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
