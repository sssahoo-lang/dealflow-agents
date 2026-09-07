package com.dealflow.analytics.security;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.Jwts;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import javax.crypto.SecretKey;
import io.jsonwebtoken.security.Keys;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * Validates the same HS256 token the Python API issues.
 *
 * <p>Tokens are verified, never minted here. Note the asymmetry this creates and
 * that the README names openly: because the secret is symmetric, a compromise of
 * this service could forge a token for the CRM. The documented fix is RS256 plus
 * a JWKS endpoint on the Python side; it is deferred, not overlooked.
 */
@Component
public class JwtAuthFilter extends OncePerRequestFilter {

    private static final Logger log = LoggerFactory.getLogger(JwtAuthFilter.class);
    private static final String BEARER = "Bearer ";

    private final SecretKey key;

    /** Minimum HMAC-SHA key size per RFC 7518 section 3.2. */
    static final int MIN_SECRET_BYTES = 32;

    public JwtAuthFilter(JwtProperties properties) {
        byte[] secret = properties.secret().getBytes(StandardCharsets.UTF_8);
        if (secret.length < MIN_SECRET_BYTES) {
            // jjwt enforces this; python-jose does not. Without this message the
            // failure reads as a library quirk rather than what it is: the two
            // services disagreeing about the shared secret's strength.
            throw new IllegalStateException(
                    "JWT_SECRET must be at least " + MIN_SECRET_BYTES + " bytes (got "
                            + secret.length + "). It is shared with the Python API, which "
                            + "validates the same floor -- set one value of sufficient "
                            + "length for both services.");
        }
        this.key = Keys.hmacShaKeyFor(secret);
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
                    .verifyWith(key)
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
