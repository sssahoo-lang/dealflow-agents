package com.dealflow.analytics.outbox;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

/**
 * Reads the CRM's outbox and tracks this consumer's own progress.
 *
 * <p><b>The trap this design exists to avoid.</b> BIGSERIAL ids are assigned at
 * INSERT but only become visible at COMMIT. Transaction A can take id 100 while
 * transaction B takes 101 and commits first. A poller that reads
 * {@code WHERE id > last_seen}, sees 101 and stores {@code last_seen = 101} will
 * <em>never</em> see event 100. It is silent, and it shows up as a leaderboard
 * that is quietly a fraction of a percent wrong.
 *
 * <p>So progress is tracked by an anti-join against a ledger of processed ids,
 * not by a high-water mark: an event is unprocessed iff it has no ledger row.
 * {@code floor_event_id} is a pure optimisation to keep that join bounded --
 * correctness never depends on it, and setting it to 0 forever would only cost
 * index scan width.
 */
@Repository
public class OutboxRepository {

    private final NamedParameterJdbcTemplate jdbc;
    private final ObjectMapper objectMapper;

    public OutboxRepository(NamedParameterJdbcTemplate jdbc, ObjectMapper objectMapper) {
        this.jdbc = jdbc;
        this.objectMapper = objectMapper;
    }

    /** A method rather than a field: a field initialiser would run before the
     *  constructor assigns objectMapper. */
    private EventEnvelope mapRow(ResultSet rs, int rowNum) throws SQLException {
        JsonNode payload;
        try {
            payload = objectMapper.readTree(rs.getString("payload"));
        } catch (Exception e) {
            throw new SQLException("Unreadable payload on outbox event " + rs.getLong("id"), e);
        }
        return new EventEnvelope(
                rs.getLong("id"),
                rs.getString("aggregate_type"),
                rs.getLong("aggregate_id"),
                rs.getString("event_type"),
                rs.getInt("event_version"),
                payload,
                rs.getTimestamp("occurred_at").toInstant());
    }

    /**
     * Correct regardless of commit ordering: an event qualifies when it has no
     * processed_event row and is not in backoff. Requires that the outbox and the
     * ledger be joinable in one query, which is why they share a database.
     */
    public List<EventEnvelope> fetchBatch(String consumer, int batchSize) {
        return jdbc.query(
                """
                SELECT e.id, e.aggregate_type, e.aggregate_id, e.event_type,
                       e.event_version, e.payload::text AS payload, e.occurred_at
                  FROM public.outbox_events e
                  LEFT JOIN analytics.processed_event p ON p.event_id = e.id
                  LEFT JOIN analytics.failed_event    f ON f.event_id = e.id
                 WHERE e.id > COALESCE(
                           (SELECT floor_event_id FROM analytics.consumer_offset
                             WHERE consumer = :consumer), 0)
                   AND p.event_id IS NULL
                   AND (f.event_id IS NULL OR f.next_attempt_at <= now())
                 ORDER BY e.id
                 LIMIT :batchSize
                """,
                Map.of("consumer", consumer, "batchSize", batchSize),
                this::mapRow);
    }

    public void markDone(long eventId) {
        jdbc.update(
                """
                INSERT INTO analytics.processed_event (event_id, status)
                VALUES (:id, 'done')
                ON CONFLICT (event_id) DO NOTHING
                """,
                Map.of("id", eventId));
        jdbc.update("DELETE FROM analytics.failed_event WHERE event_id = :id", Map.of("id", eventId));
    }

    /** Permanently skip an event, but keep it visible via /admin/outbox/status. */
    public void markDead(long eventId, int attempts, String error) {
        jdbc.update(
                """
                INSERT INTO analytics.processed_event (event_id, status, attempts, last_error)
                VALUES (:id, 'dead', :attempts, :error)
                ON CONFLICT (event_id) DO UPDATE
                   SET status = 'dead', attempts = :attempts, last_error = :error
                """,
                Map.of("id", eventId, "attempts", attempts, "error", truncate(error)));
        jdbc.update("DELETE FROM analytics.failed_event WHERE event_id = :id", Map.of("id", eventId));
    }

