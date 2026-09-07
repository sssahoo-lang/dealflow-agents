package com.dealflow.analytics.security;

import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.MessageDigest;
import java.security.interfaces.RSAPublicKey;
import java.util.Base64;

/**
 * RSA keypairs and the JWKS documents that describe them, for tests.
 *
 * <p>The kid is computed the same way the Python side computes it (RFC 7638
 * thumbprint over the canonical JWK). Two independent implementations agreeing
 * on a key's name is the whole basis of rotation working across the language
 * boundary, so the test helper derives it rather than inventing a name.
 */
final class RsaTestKeys {

    private RsaTestKeys() {}

    static KeyPair generate() {
        try {
            KeyPairGenerator generator = KeyPairGenerator.getInstance("RSA");
            generator.initialize(2048);
            return generator.generateKeyPair();
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    static String kid(KeyPair pair) {
        RSAPublicKey pub = (RSAPublicKey) pair.getPublic();
        String canonical = "{\"e\":\"" + b64u(pub.getPublicExponent())
                + "\",\"kty\":\"RSA\",\"n\":\"" + b64u(pub.getModulus()) + "\"}";
        try {
            return Base64.getUrlEncoder().withoutPadding().encodeToString(
                    MessageDigest.getInstance("SHA-256")
                            .digest(canonical.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    /** A JWKS document containing the public half of each pair. */
    static String jwks(KeyPair... pairs) {
        StringBuilder sb = new StringBuilder("{\"keys\":[");
        for (int i = 0; i < pairs.length; i++) {
            RSAPublicKey pub = (RSAPublicKey) pairs[i].getPublic();
            if (i > 0) {
                sb.append(',');
            }
            sb.append("{\"kty\":\"RSA\",\"use\":\"sig\",\"alg\":\"RS256\",\"kid\":\"")
                    .append(kid(pairs[i]))
                    .append("\",\"n\":\"").append(b64u(pub.getModulus()))
                    .append("\",\"e\":\"").append(b64u(pub.getPublicExponent()))
                    .append("\"}");
        }
        return sb.append("]}").toString();
    }

    private static String b64u(BigInteger value) {
        byte[] bytes = value.toByteArray();
        // BigInteger.toByteArray() prepends a zero byte for sign when the high
        // bit is set. A JWK carries an unsigned big-endian integer, so that byte
        // must go -- leaving it in produces a key that looks right and verifies
        // nothing.
        if (bytes.length > 1 && bytes[0] == 0) {
            byte[] trimmed = new byte[bytes.length - 1];
            System.arraycopy(bytes, 1, trimmed, 0, trimmed.length);
            bytes = trimmed;
        }
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }
}
