package ai.nexuss.companion;

import android.os.Bundle;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.biometric.BiometricManager;
import androidx.biometric.BiometricPrompt;
import androidx.core.content.ContextCompat;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.json.JSONObject;

public final class ApprovalActivity extends AppCompatActivity {
    private final ExecutorService network = Executors.newSingleThreadExecutor();
    private JSONObject proposal;
    private TextView status;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        try {
            proposal = new JSONObject(getIntent().getStringExtra("proposal_json"));
        } catch (Exception error) {
            finish();
            return;
        }

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(40, 40, 40, 40);

        TextView title = new TextView(this);
        title.setText("Approve exact Nexuss action");
        title.setTextSize(24);
        root.addView(title);

        TextView preview = new TextView(this);
        preview.setText(proposal.optString("exact_preview", "Preview unavailable"));
        preview.setTextIsSelectable(true);
        root.addView(preview, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));

        TextView hash = new TextView(this);
        hash.setText("Payload SHA-256:\n" + proposal.optString("payload_sha256"));
        hash.setTextIsSelectable(true);
        root.addView(hash);

        Button approve = new Button(this);
        approve.setText("Approve with biometric or device credential");
        approve.setOnClickListener(view -> authenticateAndExecute());
        root.addView(approve);

        Button reject = new Button(this);
        reject.setText("Reject");
        reject.setOnClickListener(view -> reject());
        root.addView(reject);

        status = new TextView(this);
        status.setText("No action has been taken.");
        root.addView(status);
        setContentView(root);
    }

    private void authenticateAndExecute() {
        int authenticators = BiometricManager.Authenticators.BIOMETRIC_STRONG
                | BiometricManager.Authenticators.DEVICE_CREDENTIAL;
        BiometricPrompt.PromptInfo promptInfo = new BiometricPrompt.PromptInfo.Builder()
                .setTitle("Approve Nexuss action")
                .setSubtitle(proposal.optString("target_label"))
                .setDescription("The displayed payload hash and exact preview are binding.")
                .setAllowedAuthenticators(authenticators)
                .build();
        BiometricPrompt prompt = new BiometricPrompt(
                this,
                ContextCompat.getMainExecutor(this),
                new BiometricPrompt.AuthenticationCallback() {
                    @Override
                    public void onAuthenticationSucceeded(
                            @NonNull BiometricPrompt.AuthenticationResult result) {
                        super.onAuthenticationSucceeded(result);
                        approveAndExecute();
                    }

                    @Override
                    public void onAuthenticationError(int code, @NonNull CharSequence message) {
                        super.onAuthenticationError(code, message);
                        status.setText("Approval not granted: " + message);
                    }
                });
        prompt.authenticate(promptInfo);
    }

    private void approveAndExecute() {
        status.setText("Submitting exact approval…");
        network.execute(() -> {
            try {
                SecureDeviceStore.DeviceIdentity identity =
                        new SecureDeviceStore(this).load();
                if (identity == null) {
                    throw new IllegalStateException("Trusted pairing is unavailable.");
                }
                new MobileFabricClient().decide(identity, proposal, true, true);
                ApprovedActionExecutor.ExecutionResult result =
                        new ApprovedActionExecutor(this).execute(proposal);
                new MobileFabricClient().evidence(identity, proposal, result);
                runOnUiThread(() -> status.setText(
                        result.executed()
                                ? "Action dispatch verified: " + result.resultCode()
                                : "Action failed closed: " + result.resultCode()));
            } catch (Exception error) {
                runOnUiThread(() -> status.setText("Action failed: " + error.getMessage()));
            }
        });
    }

    private void reject() {
        status.setText("Rejecting…");
        network.execute(() -> {
            try {
                SecureDeviceStore.DeviceIdentity identity =
                        new SecureDeviceStore(this).load();
                if (identity == null) {
                    throw new IllegalStateException("Trusted pairing is unavailable.");
                }
                new MobileFabricClient().decide(identity, proposal, false, false);
                runOnUiThread(() -> status.setText("Action rejected. Nothing was executed."));
            } catch (Exception error) {
                runOnUiThread(() -> status.setText("Rejection failed: " + error.getMessage()));
            }
        });
    }

    @Override
    protected void onDestroy() {
        network.shutdownNow();
        super.onDestroy();
    }
}
