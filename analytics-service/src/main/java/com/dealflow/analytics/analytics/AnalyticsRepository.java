package com.dealflow.analytics.analytics;

import com.dealflow.analytics.dto.ConversionRow;
import com.dealflow.analytics.dto.ForecastResponse;
import com.dealflow.analytics.dto.LeaderboardRow;
import com.dealflow.analytics.dto.VelocityRow;
import java.math.BigDecimal;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

/**
 * Every aggregate is computed here at read time over the immutable facts. Nothing
 * is precomputed or incremented, which is what makes the read model safe to
 * rebuild by replaying the outbox.
 *
 * <p><b>Scoping is an explicit parameter on every method, never a global filter.</b>
 * A filter applied somewhere else is a filter that can be forgotten; passing
 * {@code ownerId} (null for admins) means a new query cannot accidentally return
 * another rep's pipeline, because it will not compile without deciding.
 */
@Repository
public class AnalyticsRepository {

    /** The pipeline ladder. 'lost' is deliberately absent: it is an exit, not a rung. */
    private static final String STAGE_LADDER =
            "(VALUES ('new',1),('qualified',2),('proposal',3),('negotiation',4),('won',5))";

    private final NamedParameterJdbcTemplate jdbc;

    public AnalyticsRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    private static Map<String, Object> scoped(Long ownerId) {
        Map<String, Object> params = new HashMap<>();
        params.put("ownerId", ownerId);
        return params;
    }

    public List<LeaderboardRow> leaderboard(Long ownerId, Instant from, Instant to, int limit) {
        Map<String, Object> params = scoped(ownerId);
        params.put("from", Timestamp.from(from));
        params.put("to", Timestamp.from(to));
        params.put("limit", limit);

        return jdbc.query(
                """
                -- One closing event per deal at most, so the value sums below cannot
                -- double count a deal that bounced between won and lost.
                WITH closed AS (
                    SELECT DISTINCT ON (deal_id) deal_id, to_stage, occurred_at
                      FROM analytics.deal_stage_transition
                     WHERE to_stage IN ('won','lost')
                       AND occurred_at >= :from AND occurred_at < :to
                     ORDER BY deal_id, occurred_at DESC
                )
                SELECT p.owner_id,
                       MIN(p.owner_name)  AS owner_name,
                       MIN(p.owner_email) AS owner_email,
                       COUNT(*) FILTER (WHERE c.to_stage = 'won')  AS deals_won,
                       COUNT(*) FILTER (WHERE c.to_stage = 'lost') AS deals_lost,
                       COALESCE(SUM(p.value) FILTER (WHERE c.to_stage = 'won'), 0) AS won_value,
                       COALESCE(SUM(p.value) FILTER (
                           WHERE p.stage NOT IN ('won','lost')), 0)               AS open_value,
                       -- Rounded: a day count carrying 15 decimal places reads as
                       -- noise and invites false precision.
                       ROUND(AVG(EXTRACT(EPOCH FROM (c.occurred_at - p.created_at)) / 86400.0)
                           FILTER (WHERE c.to_stage = 'won'), 2)                  AS avg_days_to_close
                  FROM analytics.deal_projection p
                  LEFT JOIN closed c ON c.deal_id = p.deal_id
                 WHERE (CAST(:ownerId AS bigint) IS NULL OR p.owner_id = :ownerId)
                 GROUP BY p.owner_id
                 ORDER BY won_value DESC, open_value DESC
                 LIMIT :limit
                """,
                params,
                (rs, i) -> {
                    int won = rs.getInt("deals_won");
                    int lost = rs.getInt("deals_lost");
                    Double winRate = (won + lost) == 0 ? null : (double) won / (won + lost);
                    Double avgDays = rs.getObject("avg_days_to_close") == null
                            ? null
                            : rs.getDouble("avg_days_to_close");
                    return new LeaderboardRow(
                            rs.getLong("owner_id"),
                            rs.getString("owner_name"),
                            rs.getString("owner_email"),
                            won,
                            lost,
                            rs.getBigDecimal("won_value"),
                            rs.getBigDecimal("open_value"),
                            winRate,
                            avgDays);
                });
    }

