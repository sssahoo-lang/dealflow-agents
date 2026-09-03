package com.dealflow.analytics.security;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.stereotype.Component;

/** Reads the principal the filter put on the request. */
@Component
public class CurrentPrincipal {

    public Principal of(HttpServletRequest request) {
        Principal principal = (Principal) request.getAttribute(Principal.ATTRIBUTE);
        if (principal == null) {
            // Only reachable if a path is added to shouldNotFilter but still
            // expects a caller -- fail loudly rather than silently unscoped.
            throw new IllegalStateException("No principal on request; is the path excluded from JwtAuthFilter?");
        }
        return principal;
    }
}
