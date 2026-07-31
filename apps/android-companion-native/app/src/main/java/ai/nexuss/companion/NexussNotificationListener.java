package ai.nexuss.companion;

import android.app.Notification;
import android.os.Bundle;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;
import java.time.Instant;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.regex.Pattern;
import org.json.JSONObject;

public final class NexussNotificationListener extends NotificationListenerService {
    private static final Pattern SENSITIVE = Pattern.compile(
            "(?is)\\b(otp|one[- ]time|verification|security|login|auth(?:entication)?)\\b"
                    + ".{0,80}\\b\\d{4,8}\\b");
    private final ExecutorService network = Executors.newSingleThreadExecutor();

    @Override
    public void onNotificationPosted(StatusBarNotification posted) {
        String packageName = posted.getPackageName();
        String source = AppAllowlist.sourceFor(packageName);
        if (source == null) {
            return;
        }

        Notification notification = posted.getNotification();
        NotificationActionRegistry.register(posted.getKey(), notification);
        Bundle extras = notification.extras;
        String title = text(extras.getCharSequence(Notification.EXTRA_TITLE));
        String body = text(extras.getCharSequence(Notification.EXTRA_TEXT));
        boolean sensitive = SENSITIVE.matcher(body).find();
        if (sensitive) {
            body = "[sensitive notification content withheld]";
        }
        boolean replySupported = false;
        if (notification.actions != null) {
            for (Notification.Action action : notification.actions) {
                if (action.getRemoteInputs() != null && action.getRemoteInputs().length > 0) {
                    replySupported = true;
                    break;
                }
            }
        }

        String kind = inferKind(source, notification.category, title, body);
        JSONObject signal = new JSONObject();
        try {
            signal.put("event_id", java.util.UUID.randomUUID().toString());
            signal.put("source", source);
            signal.put("package_name", packageName);
            signal.put("kind", kind);
            signal.put("occurred_at", Instant.ofEpochMilli(posted.getPostTime()).toString());
            signal.put("sender_label", title.isBlank() ? JSONObject.NULL : title);
            signal.put("conversation_label", title.isBlank() ? JSONObject.NULL : title);
            signal.put("text", body.isBlank() ? JSONObject.NULL : body);
            signal.put("notification_key", posted.getKey());
            signal.put("reply_supported", replySupported);
            signal.put("sensitive", sensitive);
            signal.put("metadata", new JSONObject()
                    .put("category", notification.category)
                    .put("ongoing", posted.isOngoing()));
        } catch (Exception error) {
            return;
        }

        network.execute(() -> {
            try {
                SecureDeviceStore.DeviceIdentity identity =
                        new SecureDeviceStore(this).load();
                if (identity != null) {
                    new MobileFabricClient().postSignal(identity, signal);
                }
            } catch (Exception ignored) {
                // Fail closed. The next notification or manual sync retries.
            }
        });
    }

    @Override
    public void onNotificationRemoved(StatusBarNotification removed) {
        NotificationActionRegistry.remove(removed.getKey());
    }

    @Override
    public void onDestroy() {
        network.shutdownNow();
        super.onDestroy();
    }

    private static String inferKind(
            String source,
            String category,
            String title,
            String body) {
        String combined = (title + " " + body).toLowerCase(Locale.ROOT);
        if ("phone".equals(source)) {
            if (combined.contains("missed")) {
                return "missed_call";
            }
            if (Notification.CATEGORY_CALL.equals(category)) {
                return "incoming_call";
            }
        }
        if ("sms".equals(source)
                || "whatsapp".equals(source)
                || "instagram".equals(source)
                || "facebook_lite".equals(source)) {
            return "message_received";
        }
        return "app_notification";
    }

    private static String text(CharSequence value) {
        return value == null ? "" : value.toString().trim();
    }
}