    /**
     * A funnel, computed from the furthest rung each deal has reached -- taking the
     * later of its current stage and any stage it transitioned into.
     *
     * <p>Using transitions alone would undercount: a deal created directly into
     * 'qualified' never produced a transition into it, but it plainly reached it.
     *
     * <p>"Reached" is ordinal, so a deal that jumped proposal -> won counts at every
     * rung below won, including the negotiation it skipped. That keeps the funnel
     * monotonic (a later rung can never exceed an earlier one), which is the property
     * that makes a conversion rate meaningful. The alternative -- counting only stages
     * actually transitioned into -- produces rates above 100% as soon as a rep skips a
     * step, which is worse.
     */
    public List<ConversionRow> conversion(Long ownerId) {
        return jdbc.query(
                """
                WITH ordered(stage, ord) AS """ + STAGE_LADDER + """
                ,
                deal_max AS (
                    SELECT p.deal_id,
                           GREATEST(
                               COALESCE((SELECT o.ord FROM ordered o WHERE o.stage = p.stage), 0),
                               COALESCE((SELECT MAX(o2.ord)
                                           FROM analytics.deal_stage_transition t
                                           JOIN ordered o2 ON o2.stage = t.to_stage
                                          WHERE t.deal_id = p.deal_id), 0)
                           ) AS max_ord
                      FROM analytics.deal_projection p
                     WHERE (CAST(:ownerId AS bigint) IS NULL OR p.owner_id = :ownerId)
                )
                SELECT a.stage AS from_stage,
                       b.stage AS to_stage,
                       (SELECT count(*) FROM deal_max d WHERE d.max_ord >= a.ord) AS entered,
                       (SELECT count(*) FROM deal_max d WHERE d.max_ord >= b.ord) AS advanced
                  FROM ordered a
                  JOIN ordered b ON b.ord = a.ord + 1
                 ORDER BY a.ord
                """,
                scoped(ownerId),
                (rs, i) -> {
                    long entered = rs.getLong("entered");
                    long advanced = rs.getLong("advanced");
                    return new ConversionRow(
                            rs.getString("from_stage"),
                            rs.getString("to_stage"),
                            entered,
                            advanced,
                            entered == 0 ? null : (double) advanced / entered);
                });
    }

    /** Time between consecutive transitions, per stage. */
    public List<VelocityRow> velocity(Long ownerId) {
        return jdbc.query(
                """
                WITH steps AS (
                    SELECT t.deal_id,
                           t.to_stage AS stage,
                           t.occurred_at,
                           LEAD(t.occurred_at) OVER (
                               PARTITION BY t.deal_id ORDER BY t.occurred_at) AS next_at
                      FROM analytics.deal_stage_transition t
                      JOIN analytics.deal_projection p ON p.deal_id = t.deal_id
                     WHERE (CAST(:ownerId AS bigint) IS NULL OR p.owner_id = :ownerId)
                )
                SELECT stage,
                       ROUND(AVG(EXTRACT(EPOCH FROM (next_at - occurred_at)) / 86400.0), 2)
                           AS avg_days,
                       ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (
                           ORDER BY EXTRACT(EPOCH FROM (next_at - occurred_at)) / 86400.0
                       )::numeric, 2) AS median_days,
                       COUNT(*) AS sample_size
                  FROM steps
                 WHERE next_at IS NOT NULL
                 GROUP BY stage
                 ORDER BY stage
                """,
                scoped(ownerId),
                (rs, i) -> new VelocityRow(
                        rs.getString("stage"),
                        rs.getObject("avg_days") == null ? null : rs.getDouble("avg_days"),
                        rs.getObject("median_days") == null ? null : rs.getDouble("median_days"),
                        rs.getLong("sample_size")));
    }

    public ForecastResponse forecast(Long ownerId, int horizonMonths) {
        Map<String, Object> params = scoped(ownerId);
        params.put("horizon", horizonMonths);

        List<ForecastResponse.ForecastBucket> buckets = jdbc.query(
                """
                SELECT to_char(date_trunc('month', p.expected_close_date), 'YYYY-MM') AS month,
                       SUM(p.value * sp.probability) AS weighted,
                       SUM(p.value)                  AS raw,
                       COUNT(*)                      AS deal_count
                  FROM analytics.deal_projection p
                  JOIN analytics.stage_probability sp ON sp.stage = p.stage
                 WHERE p.stage NOT IN ('won','lost')
                   AND p.expected_close_date IS NOT NULL
                   AND p.expected_close_date <
                       (CURRENT_DATE + make_interval(months => :horizon))
                   AND (CAST(:ownerId AS bigint) IS NULL OR p.owner_id = :ownerId)
                 GROUP BY 1
                 ORDER BY 1
                """,
                params,
                (rs, i) -> new ForecastResponse.ForecastBucket(
                        rs.getString("month"),
                        rs.getBigDecimal("weighted"),
                        rs.getBigDecimal("raw"),
                        rs.getLong("deal_count")));

        // Open deals with no close date can't be bucketed. Reporting them
        // separately keeps the forecast from quietly looking smaller than the
        // pipeline actually is.
        Map<String, Object> unscheduled = jdbc.queryForMap(
                """
                SELECT COUNT(*) AS deal_count, COALESCE(SUM(value), 0) AS value
                  FROM analytics.deal_projection
                 WHERE stage NOT IN ('won','lost')
                   AND expected_close_date IS NULL
                   AND (CAST(:ownerId AS bigint) IS NULL OR owner_id = :ownerId)
                """,
                params);

        BigDecimal weightedTotal = buckets.stream()
                .map(ForecastResponse.ForecastBucket::weighted)
                .reduce(BigDecimal.ZERO, BigDecimal::add);
        BigDecimal rawTotal = buckets.stream()
                .map(ForecastResponse.ForecastBucket::raw)
                .reduce(BigDecimal.ZERO, BigDecimal::add);

        return new ForecastResponse(
                horizonMonths,
                Instant.now(),
                weightedTotal.setScale(2, java.math.RoundingMode.HALF_UP),
                rawTotal.setScale(2, java.math.RoundingMode.HALF_UP),
                ((Number) unscheduled.get("deal_count")).longValue(),
                (BigDecimal) unscheduled.get("value"),
                buckets);
    }
}
