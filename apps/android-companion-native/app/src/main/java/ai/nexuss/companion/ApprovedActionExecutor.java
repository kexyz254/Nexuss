package ai.nexuss.companion;

import android.app.Notification;
import android.app.PendingIntent;
import android.app.RemoteInput;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;

final class ApprovedActionExecutor {
    private final Context context;

    ApprovedActionExecutor(Context context) {
        this.context = context.getApplicationContext();
    }

    ExecutionResult execute(JSONObject proposal) {
        try {
            String kind = proposal.getString("kind");
            return switch (kind) {
                case "dial_handoff" -> dial(proposal);
                case "sms_compose" -> composeSms(proposal);
                case "notification_reply" -> reply(proposal);
                case "open_conversation" -> openConversation(proposal);
                default -> result(
                        false,
                        false,
                        "none",
                        "UNSUPPORTED_ACTION_KIND",
                        null,
                        kind);
            };
        } catch (Exception error) {
            return result(
                    false,
                    false,
                    "execution_failed",
                    error.getClass().getSimpleName(),
                    null,
                    error.getMessage());
        }
    }

    private ExecutionResult dial(JSONObject proposal) throws Exception {
        String destination = proposal.getString("destination");
        Intent intent = new Intent(
                Intent.ACTION_DIAL,
                Uri.fromParts("tel", destination, null));
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        context.startActivity(intent);
        return result(
                true,
                false,
                "handoff_opened",
                "DIALER_OPENED",
                destination,
                proposal.getString("payload_sha256"));
    }

    private ExecutionResult composeSms(JSONObject proposal) throws Exception {
        String destination = proposal.getString("destination");
        Intent intent = new Intent(
                Intent.ACTION_SENDTO,
                Uri.fromParts("smsto", destination, null));
        intent.putExtra("sms_body", proposal.getString("body"));
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        context.startActivity(intent);
        return result(
                true,
                false,
                "handoff_opened",
                "SMS_COMPOSER_OPENED",
                destination,
                proposal.getString("payload_sha256"));
    }

    private ExecutionResult openConversation(JSONObject proposal) throws Exception {
        String key = proposal.getString("notification_key");
        NotificationActionRegistry.Entry entry = NotificationActionRegistry.get(key);
        if (entry == null || entry.contentIntent() == null) {
            return result(
                    false,
                    false,
                    "execution_failed",
                    "CONVERSATION_INTENT_UNAVAILABLE",
                    key,
                    proposal.getString("payload_sha256"));
        }
        entry.contentIntent().send();
        return result(
                true,
                false,
                "handoff_opened",
                "CONVERSATION_OPENED",
                key,
                proposal.getString("payload_sha256"));
    }

    private ExecutionResult reply(JSONObject proposal) throws Exception {
        String key = proposal.getString("notification_key");
        NotificationActionRegistry.Entry entry = NotificationActionRegistry.get(key);
        Notification.Action action = entry == null ? null : entry.replyAction();
        if (action == null || action.getRemoteInputs() == null) {
            return result(
                    false,
                    false,
                    "execution_failed",
                    "REMOTE_INPUT_UNAVAILABLE",
                    key,
                    proposal.getString("payload_sha256"));
        }

        RemoteInput[] remoteInputs = action.getRemoteInputs();
        Bundle results = new Bundle();
        for (RemoteInput remoteInput : remoteInputs) {
            results.putCharSequence(
                    remoteInput.getResultKey(),
                    proposal.getString("body"));
        }
        Intent fillInIntent = new Intent();
        RemoteInput.addResultsToIntent(remoteInputs, fillInIntent, results);
        action.actionIntent.send(context, 0, fillInIntent);
        return result(
                true,
                true,
                "dispatch_accepted",
                "REMOTE_INPUT_SENT",
                key,
                proposal.getString("payload_sha256"));
    }

    private static ExecutionResult result(
            boolean executed,
            boolean externalWrite,
            String scope,
            String code,
            String providerReference,
            String material) {
        String evidenceHash;
        try {
            evidenceHash = DeviceAssertion.sha256(
                    String.join(
                            "\n",
                            Boolean.toString(executed),
                            Boolean.toString(externalWrite),
                            scope,
                            code,
                            providerReference == null ? "" : providerReference,
                            material == null ? "" : material)
                            .getBytes(StandardCharsets.UTF_8));
        } catch (Exception error) {
            evidenceHash = "0".repeat(64);
        }
        return new ExecutionResult(
                executed,
                externalWrite,
                scope,
                code,
                providerReference,
                evidenceHash);
    }

    record ExecutionResult(
            boolean executed,
            boolean externalWritePerformed,
            String verificationScope,
            String resultCode,
            String providerReference,
            String evidenceSha256) {}
}