    /** Exponential backoff: 2^attempts seconds before the event is retried. */
    public int recordFailure(long eventId, String error) {
        return jdbc.queryForObject(
                """
                INSERT INTO analytics.failed_event (event_id, attempts, last_error, next_attempt_at)
                VALUES (:id, 1, :error, now() + interval '2 seconds')
                ON CONFLICT (event_id) DO UPDATE
                   SET attempts = analytics.failed_event.attempts + 1,
                       last_error = :error,
                       next_attempt_at = now()
                           + (interval '1 second' * power(2, analytics.failed_event.attempts + 1))
                RETURNING attempts
                """,
                Map.of("id", eventId, "error", truncate(error)),
                Integer.class);
    }

    /**
     * Advance the floor to the highest *contiguous* processed id and drop ledger
     * rows below it. Contiguous matters: jumping past a gap would permanently
     * hide an event that is still in backoff.
     */
    public int compactOffset(String consumer) {
        Long contiguous = jdbc.queryForObject(
                """
                SELECT COALESCE(MAX(p.event_id), 0)
                  FROM analytics.processed_event p
                 WHERE NOT EXISTS (
                           SELECT 1 FROM public.outbox_events e
                            LEFT JOIN analytics.processed_event p2 ON p2.event_id = e.id
                            WHERE e.id <= p.event_id AND p2.event_id IS NULL)
                """,
                Map.of(),
                Long.class);

        if (contiguous == null || contiguous == 0) {
            return 0;
        }
        jdbc.update(
                """
                UPDATE analytics.consumer_offset
                   SET floor_event_id = :floor, updated_at = now()
                 WHERE consumer = :consumer AND floor_event_id < :floor
                """,
                Map.of("floor", contiguous, "consumer", consumer));
        return jdbc.update(
                "DELETE FROM analytics.processed_event WHERE event_id < :floor AND status = 'done'",
                Map.of("floor", contiguous));
    }

    public Map<String, Object> status(String consumer) {
        // Both pending_count and lag_seconds MUST filter on the floor, not just
        // on the absence of a ledger row. Compaction prunes processed_event rows
        // below the floor, so without this every compacted event reappears as
        // "pending" and lag climbs -- a dashboard screaming about a consumer that
        // is in fact fully caught up.
        return jdbc.queryForMap(
                """
                WITH floor AS (
                    SELECT COALESCE(
                        (SELECT floor_event_id FROM analytics.consumer_offset
                          WHERE consumer = :consumer), 0) AS id
                ),
                unprocessed AS (
                    SELECT e.id, e.occurred_at
                      FROM public.outbox_events e
                      LEFT JOIN analytics.processed_event p ON p.event_id = e.id
                     WHERE p.event_id IS NULL
                       AND e.id > (SELECT id FROM floor)
                )
                SELECT
                  (SELECT id FROM floor)                                         AS floor_event_id,
                  (SELECT count(*) FROM analytics.processed_event
                    WHERE status = 'done')                                       AS processed_count,
                  (SELECT count(*) FROM analytics.processed_event
                    WHERE status = 'dead')                                       AS dead_count,
                  (SELECT count(*) FROM analytics.failed_event)                  AS retrying_count,
                  (SELECT count(*) FROM unprocessed)                             AS pending_count,
                  (SELECT COALESCE(
                       EXTRACT(EPOCH FROM (now() - MIN(occurred_at))), 0)
                     FROM unprocessed)                                           AS lag_seconds
                """,
                Map.of("consumer", consumer));
    }

    public List<Map<String, Object>> deadLetters() {
        return jdbc.queryForList(
                """
                SELECT event_id, attempts, last_error, processed_at
                  FROM analytics.processed_event
                 WHERE status = 'dead'
                 ORDER BY event_id
                """,
                Map.of());
    }

    private static String truncate(String error) {
        if (error == null) {
            return null;
        }
        return error.length() <= 500 ? error : error.substring(0, 500);
    }
}
