package ai.nexuss.companion;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.widget.Toast;
import java.time.Instant;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.json.JSONObject;

public final class ShareReceiverActivity extends Activity {
    private final ExecutorService network = Executors.newSingleThreadExecutor();

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        Intent intent = getIntent();
        String shared = intent == null
                ? null
                : intent.getStringExtra(Intent.EXTRA_TEXT);
        if (shared == null || shared.isBlank()) {
            Toast.makeText(this, "No text was shared.", Toast.LENGTH_SHORT).show();
            finish();
            return;
        }

        network.execute(() -> {
            boolean success = false;
            try {
                SecureDeviceStore.DeviceIdentity identity =
                        new SecureDeviceStore(this).load();
                if (identity != null) {
                    JSONObject signal = new JSONObject()
                            .put("event_id", UUID.randomUUID().toString())
                            .put("source", "other")
                            .put("package_name", getPackageName())
                            .put("kind", "shared_content")
                            .put("occurred_at", Instant.now().toString())
                            .put("sender_label", "Shared to Nexuss")
                            .put("conversation_label", "Manual share")
                            .put("text", shared)
                            .put("reply_supported", false)
                            .put("sensitive", false)
                            .put("metadata", new JSONObject());
                    new MobileFabricClient().postSignal(identity, signal);
                    success = true;
                }
            } catch (Exception ignored) {
                success = false;
            }
            boolean result = success;
            runOnUiThread(() -> {
                Toast.makeText(
                        this,
                        result ? "Shared with Nexuss." : "Nexuss is not paired or reachable.",
                        Toast.LENGTH_LONG).show();
                finish();
            });
        });
    }

    @Override
    protected void onDestroy() {
        network.shutdownNow();
        super.onDestroy();
    }
}
