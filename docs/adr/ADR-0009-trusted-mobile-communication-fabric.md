# ADR-0009: Trusted Mobile Communication Fabric

**Status:** Accepted for P6.7A implementation

## Decision

Nexuss will integrate personal communication applications through the narrowest
supported platform surface:

1. Android NotificationListenerService for allowlisted notification signals.
2. The Android share sheet for user-selected content.
3. Default-handler roles only in later, separately approved modules.
4. Android ACTION_DIAL and ACTION_SENDTO for user-completed phone/SMS handoffs.
5. App-provided notification RemoteInput and PendingIntent actions when present.
6. Official Meta business/professional APIs only for accounts and use cases they support.

Nexuss will not use AccessibilityService as a general automation engine and
will not claim access to private personal-app history that Android or the
provider does not expose.

## Consequences

The system gains high-value cross-app awareness and bounded action execution
without requiring root, screen scraping or hidden credentials. Historical
coverage depends on notifications observed after permission is granted, content
the user shares, or an official provider API. Some actions remain conditional
because individual notifications may not expose a reply or conversation action.
