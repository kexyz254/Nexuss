package ai.nexuss.companion;

import android.Manifest;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.json.JSONArray;
import org.json.JSONObject;

public final class MainActivity extends AppCompatActivity {
    private static final String APPROVAL_CHANNEL = "nexuss_approvals";
    private final ExecutorService network = Executors.newSingleThreadExecutor();
    private EditText coreUrl;
    private EditText pairingCode;
    private EditText deviceLabel;
    private TextView status;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        createApprovalChannel();
        requestNotificationPermission();

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(40, 40, 40, 40);

        TextView title = new TextView(this);
        title.setText("Nexuss Trusted Companion");
        title.setTextSize(24);
        root.addView(title);

        TextView boundary = new TextView(this);
        boundary.setText(
                "Reads only allowlisted notifications and content you share. "
                        + "Every phone action requires exact on-device approval.");
        root.addView(boundary);

        coreUrl = field("Core URL", "http://192.168.1.10:8100");
        pairingCode = field("Eight-digit pairing code", "");
        deviceLabel = field("Device label", Build.MODEL);
        root.addView(coreUrl);
        root.addView(pairingCode);
        root.addView(deviceLabel);

        Button pair = new Button(this);
        pair.setText("Pair trusted device");
        pair.setOnClickListener(view -> pair());
        root.addView(pair);

        Button notificationAccess = new Button(this);
        notificationAccess.setText("Open notification access settings");
        notificationAccess.setOnClickListener(view -> startActivity(
                new Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)));
        root.addView(notificationAccess);

        Button approvals = new Button(this);
        approvals.setText("Check pending approvals");
        approvals.setOnClickListener(view -> checkApprovals());
        root.addView(approvals);

        Button forget = new Button(this);
        forget.setText("Forget this local pairing");
        forget.setOnClickListener(view -> {
            new SecureDeviceStore(this).clear();
            status.setText("Local pairing removed. Revoke the device in Nexuss desktop too.");
        });
        root.addView(forget);

        status = new TextView(this);
        status.setText("Not checked.");
        root.addView(status, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));
        setContentView(root);

        network.execute(() -> {
            try {
                SecureDeviceStore.DeviceIdentity identity =
                        new SecureDeviceStore(this).load();
                if (identity != null) {
                    runOnUiThread(() -> {
                        coreUrl.setText(identity.coreUrl());
                        status.setText("Paired as device " + identity.deviceId());
                    });
                }
            } catch (Exception error) {
                runOnUiThread(() -> status.setText("Stored pairing could not be decrypted."));
            }
        });
    }

    private EditText field(String hint, String value) {
        EditText edit = new EditText(this);
        edit.setHint(hint);
        edit.setText(value);
        edit.setSingleLine(true);
        return edit;
    }

    private void pair() {
        String url = coreUrl.getText().toString().trim();
        String code = pairingCode.getText().toString().trim();
        String label = deviceLabel.getText().toString().trim();
        if (!BuildConfig.DEBUG && !url.startsWith("https://")) {
            status.setText("Release builds require HTTPS.");
            return;
        }
        if (!code.matches("^[0-9]{8}$")) {
            status.setText("Enter the current eight-digit Nexuss pairing code.");
            return;
        }
        status.setText("Pairing…");
        network.execute(() -> {
            try {
                SecureDeviceStore.DeviceIdentity identity =
                        new MobileFabricClient().pair(url, code, label);
                new SecureDeviceStore(this).save(identity);
                runOnUiThread(() -> status.setText(
                        "Trusted pairing active: " + identity.deviceId()));
            } catch (Exception error) {
                runOnUiThread(() -> status.setText("Pairing failed: " + error.getMessage()));
            }
        });
    }

    private void checkApprovals() {
        status.setText("Checking approvals…");
        network.execute(() -> {
            try {
                SecureDeviceStore.DeviceIdentity identity =
                        new SecureDeviceStore(this).load();
                if (identity == null) {
                    throw new IllegalStateException("Pair this device first.");
                }
                JSONArray pending = new MobileFabricClient().pendingActions(identity);
                for (int index = 0; index < pending.length(); index++) {
                    JSONObject view = pending.getJSONObject(index);
                    showApprovalNotification(view.getJSONObject("proposal"));
                }
                runOnUiThread(() -> status.setText(
                        pending.length() + " approval request(s) available."));
            } catch (Exception error) {
                runOnUiThread(() -> status.setText("Approval check failed: " + error.getMessage()));
            }
        });
    }

    private void showApprovalNotification(JSONObject proposal) throws Exception {
        String actionId = proposal.getString("action_id");
        Intent intent = new Intent(this, ApprovalActivity.class)
                .putExtra("proposal_json", proposal.toString());
        PendingIntent pendingIntent = PendingIntent.getActivity(
                this,
                actionId.hashCode(),
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        NotificationCompat.Builder notification = new NotificationCompat.Builder(
                this,
                APPROVAL_CHANNEL)
                .setSmallIcon(android.R.drawable.ic_dialog_alert)
                .setContentTitle("Nexuss approval required")
                .setContentText(proposal.getString("target_label"))
                .setStyle(new NotificationCompat.BigTextStyle()
                        .bigText(proposal.getString("exact_preview")))
                .setContentIntent(pendingIntent)
                .setAutoCancel(true)
                .setPriority(NotificationCompat.PRIORITY_HIGH);
        if (ActivityCompat.checkSelfPermission(
                this,
                Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
                || Build.VERSION.SDK_INT < 33) {
            NotificationManagerCompat.from(this).notify(actionId.hashCode(), notification.build());
        }
    }

    private void createApprovalChannel() {
        NotificationChannel channel = new NotificationChannel(
                APPROVAL_CHANNEL,
                "Nexuss approvals",
                NotificationManager.IMPORTANCE_HIGH);
        channel.setDescription("Exact trusted-device action approvals.");
        getSystemService(NotificationManager.class).createNotificationChannel(channel);
    }

    private void requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33
                && ActivityCompat.checkSelfPermission(
                        this,
                        Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(
                    this,
                    new String[]{Manifest.permission.POST_NOTIFICATIONS},
                    1001);
        }
    }

    @Override
    protected void onDestroy() {
        network.shutdownNow();
        super.onDestroy();
    }
}
