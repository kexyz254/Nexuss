# Nexuss Trusted Android Companion — P6.7A Reference Source

This module is the native counterpart for the P6.7A mobile fabric.

## Active boundaries

- Allowlisted notifications: phone, SMS, WhatsApp, Instagram and Facebook Lite.
- Manual Android share-target ingestion.
- Android Keystore encryption for the paired-device token.
- HMAC-SHA256 request assertions with timestamp and nonce.
- Exact action preview and SHA-256 display.
- Biometric or device-credential confirmation.
- ACTION_DIAL, ACTION_SENDTO, notification RemoteInput and notification content PendingIntent.
- No AccessibilityService, private database access, root, call recording or background SMS sending.

## Build prerequisites

- Android Studio compatible with Android Gradle Plugin 9.4
- JDK 17
- Gradle 9.6
- Android SDK platform 37 and Build Tools 36.0.0

The repository intentionally omits the Gradle wrapper JAR. Open the module in
Android Studio or generate the wrapper with a trusted local Gradle installation.

## Transport

Debug builds allow cleartext HTTP only for the existing private-LAN Nexuss
prototype. Release builds reject cleartext and require HTTPS. Never port-forward
or publicly expose the current Core endpoint.

## Pairing

1. Start Nexuss Core on a private network.
2. Create a phone pairing challenge in the desktop interface.
3. Enter the Core URL, eight-digit code and device label in the companion.
4. Grant notification access explicitly in Android Settings.
5. Keep only the desired source applications enabled in the listener settings.
