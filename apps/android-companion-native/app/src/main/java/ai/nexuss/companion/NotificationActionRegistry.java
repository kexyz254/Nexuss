package ai.nexuss.companion;

import android.app.Notification;
import android.app.PendingIntent;
import android.app.RemoteInput;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

final class NotificationActionRegistry {
    private static final Map<String, Entry> ENTRIES = new ConcurrentHashMap<>();

    private NotificationActionRegistry() {}

    static void register(String key, Notification notification) {
        Notification.Action replyAction = null;
        if (notification.actions != null) {
            for (Notification.Action action : notification.actions) {
                RemoteInput[] inputs = action.getRemoteInputs();
                if (inputs != null && inputs.length > 0) {
                    replyAction = action;
                    break;
                }
            }
        }
        ENTRIES.put(key, new Entry(notification.contentIntent, replyAction));
    }

    static Entry get(String key) {
        return ENTRIES.get(key);
    }

    static void remove(String key) {
        ENTRIES.remove(key);
    }

    record Entry(PendingIntent contentIntent, Notification.Action replyAction) {}
}
