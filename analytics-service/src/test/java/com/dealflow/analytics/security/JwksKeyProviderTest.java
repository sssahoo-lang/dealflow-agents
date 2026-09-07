package com.dealflow.analytics.security;

import static org.assertj.core.api.Assertions.assertThat;

import java.security.KeyPair;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.Test;

/**
 * The caching and refresh policy around the CRM's public keys.
 *
 * <p>Each test here corresponds to a way this could go wrong in production
 * rather than to a method: refetching on every request, never refetching and so
 * breaking rotation, or letting an attacker-chosen {@code kid} drive outbound
 * traffic.
 */
class JwksKeyProviderTest {

    private static final Duration COOLDOWN = Duration.ofSeconds(30);

    /** A clock the test moves by hand; no sleeping, no flakiness. */
    static class TickingClock extends Clock {
        Instant now = Instant.parse("2026-01-01T00:00:00Z");

        @Override public Instant instant() { return now; }
        @Override public ZoneOffset getZone() { return ZoneOffset.UTC; }
        @Override public Clock withZone(java.time.ZoneId zone) { return this; }
    }

    private static JwtProperties props() {
        return new JwtProperties("http://api:8000/.well-known/jwks.json", COOLDOWN,
                Duration.ofSeconds(3));
    }

    @Test
    void resolvesAKeyByItsThumbprint() {
        KeyPair pair = RsaTestKeys.generate();
        JwksKeyProvider provider = new JwksKeyProvider(
                props(), () -> RsaTestKeys.jwks(pair), new TickingClock());

        assertThat(provider.get(RsaTestKeys.kid(pair))).isEqualTo(pair.getPublic());
    }

    @Test
    void cachesAcrossCallsInsteadOfRefetchingPerRequest() {
        KeyPair pair = RsaTestKeys.generate();
        AtomicInteger fetches = new AtomicInteger();
        JwksKeyProvider provider = new JwksKeyProvider(props(), () -> {
            fetches.incrementAndGet();
            return RsaTestKeys.jwks(pair);
        }, new TickingClock());

        for (int i = 0; i < 5; i++) {
            assertThat(provider.get(RsaTestKeys.kid(pair))).isNotNull();
        }

        assertThat(fetches.get()).isEqualTo(1);
    }

    @Test
    void anUnknownKidIsRejectedWithoutRefetchingInsideTheCooldown() {
        // The kid comes from whoever sent the token. If every unknown one caused
        // a fetch, a stream of junk tokens would point this service's traffic at
        // the CRM.
        KeyPair pair = RsaTestKeys.generate();
        AtomicInteger fetches = new AtomicInteger();
        TickingClock clock = new TickingClock();
        JwksKeyProvider provider = new JwksKeyProvider(props(), () -> {
            fetches.incrementAndGet();
            return RsaTestKeys.jwks(pair);
        }, clock);

        provider.get(RsaTestKeys.kid(pair));   // one legitimate fetch
        for (int i = 0; i < 20; i++) {
            assertThat(provider.get("kid-that-does-not-exist-" + i)).isNull();
        }

        assertThat(fetches.get()).isEqualTo(1);
    }

    @Test
    void picksUpARotatedKeyOnceTheCooldownHasPassed() {
        // The rotation story end to end: the CRM starts signing with a new key,
        // and this service recovers on its own, with no restart and nobody
        // copying a value between two config files.
        KeyPair oldKey = RsaTestKeys.generate();
        KeyPair newKey = RsaTestKeys.generate();
        AtomicReference<String> served = new AtomicReference<>(RsaTestKeys.jwks(oldKey));
        TickingClock clock = new TickingClock();
        JwksKeyProvider provider = new JwksKeyProvider(props(), served::get, clock);

        assertThat(provider.get(RsaTestKeys.kid(oldKey))).isNotNull();

        served.set(RsaTestKeys.jwks(oldKey, newKey));
        assertThat(provider.get(RsaTestKeys.kid(newKey)))
                .as("inside the cooldown the new kid is not yet resolvable")
                .isNull();

        clock.now = clock.now.plus(COOLDOWN).plusSeconds(1);

        assertThat(provider.get(RsaTestKeys.kid(newKey))).isEqualTo(newKey.getPublic());
        assertThat(provider.get(RsaTestKeys.kid(oldKey)))
                .as("tokens signed before the rotation must keep verifying")
                .isEqualTo(oldKey.getPublic());
    }

    @Test
    void keepsCachedKeysWhenTheCrmIsUnreachable() {
        // A brief outage at the CRM must not invalidate every token in flight.
        KeyPair pair = RsaTestKeys.generate();
        AtomicReference<Boolean> failing = new AtomicReference<>(false);
        TickingClock clock = new TickingClock();
        JwksKeyProvider provider = new JwksKeyProvider(props(), () -> {
            if (failing.get()) {
                throw new java.net.ConnectException("connection refused");
            }
            return RsaTestKeys.jwks(pair);
        }, clock);

        provider.get(RsaTestKeys.kid(pair));
        failing.set(true);
        clock.now = clock.now.plus(COOLDOWN).plusSeconds(1);

        assertThat(provider.get("unknown-kid")).isNull();
        assertThat(provider.get(RsaTestKeys.kid(pair)))
                .as("the cached key survives a failed refresh")
                .isEqualTo(pair.getPublic());
    }

    @Test
    void returnsNullForAMissingKidRatherThanGuessing() {
        // Trying every key we hold would verify a token whose header says it was
        // signed by something else -- the shape of a key confusion attack.
        KeyPair pair = RsaTestKeys.generate();
        JwksKeyProvider provider = new JwksKeyProvider(
                props(), () -> RsaTestKeys.jwks(pair), new TickingClock());

        assertThat(provider.get(null)).isNull();
        assertThat(provider.get("")).isNull();
    }

    @Test
    void ignoresNonSigningAndNonRsaEntries() throws Exception {
        // A JWKS may legitimately carry keys for other purposes. They are skipped,
        // not treated as an error that would break verification entirely.
        KeyPair pair = RsaTestKeys.generate();
        String mixed = RsaTestKeys.jwks(pair).replace("{\"keys\":[",
                "{\"keys\":[{\"kty\":\"oct\",\"kid\":\"symmetric\"},"
                        + "{\"kty\":\"RSA\",\"use\":\"enc\",\"kid\":\"encryption\","
                        + "\"n\":\"AQAB\",\"e\":\"AQAB\"},");

        var parsed = JwksKeyProvider.parse(mixed);

        assertThat(parsed).containsOnlyKeys(RsaTestKeys.kid(pair));
    }
}
