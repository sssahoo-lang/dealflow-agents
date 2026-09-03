package com.dealflow.analytics.security;

import static org.assertj.core.api.Assertions.assertThat;

import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import jakarta.servlet.FilterChain;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Date;
import java.util.Map;
import javax.crypto.SecretKey;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

/**
 * The cross-service trust boundary. This service accepts tokens minted by a
 * different codebase in a different language, so the rejection paths matter as
 * much as the happy path -- these are unit tests with no Spring context and no
 * database, so they stay fast enough to run on every change.
 */
class JwtAuthFilterTest {

    private static final String SECRET = "test-secret-that-is-long-enough-for-hs256-signing";

    private JwtAuthFilter filter;
    private MockHttpServletRequest request;
    private MockHttpServletResponse response;
    private RecordingChain chain;

    /** Records whether the request was allowed through. */
    static class RecordingChain implements FilterChain {
        boolean proceeded = false;

        @Override
        public void doFilter(jakarta.servlet.ServletRequest req, jakarta.servlet.ServletResponse res) {
            proceeded = true;
        }
    }

    @BeforeEach
    void setUp() {
        filter = new JwtAuthFilter(new JwtProperties(SECRET));
        request = new MockHttpServletRequest();
        response = new MockHttpServletResponse();
        chain = new RecordingChain();
    }

    private String token(String secret, Map<String, Object> claims, Instant expiry) {
        SecretKey key = Keys.hmacShaKeyFor(secret.getBytes(StandardCharsets.UTF_8));
        return Jwts.builder()
                .subject("rep@demo.com")
                .claims(claims)
                .expiration(Date.from(expiry))
                .signWith(key)
                .compact();
    }

    private String validToken() {
        return token(SECRET, Map.of("uid", 2, "role", "rep"), Instant.now().plusSeconds(3600));
    }

    @Test
    void acceptsATokenSignedWithTheSharedSecret() throws Exception {
        request.addHeader("Authorization", "Bearer " + validToken());

        filter.doFilter(request, response, chain);

        assertThat(chain.proceeded).isTrue();
        assertThat(response.getStatus()).isEqualTo(200);
    }

    @Test
    void resolvesClaimsIntoAPrincipal() throws Exception {
        request.addHeader("Authorization", "Bearer " + validToken());

        filter.doFilter(request, response, chain);

        Principal principal = (Principal) request.getAttribute(Principal.ATTRIBUTE);
        assertThat(principal).isNotNull();
        assertThat(principal.userId()).isEqualTo(2L);
        assertThat(principal.email()).isEqualTo("rep@demo.com");
        assertThat(principal.role()).isEqualTo("rep");
        assertThat(principal.isAdmin()).isFalse();
    }

    @Test
    void recognisesTheAdminRole() throws Exception {
        request.addHeader(
                "Authorization",
                "Bearer " + token(SECRET, Map.of("uid", 1, "role", "admin"),
                        Instant.now().plusSeconds(3600)));

        filter.doFilter(request, response, chain);

        Principal principal = (Principal) request.getAttribute(Principal.ATTRIBUTE);
        assertThat(principal.isAdmin()).isTrue();
    }

    @Test
    void rejectsAMissingHeader() throws Exception {
        filter.doFilter(request, response, chain);

        assertThat(chain.proceeded).isFalse();
        assertThat(response.getStatus()).isEqualTo(401);
    }

    @Test
    void rejectsAMalformedToken() throws Exception {
        request.addHeader("Authorization", "Bearer not-a-jwt");

        filter.doFilter(request, response, chain);

        assertThat(chain.proceeded).isFalse();
        assertThat(response.getStatus()).isEqualTo(401);
    }

    @Test
    void rejectsATokenSignedWithADifferentSecret() throws Exception {
        String forged = token(
                "a-completely-different-secret-of-sufficient-length",
                Map.of("uid", 1, "role", "admin"),
                Instant.now().plusSeconds(3600));
        request.addHeader("Authorization", "Bearer " + forged);

        filter.doFilter(request, response, chain);

        assertThat(chain.proceeded).isFalse();
        assertThat(response.getStatus()).isEqualTo(401);
    }

    @Test
    void rejectsAnExpiredToken() throws Exception {
        request.addHeader(
                "Authorization",
                "Bearer " + token(SECRET, Map.of("uid", 1, "role", "admin"),
                        Instant.now().minusSeconds(60)));

        filter.doFilter(request, response, chain);

        assertThat(chain.proceeded).isFalse();
        assertThat(response.getStatus()).isEqualTo(401);
    }

    @Test
    void rejectsATokenWithoutUidAndRoleClaims() throws Exception {
        // A token minted before those claims existed. Letting it through would
        // leave this service unable to scope a query -- and scoping to
        // "everything" would leak other reps' pipelines.
        String legacy = token(SECRET, Map.of(), Instant.now().plusSeconds(3600));
        request.addHeader("Authorization", "Bearer " + legacy);

        filter.doFilter(request, response, chain);

        assertThat(chain.proceeded).isFalse();
        assertThat(response.getStatus()).isEqualTo(401);
    }

    @Test
    void healthEndpointNeedsNoToken() {
        request.setRequestURI("/actuator/health");

        assertThat(filter.shouldNotFilter(request)).isTrue();
    }

    @Test
    void everyOtherPathIsFiltered() {
        request.setRequestURI("/whoami");

        assertThat(filter.shouldNotFilter(request)).isFalse();
    }
}
