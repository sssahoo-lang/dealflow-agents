package com.dealflow.analytics.rules;

import com.dealflow.analytics.security.CurrentPrincipal;
import com.dealflow.analytics.security.Principal;
import com.fasterxml.jackson.databind.JsonNode;
import jakarta.servlet.http.HttpServletRequest;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

/** Rule definitions, findings, and manual sweeps. */
@RestController
@RequestMapping("/rules")
public class RulesController {

    private static final int MAX_LIMIT = 200;

    private final RuleRepository repository;
    private final RuleEngine engine;
    private final CurrentPrincipal currentPrincipal;

    public RulesController(
            RuleRepository repository, RuleEngine engine, CurrentPrincipal currentPrincipal) {
        this.repository = repository;
        this.engine = engine;
        this.currentPrincipal = currentPrincipal;
    }

    private Principal require(HttpServletRequest request) {
        return currentPrincipal.of(request);
    }

    private void requireAdmin(HttpServletRequest request) {
        if (!require(request).isAdmin()) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Admin role required");
        }
    }

    /** Rule definitions are org-wide config, so any authenticated caller may read them. */
    @GetMapping
    public Map<String, Object> list(HttpServletRequest request) {
        require(request);
        return Map.of("rules", repository.all());
    }

    public record RuleUpdate(Boolean enabled, String severity, JsonNode condition) {}

    @PatchMapping("/{id}")
    public RuleDefinition update(
            HttpServletRequest request, @PathVariable long id, @RequestBody RuleUpdate update) {
        requireAdmin(request);

        RuleDefinition existing = repository.byId(id);
        if (existing == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "No rule " + id);
        }
        if (update.severity() != null
                && !List.of("info", "warn", "critical").contains(update.severity())) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST, "severity must be info, warn or critical");
        }

        String conditionJson = null;
        if (update.condition() != null) {
            // Validate BEFORE persisting. A rule that cannot be parsed must never
            // reach the table, or the next sweep silently skips it.
            try {
                ConditionParser.parse(update.condition());
            } catch (RuntimeException e) {
                throw new ResponseStatusException(
                        HttpStatus.BAD_REQUEST, "Invalid condition: " + e.getMessage());
            }
            conditionJson = update.condition().toString();
        }

        repository.update(id, update.enabled(), update.severity(), conditionJson);
        return repository.byId(id);
    }

    /** Synchronous sweep, for demos and for verifying a rule change immediately. */
    @PostMapping("/run")
    public Map<String, Object> run(HttpServletRequest request) {
        requireAdmin(request);
        List<RuleEngine.RunSummary> summaries = engine.runAll();

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("rulesRun", summaries.size());
        response.put("totalOpened", summaries.stream().mapToInt(RuleEngine.RunSummary::opened).sum());
        response.put("totalResolved",
                summaries.stream().mapToInt(RuleEngine.RunSummary::resolved).sum());
        response.put("results", summaries);
        return response;
    }

    @GetMapping("/findings")
    public Map<String, Object> findings(
            HttpServletRequest request,
            @RequestParam(defaultValue = "open") String status,
            @RequestParam(defaultValue = "50") int limit) {

        Principal principal = require(request);
        if (limit < 1 || limit > MAX_LIMIT) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST, "limit must be between 1 and " + MAX_LIMIT);
        }
        if (!List.of("open", "resolved", "all").contains(status)) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST, "status must be open, resolved or all");
        }

        // A rep sees findings on their own deals only.
        Long ownerId = principal.isAdmin() ? null : principal.userId();
        List<Map<String, Object>> findings =
                repository.findings(ownerId, "all".equals(status) ? null : status, limit);
        return Map.of("status", status, "count", findings.size(), "findings", findings);
    }
}
