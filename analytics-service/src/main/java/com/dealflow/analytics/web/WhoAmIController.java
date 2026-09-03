package com.dealflow.analytics.web;

import com.dealflow.analytics.security.CurrentPrincipal;
import com.dealflow.analytics.security.Principal;
import jakarta.servlet.http.HttpServletRequest;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Proves the cross-service auth path works: a token minted by the Python API is
 * accepted here, and its claims resolve to a caller this service can scope on.
 *
 * <p>Kept beyond the skeleton step because it stays useful for debugging a token
 * without hitting a real analytics query.
 */
@RestController
public class WhoAmIController {

    private final CurrentPrincipal currentPrincipal;

    public WhoAmIController(CurrentPrincipal currentPrincipal) {
        this.currentPrincipal = currentPrincipal;
    }

    @GetMapping("/whoami")
    public Map<String, Object> whoami(HttpServletRequest request) {
        Principal principal = currentPrincipal.of(request);
        return Map.of(
                "userId", principal.userId(),
                "email", principal.email(),
                "role", principal.role(),
                "isAdmin", principal.isAdmin());
    }
}
