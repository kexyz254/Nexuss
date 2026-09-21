"""Read-only system intelligence for Nexuss runtime self-awareness."""

from __future__ import annotations

import os
import platform
import sys
from datetime import UTC, datetime

from nexuss.connectors.errors import ConnectorError
from nexuss.connectors.github.runtime import get_github_connector
from nexuss.connectors.google_workspace.service import (
    GoogleWorkspaceConnectorService,
)
from nexuss.core.registry import list_capabilities
from nexuss.device.client import inspect_device_node_runtime
from nexuss.domain.models import CapabilityStatus
from nexuss.local_control.client import (
    HttpLocalControlClient,
    LocalControlError,
)


def collect_system_intelligence(
    *,
    observed_at: datetime | None = None,
) -> dict[str, object]:
    timestamp = observed_at or datetime.now(UTC)
    manifests = list(list_capabilities())

    capability_counts = {
        status.value: sum(
            manifest.status is status
            for manifest in manifests
        )
        for status in CapabilityStatus
    }

    github: dict[str, object]
    try:
        health = get_github_connector().health(now=timestamp)
        github = {
            "status": health.status.value,
            "configured": health.configured,
            "identity_verified": (
                health.identity.verified
                if health.identity is not None
                else False
            ),
        }
    except ConnectorError as exc:
        github = {
            "status": "error",
            "configured": False,
            "reason_code": exc.code,
        }

    google_service = GoogleWorkspaceConnectorService.from_environment()
    try:
        google_health = google_service.health()
        google = google_health.model_dump(mode="json")
    except ConnectorError as exc:
        google = {
            "connected": False,
            "reason_code": exc.code,
        }

    local_control: dict[str, object]
    try:
        client = HttpLocalControlClient.from_environment()
        update = client.inspect_update()
        local_control = {
            "configured": True,
            "reachable": True,
            "branch": update.branch,
            "current_sha": update.current_sha,
            "remote_sha": update.remote_sha,
            "update_available": update.update_available,
            "fast_forward_available": update.fast_forward_available,
            "clean_worktree": update.clean_worktree,
        }
    except (LocalControlError, ValueError):
        local_control = {
            "configured": bool(
                os.getenv("NEXUSS_LOCAL_CONTROL_URL", "").strip()
            ),
            "reachable": False,
        }

    return {
        "observed_at": timestamp.isoformat(),
        "runtime": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "process_id": os.getpid(),
            "executable": sys.executable,
        },
        "capabilities": {
            "total": len(manifests),
            "counts": capability_counts,
        },
        "connectors": {
            "github": github,
            "google_workspace": google,
            "trusted_device_node": inspect_device_node_runtime(),
            "local_control": local_control,
        },
        "credentials_exposed": False,
    }
