package com.dealflow.analytics.rules;

import java.math.BigDecimal;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.time.temporal.ChronoUnit;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;

/**
 * The facts one deal presents to the evaluator.
 *
 * <p>Derived values are computed against an injected {@link Clock} rather than
 * {@code Instant.now()}. That is what lets the 14-day boundary be tested exactly,
 * and it matters in practice: the container clock here has been observed drifting
 * more than a minute from the host.
 */
public record DealFacts(long dealId, long ownerId, Map<String, Object> values) {

    public static final String STAGE = "stage";
    public static final String VALUE = "value";
    public static final String SCORE = "score";
    public static final String PRIORITY = "priority";
    public static final String DAYS_SINCE_LAST_ACTIVITY = "days_since_last_activity";
    public static final String DAYS_REMAINING = "expected_close_date_days_remaining";

    public static DealFacts of(
            long dealId,
            long ownerId,
            String stage,
            BigDecimal value,
            Double score,
            String priority,
            Instant lastActivityAt,
            Instant createdAt,
            LocalDate expectedCloseDate,
            Clock clock) {

        Map<String, Object> facts = new HashMap<>();
        facts.put(STAGE, stage);
        facts.put(VALUE, value);
        facts.put(SCORE, score);
        facts.put(PRIORITY, priority);

        // A deal with no logged activity is measured from creation: "we have never
        // touched this" is staleness, not missing data.
        Instant since = lastActivityAt != null ? lastActivityAt : createdAt;
        facts.put(
                DAYS_SINCE_LAST_ACTIVITY,
                since == null ? null : Duration.between(since, Instant.now(clock)).toDays());

        // Elapsed duration, not calendar arithmetic: LocalDate.minusDays across a
        // DST boundary is off by an hour, and this is the field every staleness
        // rule keys on.
        facts.put(
                DAYS_REMAINING,
                expectedCloseDate == null
                        ? null
                        : ChronoUnit.DAYS.between(
                                LocalDate.ofInstant(Instant.now(clock), ZoneOffset.UTC),
                                expectedCloseDate));

        // Collections.unmodifiableMap, not Map.copyOf: several facts are
        // legitimately null (a deal with no score, no priority, no close date) and
        // Map.copyOf rejects null values outright.
        return new DealFacts(dealId, ownerId, Collections.unmodifiableMap(facts));
    }

    /** @throws UnknownFieldException when a rule names a fact that does not exist */
    public Object get(String field) {
        if (!values.containsKey(field)) {
            throw new UnknownFieldException(field);
        }
        return values.get(field);
    }
}
