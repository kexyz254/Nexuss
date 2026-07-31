"""Static safety and integration contract for the P6.7A Android companion."""

from __future__ import annotations

from pathlib import Path


class ContractFailure(RuntimeError):
    """Raised when the Android companion violates the declared boundary."""


def require(text: str, marker: str, label: str) -> None:
    if marker not in text:
        raise ContractFailure(f"Missing {label}: {marker}")


def forbid(text: str, marker: str, label: str) -> None:
    if marker in text:
        raise ContractFailure(f"Forbidden {label}: {marker}")


def main() -> int:
    root = Path.cwd()
    module = root / "apps/android-companion-native"
    manifest = (module / "app/src/main/AndroidManifest.xml").read_text(
        encoding="utf-8-sig"
    )
    build = (module / "app/build.gradle.kts").read_text(encoding="utf-8-sig")
    java_root = module / "app/src/main/java/ai/nexuss/companion"
    java = "\n".join(
        path.read_text(encoding="utf-8-sig")
        for path in sorted(java_root.glob("*.java"))
    )

    require(manifest, "android.permission.INTERNET", "network permission")
    require(manifest, "android.permission.USE_BIOMETRIC", "biometric permission")
    require(
        manifest,
        "android.permission.BIND_NOTIFICATION_LISTENER_SERVICE",
        "notification-listener binding",
    )
    require(manifest, ".NexussNotificationListener", "notification listener")
    require(manifest, ".ShareReceiverActivity", "manual share target")

    forbidden_permissions = (
        "android.permission.READ_SMS",
        "android.permission.SEND_SMS",
        "android.permission.RECEIVE_SMS",
        "android.permission.READ_CALL_LOG",
        "android.permission.WRITE_CALL_LOG",
        "android.permission.CALL_PHONE",
        "android.permission.RECORD_AUDIO",
        "android.permission.READ_CONTACTS",
    )
    for permission in forbidden_permissions:
        forbid(manifest, permission, "dangerous direct-access permission")

    forbid(manifest, "AccessibilityService", "accessibility automation")
    forbid(java, "AccessibilityService", "accessibility automation")
    forbid(java, "Runtime.getRuntime().exec", "shell execution")
    forbid(java, "su -c", "root execution")

    require(java, "NotificationListenerService", "notification ingestion")
    require(java, "BiometricPrompt", "on-device approval")
    require(java, "AndroidKeyStore", "encrypted pairing-token storage")
    require(java, "Intent.ACTION_DIAL", "dialer handoff")
    require(java, "Intent.ACTION_SENDTO", "SMS composer handoff")
    require(java, "RemoteInput.addResultsToIntent", "notification reply")
    require(java, "X-Nexuss-Mobile-Assertion", "device request assertion")
    require(java, "com.whatsapp", "WhatsApp allowlist")
    require(java, "com.instagram.android", "Instagram allowlist")
    require(java, "com.facebook.lite", "Facebook Lite allowlist")

    require(
        build,
        'manifestPlaceholders["usesCleartextTraffic"] = "false"',
        "release cleartext prohibition",
    )
    require(
        build,
        'manifestPlaceholders["usesCleartextTraffic"] = "true"',
        "private-LAN debug transport declaration",
    )

    print("PASS: P6.7A Android companion source contract verified.")
    print("Accessibility automation present: False")
    print("Direct SMS permission present: False")
    print("Direct call permission present: False")
    print("Call-recording permission present: False")
    print("Release cleartext transport allowed: False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
