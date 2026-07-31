package ai.nexuss.companion;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

final class DeviceAssertion {
    private DeviceAssertion() {}

    static String sha256(byte[] value) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        return hex(digest.digest(value));
    }

    static SignedHeaders sign(
            String deviceToken,
            String method,
            String path,
            byte[] body,
            String nonce) throws Exception {
        String timestamp = Instant.now().toString();
        String bodyHash = sha256(body);
        String canonical = String.join(
                "\n",
                method.toUpperCase(),
                path,
                timestamp,
                nonce,
                bodyHash);
        Mac mac = Mac.getInstance("HmacSHA256");
        mac.init(new SecretKeySpec(
                deviceToken.getBytes(StandardCharsets.UTF_8),
                "HmacSHA256"));
        String signature = hex(
                mac.doFinal(canonical.getBytes(StandardCharsets.UTF_8)));
        return new SignedHeaders(timestamp, nonce, bodyHash, signature);
    }

    private static String hex(byte[] value) {
        char[] alphabet = "0123456789abcdef".toCharArray();
        char[] output = new char[value.length * 2];
        for (int index = 0; index < value.length; index++) {
            int unsigned = value[index] & 0xff;
            output[index * 2] = alphabet[unsigned >>> 4];
            output[index * 2 + 1] = alphabet[unsigned & 0x0f];
        }
        return new String(output);
    }

    record SignedHeaders(
            String timestamp,
            String nonce,
            String bodySha256,
            String signature) {}
}
