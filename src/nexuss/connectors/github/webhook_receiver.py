"""Webhook activation boundary for the later monitoring milestone."""

from __future__ import annotations


class GitHubWebhookReceiver:
    """P6.6A deliberately registers no public webhook route."""

    enabled = False

    @staticmethod
    def status() -> dict[str, object]:
        return {
            "enabled": False,
            "reason": (
                "Continuous monitoring is deferred until read-only workspace "
                "integration passes."
            ),
            "webhook_route_registered": False,
            "events_persisted": False,
        }
