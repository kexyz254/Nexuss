package ai.nexuss.companion;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.UUID;
import org.json.JSONArray;
import org.json.JSONObject;

final class MobileFabricClient {
    SecureDeviceStore.DeviceIdentity pair(
            String coreUrl,
            String pairingCode,
            String deviceLabel) throws Exception {
        JSONObject body = new JSONObject()
                .put("pairing_code", pairingCode)
                .put("device_label", deviceLabel);
        JSONObject response = jsonRequest(
                "POST",
                trim(coreUrl) + "/v1/mobile/pair",
                body.toString().getBytes(StandardCharsets.UTF_8),
                null,
                null);
        return new SecureDeviceStore.DeviceIdentity(
                trim(coreUrl),
                response.getString("device_id"),
                response.getString("device_token"));
    }

    JSONObject postSignal(
            SecureDeviceStore.DeviceIdentity identity,
            JSONObject signal) throws Exception {
        JSONObject batch = new JSONObject()
                .put("batch_id", UUID.randomUUID().toString())
                .put("sequence", System.currentTimeMillis())
                .put("device_time", Instant.now().toString())
                .put("batch_nonce", randomNonce())
                .put("signals", new JSONArray().put(signal));
        return assertedJsonRequest(
                identity,
                "POST",
                "/v1/mobile-fabric/signals",
                batch.toString().getBytes(StandardCharsets.UTF_8));
    }

    JSONArray pendingActions(SecureDeviceStore.DeviceIdentity identity) throws Exception {
        return assertedArrayRequest(
                identity,
                "GET",
                "/v1/mobile-fabric/actions/pending",
                new byte[0]);
    }

    JSONObject decide(
            SecureDeviceStore.DeviceIdentity identity,
            JSONObject proposal,
            boolean approve,
            boolean biometricVerified) throws Exception {
        String actionId = proposal.getString("action_id");
        JSONObject decision = new JSONObject()
                .put("approval_token", proposal.getString("approval_token"))
                .put("payload_sha256", proposal.getString("payload_sha256"))
                .put("decision", approve ? "approve" : "reject")
                .put("biometric_verified", biometricVerified)
                .put("decided_at", Instant.now().toString());
        return assertedJsonRequest(
                identity,
                "POST",
                "/v1/mobile-fabric/actions/" + actionId + "/decision",
                decision.toString().getBytes(StandardCharsets.UTF_8));
    }

    JSONArray approvedActions(SecureDeviceStore.DeviceIdentity identity) throws Exception {
        return assertedArrayRequest(
                identity,
                "GET",
                "/v1/mobile-fabric/actions/approved",
                new byte[0]);
    }

    JSONObject evidence(
            SecureDeviceStore.DeviceIdentity identity,
            JSONObject proposal,
            ApprovedActionExecutor.ExecutionResult result) throws Exception {
        String actionId = proposal.getString("action_id");
        JSONObject evidence = new JSONObject()
                .put("action_id", actionId)
                .put("payload_sha256", proposal.getString("payload_sha256"))
                .put("executed", result.executed())
                .put("external_write_performed", result.externalWritePerformed())
                .put("verification_scope", result.verificationScope())
                .put("result_code", result.resultCode())
                .put("provider_reference", result.providerReference())
                .put("observed_at", Instant.now().toString())
                .put("evidence_sha256", result.evidenceSha256());
        return assertedJsonRequest(
                identity,
                "POST",
                "/v1/mobile-fabric/actions/" + actionId + "/evidence",
                evidence.toString().getBytes(StandardCharsets.UTF_8));
    }

    private JSONObject assertedJsonRequest(
            SecureDeviceStore.DeviceIdentity identity,
            String method,
            String path,
            byte[] body) throws Exception {
        return jsonRequest(
                method,
                trim(identity.coreUrl()) + path,
                body,
                identity,
                path);
    }

    private JSONArray assertedArrayRequest(
            SecureDeviceStore.DeviceIdentity identity,
            String method,
            String path,
            byte[] body) throws Exception {
        String response = rawRequest(
                method,
                trim(identity.coreUrl()) + path,
                body,
                identity,
                path);
        return new JSONArray(response);
    }

    private JSONObject jsonRequest(
            String method,
            String url,
            byte[] body,
            SecureDeviceStore.DeviceIdentity identity,
            String path) throws Exception {
        return new JSONObject(rawRequest(method, url, body, identity, path));
    }

    private String rawRequest(
            String method,
            String url,
            byte[] body,
            SecureDeviceStore.DeviceIdentity identity,
            String path) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(url).openConnection();
        connection.setRequestMethod(method);
        connection.setConnectTimeout(15_000);
        connection.setReadTimeout(45_000);
        connection.setRequestProperty("Accept", "application/json");

        if (identity != null && path != null) {
            DeviceAssertion.SignedHeaders signed = DeviceAssertion.sign(
                    identity.deviceToken(),
                    method,
                    path,
                    body,
                    randomNonce());
            connection.setRequestProperty("X-Nexuss-Mobile-Device-ID", identity.deviceId());
            connection.setRequestProperty("X-Nexuss-Mobile-Token", identity.deviceToken());
            connection.setRequestProperty("X-Nexuss-Mobile-Timestamp", signed.timestamp());
            connection.setRequestProperty("X-Nexuss-Mobile-Nonce", signed.nonce());
            connection.setRequestProperty(
                    "X-Nexuss-Mobile-Body-SHA256",
                    signed.bodySha256());
            connection.setRequestProperty("X-Nexuss-Mobile-Assertion", signed.signature());
        }

        if (body.length > 0) {
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json");
            try (OutputStream output = connection.getOutputStream()) {
                output.write(body);
            }
        }

        int status = connection.getResponseCode();
        InputStream stream = status >= 400
                ? connection.getErrorStream()
                : connection.getInputStream();
        String response = readAll(stream);
        connection.disconnect();
        if (status < 200 || status >= 300) {
            throw new IllegalStateException("Nexuss HTTP " + status + ": " + response);
        }
        return response;
    }

    private static String readAll(InputStream stream) throws Exception {
        if (stream == null) {
            return "";
        }
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(stream, StandardCharsets.UTF_8))) {
            StringBuilder result = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) {
                result.append(line);
            }
            return result.toString();
        }
    }

    private static String randomNonce() {
        return UUID.randomUUID().toString().replace("-", "");
    }

    private static String trim(String url) {
        return url.endsWith("/") ? url.substring(0, url.length() - 1) : url;
    }
}
