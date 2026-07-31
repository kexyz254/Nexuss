package ai.nexuss.companion;

import java.util.Collections;
import java.util.HashMap;
import java.util.Map;

final class AppAllowlist {
    private static final Map<String, String> SOURCES;

    static {
        Map<String, String> values = new HashMap<>();
        values.put("com.whatsapp", "whatsapp");
        values.put("com.instagram.android", "instagram");
        values.put("com.facebook.lite", "facebook_lite");
        values.put("com.google.android.apps.messaging", "sms");
        values.put("com.samsung.android.messaging", "sms");
        values.put("com.google.android.dialer", "phone");
        values.put("com.samsung.android.dialer", "phone");
        values.put("ai.nexuss.companion", "other");
        values.put("ai.nexuss.companion.debug", "other");
        SOURCES = Collections.unmodifiableMap(values);
    }

    private AppAllowlist() {}

    static String sourceFor(String packageName) {
        return SOURCES.get(packageName);
    }

    static boolean contains(String packageName) {
        return SOURCES.containsKey(packageName);
    }
}
