package com.dealflow.analytics.security;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.Jwts;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import io.jsonwebtoken.Header;
import io.jsonwebtoken.Locator;
import java.io.IOException;
import java.security.Key;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * Validates the RS256 tokens the Python API issues, against the CRM's published
 * public keys.
 *
 * <p>Tokens are verified, never minted here -- and now that is a property of the
 * cryptography rather than a promise about the code. This service holds no
 * signing material at all, so compromising it yields nothing that can forge a
 * token for the CRM. That mirrors, in the auth layer, what the SELECT-only
 * database role already enforces in Postgres.
 *
 * <p>The signing key is chosen per token by its {@code kid} header, via
 * {@link JwksKeyProvider}. Selecting a key by name and rejecting a name we
 * cannot resolve -- rather than trying every key we hold -- is what keeps key
 * rotation from turning into key confusion.
 */
@Component
public class JwtAuthFilter extends OncePerRequestFilter {

    private static final Logger log = LoggerFactory.getLogger(JwtAuthFilter.class);
    private static final String BEARER = "Bearer ";

    private final Locator<Key> keyLocator;

    public JwtAuthFilter(JwksKeyProvider keys) {
        this.keyLocator = new Locator<>() {
            @Override
            public Key locate(Header header) {
                // A missing or unresolvable kid yields null, and jjwt then throws
                // -- caught below and answered as 401, exactly like a bad
                // signature. An unverifiable token is unverifiable regardless of
                // which step could not complete.
                return keys.get(String.valueOf(header.get("kid")));
            }
        };
    }

    /** Health and docs stay open; everything else needs a token. */
    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        // CORS preflight carries no Authorization header by design; filtering it
        // would 401 the preflight and break every cross-origin request before the
        // real one is ever sent.
        if ("OPTIONS".equalsIgnoreCase(request.getMethod())) {
            return true;
        }
        String path = request.getRequestURI();
        return path.startsWith("/actuator/health") || path.equals("/");
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {

        String header = request.getHeader("Authorization");
        if (header == null || !header.startsWith(BEARER)) {
            unauthorized(response, "Missing bearer token");
            return;
        }

        try {
            Claims claims = Jwts.parser()
                    .keyLocator(keyLocator)
                    .build()
                    .parseSignedClaims(header.substring(BEARER.length()))
                    .getPayload();

            Object uid = claims.get("uid");
            Object role = claims.get("role");
            if (uid == null || role == null) {
                // A token minted before those claims existed. Without them this
                // service cannot scope a query at all, so failing is the only
                // safe option -- scoping to "everything" would leak other reps'
                // pipelines.
                unauthorized(response, "Token is missing uid/role claims");
                return;
            }

            request.setAttribute(
                    Principal.ATTRIBUTE,
                    new Principal(
                            Long.parseLong(String.valueOf(uid)),
                            claims.getSubject(),
                            String.valueOf(role)));
            chain.doFilter(request, response);

        } catch (JwtException | IllegalArgumentException e) {
            // Covers a bad signature, a malformed token and an expired one alike.
            log.debug("Rejected token: {}", e.getMessage());
            unauthorized(response, "Invalid or expired token");
        }
    }

    private void unauthorized(HttpServletResponse response, String message) throws IOException {
        response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
        response.setContentType("application/json");
        response.getWriter().write("{\"error\":\"" + message + "\"}");
    }
}
