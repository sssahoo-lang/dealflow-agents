package com.dealflow.analytics.web;

import com.dealflow.analytics.config.AnalyticsProperties;
import com.dealflow.analytics.outbox.OutboxRepository;
import com.dealflow.analytics.security.CurrentPrincipal;
import com.dealflow.analytics.security.Principal;
import jakarta.servlet.http.HttpServletRequest;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

/**
 * Consumer observability. Polling latency is a design choice rather than a
 * problem, but it should be measurable rather than assumed -- hence lag_seconds
 * and the dead-letter list.
 */
@RestController
@RequestMapping("/admin/outbox")
public class AdminController {

    private final OutboxRepository outbox;
    private final AnalyticsProperties properties;
    private final CurrentPrincipal currentPrincipal;

    public AdminController(
            OutboxRepository outbox,
            AnalyticsProperties properties,
            CurrentPrincipal currentPrincipal) {
        this.outbox = outbox;
        this.properties = properties;
        this.currentPrincipal = currentPrincipal;
    }

    private void requireAdmin(HttpServletRequest request) {
        Principal principal = currentPrincipal.of(request);
        if (!principal.isAdmin()) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Admin role required");
        }
    }

    @GetMapping("/status")
    public Map<String, Object> status(HttpServletRequest request) {
        requireAdmin(request);
        return outbox.status(properties.consumerName());
    }

    @GetMapping("/dead")
    public List<Map<String, Object>> dead(HttpServletRequest request) {
        requireAdmin(request);
        return outbox.deadLetters();
    }
}
