package com.dealflow.analytics.analytics;

import com.dealflow.analytics.dto.ConversionRow;
import com.dealflow.analytics.dto.ForecastResponse;
import com.dealflow.analytics.dto.LeaderboardRow;
import com.dealflow.analytics.dto.VelocityRow;
import com.dealflow.analytics.security.CurrentPrincipal;
import com.dealflow.analytics.security.Principal;
import jakarta.servlet.http.HttpServletRequest;
import java.time.Clock;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.Map;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

/**
 * Read-only pipeline analytics.
 *
 * <p>Scoping happens here, once, and is passed down explicitly: an admin sees
 * every rep, a rep sees only their own pipeline. {@link #scopeFor} is the single
 * place that decision is made, so a new endpoint cannot forget it -- the
 * repository will not accept a query without an ownerId argument.
 */
@RestController
@RequestMapping("/analytics")
public class AnalyticsController {

    /** Guards against a caller asking for a decade of buckets. */
    private static final int MAX_HORIZON_MONTHS = 24;
    private static final int MAX_LIMIT = 100;

    private final AnalyticsRepository repository;
    private final CurrentPrincipal currentPrincipal;
    private final Clock clock;

    public AnalyticsController(
            AnalyticsRepository repository, CurrentPrincipal currentPrincipal, Clock clock) {
        this.repository = repository;
        this.currentPrincipal = currentPrincipal;
        this.clock = clock;
    }

    /** @return null for an admin (no filter), or the caller's own id for a rep */
    private Long scopeFor(HttpServletRequest request) {
        Principal principal = currentPrincipal.of(request);
        return principal.isAdmin() ? null : principal.userId();
    }

    /** Defaults to the last 90 days when the caller doesn't say. */
    private Instant fromOrDefault(Instant from) {
        return from != null ? from : Instant.now(clock).minus(90, ChronoUnit.DAYS);
    }

    private Instant toOrDefault(Instant to) {
        return to != null ? to : Instant.now(clock);
    }

    @GetMapping("/leaderboard")
    public Map<String, Object> leaderboard(
            HttpServletRequest request,
            @RequestParam(required = false)
                    @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) Instant from,
            @RequestParam(required = false)
                    @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) Instant to,
            @RequestParam(defaultValue = "10") int limit) {

        if (limit < 1 || limit > MAX_LIMIT) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST, "limit must be between 1 and " + MAX_LIMIT);
        }
        Instant start = fromOrDefault(from);
        Instant end = toOrDefault(to);
        if (!start.isBefore(end)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "from must be before to");
        }

        List<LeaderboardRow> rows =
                repository.leaderboard(scopeFor(request), start, end, limit);
        return Map.of("from", start, "to", end, "rows", rows);
    }

    @GetMapping("/conversion")
    public Map<String, Object> conversion(HttpServletRequest request) {
        List<ConversionRow> rows = repository.conversion(scopeFor(request));
        return Map.of("rows", rows);
    }

    @GetMapping("/velocity")
    public Map<String, Object> velocity(HttpServletRequest request) {
        List<VelocityRow> rows = repository.velocity(scopeFor(request));
        return Map.of("rows", rows);
    }

    @GetMapping("/forecast")
    public ForecastResponse forecast(
            HttpServletRequest request,
            @RequestParam(defaultValue = "3") int horizonMonths) {

        if (horizonMonths < 1 || horizonMonths > MAX_HORIZON_MONTHS) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST,
                    "horizonMonths must be between 1 and " + MAX_HORIZON_MONTHS);
        }
        return repository.forecast(scopeFor(request), horizonMonths);
    }
}
