package com.dealflow.analytics.projection;

import java.math.BigDecimal;
import java.sql.Date;
import java.sql.Timestamp;
import java.time.Instant;
import java.time.LocalDate;
import java.util.HashMap;
import java.util.Map;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

/**
 * Writes to the analytics read model.
 *
 * <p>Every statement here is idempotent by construction, which is what makes
 * redelivery a no-op rather than a corruption:
 * <ul>
 *   <li>the projection upsert applies only when the incoming event is newer than
 *       the one already recorded ({@code last_event_id}), so replay and
 *       out-of-order arrival are both handled by the same guard;
 *   <li>the fact tables carry a UNIQUE event_id and insert with
 *       ON CONFLICT DO NOTHING.
 * </ul>
 * There are no counters to double-count.
 */
@Repository
public class ProjectionRepository {

    private final NamedParameterJdbcTemplate jdbc;

    public ProjectionRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /** Money arrives as a string on the wire; parse to BigDecimal, never double. */
    private static BigDecimal money(String raw) {
        return raw == null ? BigDecimal.ZERO : new BigDecimal(raw);
    }

    private static Date date(String raw) {
        return raw == null || raw.isBlank() ? null : Date.valueOf(LocalDate.parse(raw));
    }

    private static Timestamp ts(String raw, Instant fallback) {
        if (raw == null || raw.isBlank()) {
            return Timestamp.from(fallback);
        }
        return Timestamp.from(Instant.parse(raw.replace("+00:00", "Z")));
    }

    public void upsertDeal(
            long eventId,
            long dealId,
            Map<String, String> text,
            String value,
            Double score,
            Instant occurredAt) {

        Map<String, Object> params = new HashMap<>();
        params.put("eventId", eventId);
        params.put("dealId", dealId);
        params.put("companyId", text.get("company_id") == null ? null : Long.valueOf(text.get("company_id")));
        params.put("companyName", text.get("company_name"));
        params.put("ownerId", Long.valueOf(text.getOrDefault("owner_id", "0")));
        params.put("ownerEmail", text.get("owner_email"));
        params.put("ownerName", text.get("owner_name"));
        params.put("name", text.getOrDefault("name", "(unnamed)"));
        params.put("stage", text.getOrDefault("stage", "unknown"));
        params.put("value", money(value));
        params.put("priority", text.get("priority"));
        params.put("score", score);
        params.put("expectedCloseDate", date(text.get("expected_close_date")));
        params.put("createdAt", ts(text.get("created_at"), occurredAt));
        params.put("stageChangedAt", ts(text.get("stage_changed_at"), occurredAt));

        jdbc.update(
                """
                INSERT INTO analytics.deal_projection (
                    deal_id, company_id, company_name, owner_id, owner_email, owner_name,
                    name, stage, value, priority, score, expected_close_date,
                    created_at, stage_changed_at, last_event_id)
                VALUES (
                    :dealId, :companyId, :companyName, :ownerId, :ownerEmail, :ownerName,
                    :name, :stage, :value, :priority, :score, :expectedCloseDate,
                    :createdAt, :stageChangedAt, :eventId)
                ON CONFLICT (deal_id) DO UPDATE SET
                    company_id          = EXCLUDED.company_id,
                    company_name        = EXCLUDED.company_name,
                    owner_id            = EXCLUDED.owner_id,
                    owner_email         = EXCLUDED.owner_email,
                    owner_name          = EXCLUDED.owner_name,
                    name                = EXCLUDED.name,
                    stage               = EXCLUDED.stage,
                    value               = EXCLUDED.value,
                    priority            = EXCLUDED.priority,
                    score               = EXCLUDED.score,
                    expected_close_date = EXCLUDED.expected_close_date,
                    stage_changed_at    = EXCLUDED.stage_changed_at,
                    last_event_id       = EXCLUDED.last_event_id,
                    updated_at          = now()
                -- The guard. An older event arriving late cannot clobber newer state.
                WHERE analytics.deal_projection.last_event_id < EXCLUDED.last_event_id
                """,
                params);
    }

    public void insertTransition(
            long eventId, long dealId, String fromStage, String toStage, Instant occurredAt) {
        jdbc.update(
                """
                INSERT INTO analytics.deal_stage_transition
                    (deal_id, from_stage, to_stage, occurred_at, event_id)
                VALUES (:dealId, :fromStage, :toStage, :occurredAt, :eventId)
                ON CONFLICT (event_id) DO NOTHING
                """,
                Map.of(
                        "dealId", dealId,
                        "fromStage", fromStage == null ? "" : fromStage,
                        "toStage", toStage,
                        "occurredAt", Timestamp.from(occurredAt),
                        "eventId", eventId));
    }

    public void insertActivityFact(
            long eventId, long activityId, Long dealId, String type, Instant occurredAt) {
        Map<String, Object> params = new HashMap<>();
        params.put("activityId", activityId);
        params.put("dealId", dealId);
        params.put("type", type);
        params.put("occurredAt", Timestamp.from(occurredAt));
        params.put("eventId", eventId);

        jdbc.update(
                """
                INSERT INTO analytics.activity_fact
                    (activity_id, deal_id, type, occurred_at, event_id)
                VALUES (:activityId, :dealId, :type, :occurredAt, :eventId)
                ON CONFLICT (activity_id) DO NOTHING
                """,
                params);

        if (dealId != null) {
            // Monotonic: only ever moves forward, so replaying an older activity
            // cannot make a deal look staler than it is.
            jdbc.update(
                    """
                    UPDATE analytics.deal_projection
                       SET last_activity_at = :occurredAt, updated_at = now()
                     WHERE deal_id = :dealId
                       AND (last_activity_at IS NULL OR last_activity_at < :occurredAt)
                    """,
                    Map.of("dealId", dealId, "occurredAt", Timestamp.from(occurredAt)));
        }
    }
}
