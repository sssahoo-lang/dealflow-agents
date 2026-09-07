package com.dealflow.analytics.security;

import static org.assertj.core.api.Assertions.assertThat;

import io.jsonwebtoken.Jwts;
import jakarta.servlet.FilterChain;
import java.security.KeyPair;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Date;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

/**
 * The cross-service trust boundary. This service accepts tokens minted by a
 * different codebase in a different language, so the rejection paths matter as
 * much as the happy path -- these are unit tests with no Spring context and no
 * database, so they stay fast enough to run on every change.
 *
 * <p>Tokens are RS256. Note that no test here can produce a token this filter
 * would accept without holding a private key the filter never sees, which is the
 * property the whole design turns on.
 */
class JwtAuthFilterTest {

    /** Stands in for the CRM's keypair: the test signs, the filter only verifies. */
    private static final KeyPair CRM = RsaTestKeys.generate();

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
        JwksKeyProvider keys = new JwksKeyProvider(
                new JwtProperties("http://api:8000/.well-known/jwks.json",
                        Duration.ofSeconds(30), Duration.ofSeconds(3)),
                () -> RsaTestKeys.jwks(CRM),
                Clock.systemUTC());
        filter = new JwtAuthFilter(keys);
        request = new MockHttpServletRequest();
        response = new MockHttpServletResponse();
        chain = new RecordingChain();
    }

    private String token(KeyPair signer, Map<String, Object> claims, Instant expiry) {
        return Jwts.builder()
                .header().keyId(RsaTestKeys.kid(signer)).and()
                .subject("rep@demo.com")
                .claims(claims)
                .expiration(Date.from(expiry))
                .signWith(signer.getPrivate(), Jwts.SIG.RS256)
                .compact();
    }

    private String validToken() {
        return token(CRM, Map.of("uid", 2, "role", "rep"), Instant.now().plusSeconds(3600));
    }

    @Test
    void acceptsATokenSignedByTheCrmsPrivateKey() throws Exception {
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
                "Bearer " + token(CRM, Map.of("uid", 1, "role", "admin"),
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
    void rejectsATokenSignedByAnotherKey() throws Exception {
        // What an attacker who compromised this service could actually do: sign
        // with a key of their own. It is refused because its kid is not in the
        // CRM's JWKS -- and they cannot put it there.
        String forged = token(
                RsaTestKeys.generate(),
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
                "Bearer " + token(CRM, Map.of("uid", 1, "role", "admin"),
                        Instant.now().minusSeconds(60)));

        filter.doFilter(request, response, chain);

        assertThat(chain.proceeded).isFalse();
        assertThat(response.getStatus()).isEqualTo(401);
    }

    @Test
    void rejectsATokenWithNoKidHeader() throws Exception {
        // Without a kid there is no way to say which key should verify this, and
        // trying them all is how key confusion starts.
        String unnamed = Jwts.builder()
                .subject("rep@demo.com")
                .claims(Map.of("uid", 2, "role", "rep"))
                .expiration(Date.from(Instant.now().plusSeconds(3600)))
                .signWith(CRM.getPrivate(), Jwts.SIG.RS256)
                .compact();
        request.addHeader("Authorization", "Bearer " + unnamed);

        filter.doFilter(request, response, chain);

        assertThat(chain.proceeded).isFalse();
        assertThat(response.getStatus()).isEqualTo(401);
    }

    @Test
    void rejectsATokenWithoutUidAndRoleClaims() throws Exception {
        // A token minted before those claims existed. Letting it through would
        // leave this service unable to scope a query -- and scoping to
        // "everything" would leak other reps' pipelines.
        String legacy = token(CRM, Map.of(), Instant.now().plusSeconds(3600));
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
