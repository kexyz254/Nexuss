"""Authenticated live check for P6.8A commitment intelligence."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib import request
from uuid import uuid4


def _call(
    method: str,
    url: str,
    *,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {
        "Accept": "application/json",
        "X-Nexuss-Session-ID": str(uuid4()),
        "X-Nexuss-Session-Authenticated": "true",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )
    with request.urlopen(req, timeout=90) as response:
        result = json.loads(response.read().decode())
    if not isinstance(result, dict):
        raise TypeError("Nexuss response was not an object")
    return result

def main() -> int:
    base_url = "http://127.0.0.1:8100"
    health = _call("GET", f"{base_url}/v1/commitments/health")
    brief = _call(
        "POST",
        f"{base_url}/v1/commitments/prepare-day",
        payload={
            "planning_date": datetime.now(UTC).date().isoformat(),
            "timezone": "Africa/Nairobi",
            "include_mobile": True,
            "gmail_days_back": 14,
        },
    )
    print("Health:", health)
    print(
        "Brief:",
        {
            "commitments": len(brief.get("commitments", [])),
            "events": len(brief.get("calendar_events", [])),
            "conflicts": len(brief.get("conflicts", [])),
            "google_account": brief.get("connected_google_account"),
        },
    )
    assert health["external_writes_enabled"] is False
    assert brief["external_write_performed"] is False
    assert brief["phone_approval_requested"] is False
    assert brief["credentials_exposed"] is False
    print("PASS: P6.8A unified commitment live check completed.")
    print("External write performed: False")
    print("Credentials exposed: False")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
