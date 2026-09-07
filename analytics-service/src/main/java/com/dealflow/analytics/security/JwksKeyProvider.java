package com.dealflow.analytics.security;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.math.BigInteger;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.security.KeyFactory;
import java.security.PublicKey;
import java.security.spec.RSAPublicKeySpec;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Base64;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/**
 * Fetches and caches the CRM's public signing keys from its JWKS endpoint.
 *
 * <p>This class is the reason the analytics service no longer holds a shared
 * secret. It can check that a token came from the CRM; it cannot produce one.
 *
 * <p>Three behaviours are deliberate and each has a test:
 *
 * <ol>
 *   <li><b>Lazy, not eager.</b> Keys are fetched on first use, not at startup.
 *       A service that refuses to boot because a peer is not up yet turns an
 *       ordering hiccup into an outage, and compose has no ordering guarantee
 *       strong enough to rely on.
 *   <li><b>An unknown {@code kid} triggers one refetch.</b> That is what makes
 *       key rotation work with no coordinated restart: the CRM starts signing
 *       with a new key, this service sees a name it does not know, refetches,
 *       and continues.
 *   <li><b>Refetches are rate limited.</b> The kid in a token is chosen by
 *       whoever sent it. Without a cooldown, a stream of tokens bearing random
 *       kids would turn every verification into an outbound request -- this
 *       service would become an amplifier aimed at the CRM. Inside the cooldown
 *       an unknown kid is simply rejected, which is the correct answer anyway.
 * </ol>
 */
@Component
public class JwksKeyProvider {

    private static final Logger log = LoggerFactory.getLogger(JwksKeyProvider.class);

    /**
     * Where the JWKS document comes from. An interface rather than a hardcoded
     * HTTP call so the caching, cooldown and rotation behaviour can be tested
     * without standing up a server -- the parts worth testing here are the
     * decisions, not the transport.
     */
    @FunctionalInterface
    interface JwksSource {
        String fetch() throws Exception;
    }

    private final String describe;
    private final Duration refreshCooldown;
    private final JwksSource source;
    private final Clock clock;

    /** Swapped wholesale rather than mutated, so a reader never sees a half-built map. */
    private final AtomicReference<Map<String, PublicKey>> keys = new AtomicReference<>(Map.of());

    private volatile Instant lastFetch = Instant.EPOCH;

    // Explicit, because the package-private test constructor below makes two
    // candidates and Spring will not guess between them.
    @org.springframework.beans.factory.annotation.Autowired
    public JwksKeyProvider(JwtProperties properties) {
        this(properties, httpSource(properties), Clock.systemUTC());
    }

    /** Visible for testing: lets a test serve its own JWKS and control time. */
    JwksKeyProvider(JwtProperties properties, JwksSource source, Clock clock) {
        this.describe = properties.jwksUri();
        this.refreshCooldown = properties.refreshCooldown();
        this.source = source;
        this.clock = clock;
    }

    private static JwksSource httpSource(JwtProperties properties) {
        URI uri = URI.create(properties.jwksUri());
        HttpClient http =
                HttpClient.newBuilder().connectTimeout(properties.timeout()).build();
        return () -> {
            HttpResponse<String> response = http.send(
                    HttpRequest.newBuilder(uri).timeout(properties.timeout()).GET().build(),
                    HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() != 200) {
                throw new IllegalStateException(
                        "JWKS fetch returned HTTP " + response.statusCode());
            }
            return response.body();
        };
    }

    /**
     * The key named by {@code kid}, or null if it cannot be established.
     *
     * <p>Null means reject. Never fall back to "any key we happen to hold" -- a
     * token whose kid does not match the key that verifies it is, at best,
     * evidence of a bug and at worst an attempt at key confusion.
     */
    public PublicKey get(String kid) {
        if (kid == null || kid.isBlank()) {
            return null;
        }
        PublicKey cached = keys.get().get(kid);
        if (cached != null) {
            return cached;
        }
        if (!refresh()) {
            return null;
        }
        return keys.get().get(kid);
    }

    /** @return true if a fetch was attempted and succeeded. */
    private synchronized boolean refresh() {
        Instant now = clock.instant();
        if (now.isBefore(lastFetch.plus(refreshCooldown))) {
            log.debug("JWKS refresh suppressed by cooldown");
            return false;
        }
        lastFetch = now;
        try {
            Map<String, PublicKey> parsed = parse(source.fetch());
            keys.set(parsed);
            log.info("Loaded {} signing key(s) from {}", parsed.size(), describe);
            return true;
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return false;
        } catch (Exception e) {
            // Keep whatever keys are already cached: a CRM that is briefly
            // unreachable must not invalidate every token already in flight.
            log.warn("JWKS fetch from {} failed: {}", describe, e.toString());
            return false;
        }
    }

    /** Parses a JWK Set, keeping only RSA signing keys. */
    static Map<String, PublicKey> parse(String body) throws Exception {
        JsonNode keysNode = new ObjectMapper().readTree(body).path("keys");
        var out = new java.util.LinkedHashMap<String, PublicKey>();
        KeyFactory rsa = KeyFactory.getInstance("RSA");
        for (JsonNode jwk : keysNode) {
            // Anything that is not an RSA signing key is skipped rather than
            // rejected: a JWKS is allowed to carry keys for other purposes, and
            // a future encryption key must not break token verification.
            if (!"RSA".equals(jwk.path("kty").asText())) {
                continue;
            }
            String use = jwk.path("use").asText("sig");
            if (!"sig".equals(use)) {
                continue;
            }
            String kid = jwk.path("kid").asText(null);
            if (kid == null || kid.isBlank()) {
                continue;
            }
            BigInteger n = new BigInteger(1, decode(jwk.path("n").asText()));
            BigInteger e = new BigInteger(1, decode(jwk.path("e").asText()));
            out.put(kid, rsa.generatePublic(new RSAPublicKeySpec(n, e)));
        }
        return Map.copyOf(out);
    }

    private static byte[] decode(String b64u) {
        return Base64.getUrlDecoder().decode(b64u);
    }
}
