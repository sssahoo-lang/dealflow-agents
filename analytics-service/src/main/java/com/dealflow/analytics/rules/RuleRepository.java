package com.dealflow.analytics.rules;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDate;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

/** Storage for rule definitions, findings, and sweep records. */
@Repository
public class RuleRepository {

    private final NamedParameterJdbcTemplate jdbc;
    private final ObjectMapper objectMapper;

    public RuleRepository(NamedParameterJdbcTemplate jdbc, ObjectMapper objectMapper) {
        this.jdbc = jdbc;
        this.objectMapper = objectMapper;
    }

    private RuleDefinition mapRule(ResultSet rs, int rowNum) throws SQLException {
        try {
            return new RuleDefinition(
                    rs.getLong("id"),
                    rs.getString("code"),
                    rs.getString("name"),
                    rs.getString("description"),
                    rs.getString("severity"),
                    objectMapper.readTree(rs.getString("condition")),
                    rs.getBoolean("enabled"),
                    rs.getString("last_validation_error"));
        } catch (Exception e) {
            throw new SQLException("Unreadable condition on rule " + rs.getLong("id"), e);
        }
    }

    public List<RuleDefinition> all() {
        return jdbc.query(
                "SELECT * FROM analytics.rule_definition ORDER BY id", Map.of(), this::mapRule);
    }

    public List<RuleDefinition> enabled() {
        return jdbc.query(
                "SELECT * FROM analytics.rule_definition WHERE enabled ORDER BY id",
                Map.of(),
                this::mapRule);
    }

    public RuleDefinition byId(long id) {
        List<RuleDefinition> rows = jdbc.query(
                "SELECT * FROM analytics.rule_definition WHERE id = :id",
                Map.of("id", id),
                this::mapRule);
        return rows.isEmpty() ? null : rows.get(0);
    }

    /** Surfaced through GET /rules so a disabled rule explains itself. */
    public void recordValidationError(long ruleId, String error) {
        // HashMap, not Map.of: null is the meaningful value here (it CLEARS a
        // previously recorded error) and Map.of throws on null values -- with a
        // null message, which surfaces downstream as "Invalid condition: null"
        // and hides the real cause.
        Map<String, Object> params = new HashMap<>();
        params.put("id", ruleId);
        params.put("error", error == null ? null : truncate(error));
        jdbc.update(
                """
                UPDATE analytics.rule_definition
                   SET last_validation_error = :error, updated_at = now()
                 WHERE id = :id
                """,
                params);
    }

    public void update(long id, Boolean enabled, String severity, String conditionJson) {
        Map<String, Object> params = new HashMap<>();
        params.put("id", id);
        params.put("enabled", enabled);
        params.put("severity", severity);
        params.put("condition", conditionJson);
        jdbc.update(
                """
                UPDATE analytics.rule_definition
                   SET enabled   = COALESCE(:enabled, enabled),
                       severity  = COALESCE(:severity, severity),
                       condition = COALESCE(CAST(:condition AS jsonb), condition),
                       updated_at = now()
                 WHERE id = :id
                """,
                params);
    }

    /** All deals, as facts. Scoping is applied by the caller, not here. */
    public List<DealFacts> facts(java.time.Clock clock) {
        return jdbc.query(
                """
                SELECT deal_id, owner_id, stage, value, score, priority,
                       last_activity_at, created_at, expected_close_date
                  FROM analytics.deal_projection
                """,
                Map.of(),
                (rs, i) -> DealFacts.of(
                        rs.getLong("deal_id"),
                        rs.getLong("owner_id"),
                        rs.getString("stage"),
                        rs.getBigDecimal("value"),
                        rs.getObject("score") == null ? null : rs.getDouble("score"),
                        rs.getString("priority"),
                        rs.getTimestamp("last_activity_at") == null
                                ? null
                                : rs.getTimestamp("last_activity_at").toInstant(),
                        rs.getTimestamp("created_at") == null
                                ? null
                                : rs.getTimestamp("created_at").toInstant(),
                        rs.getObject("expected_close_date") == null
                                ? null
                                : ((java.sql.Date) rs.getObject("expected_close_date"))
                                        .toLocalDate(),
                        clock));
    }

    /**
     * Open a finding, or leave the existing one alone.
     *
     * @return true when a new finding was opened
     */
    public boolean openFinding(long ruleId, long dealId, String detailJson) {
        // The partial unique index on (rule_id, deal_id) WHERE status='open' is what
        // makes this a no-op on the second sweep instead of a duplicate row.
        return jdbc.update(
                """
                INSERT INTO analytics.rule_finding (rule_id, deal_id, status, detail)
                VALUES (:ruleId, :dealId, 'open', CAST(:detail AS jsonb))
                ON CONFLICT (rule_id, deal_id) WHERE status = 'open' DO NOTHING
                """,
                Map.of("ruleId", ruleId, "dealId", dealId, "detail", detailJson)) > 0;
    }

    /** @return number of findings closed */
    public int resolveFindings(long ruleId, List<Long> stillFiringDealIds) {
        Map<String, Object> params = new HashMap<>();
        params.put("ruleId", ruleId);
        params.put("dealIds", stillFiringDealIds.isEmpty() ? List.of(-1L) : stillFiringDealIds);
        return jdbc.update(
                """
                UPDATE analytics.rule_finding
                   SET status = 'resolved', resolved_at = now()
                 WHERE rule_id = :ruleId
                   AND status = 'open'
                   AND deal_id NOT IN (:dealIds)
                """,
                params);
    }

    public long startRun(Long ruleId) {
        Map<String, Object> params = new HashMap<>();
        params.put("ruleId", ruleId);
        return jdbc.queryForObject(
                "INSERT INTO analytics.rule_run (rule_id) VALUES (:ruleId) RETURNING id",
                params,
                Long.class);
    }

    public void finishRun(long runId, int evaluated, int opened, int resolved, String error) {
        Map<String, Object> params = new HashMap<>();
        params.put("runId", runId);
        params.put("evaluated", evaluated);
        params.put("opened", opened);
        params.put("resolved", resolved);
        params.put("error", error == null ? null : truncate(error));
        jdbc.update(
                """
                UPDATE analytics.rule_run
                   SET finished_at = now(), evaluated_count = :evaluated,
                       opened_count = :opened, resolved_count = :resolved, error = :error
                 WHERE id = :runId
                """,
                params);
    }

    public List<Map<String, Object>> findings(Long ownerId, String status, int limit) {
        Map<String, Object> params = new HashMap<>();
        params.put("ownerId", ownerId);
        params.put("status", status);
        params.put("limit", limit);
        // A row mapper rather than queryForList: the driver hands back jsonb as a
        // PGobject, which Jackson serialises as {"type":"jsonb","value":"...","null":false}
        // -- leaking the driver's internals into the API instead of the JSON itself.
        return jdbc.query(
                """
                SELECT f.id, f.deal_id, f.status, f.opened_at, f.resolved_at, f.detail,
                       r.code AS rule_code, r.name AS rule_name, r.severity,
                       p.name AS deal_name, p.owner_id, p.stage
                  FROM analytics.rule_finding f
                  JOIN analytics.rule_definition r ON r.id = f.rule_id
                  LEFT JOIN analytics.deal_projection p ON p.deal_id = f.deal_id
                 WHERE (CAST(:status AS text) IS NULL OR f.status = :status)
                   AND (CAST(:ownerId AS bigint) IS NULL OR p.owner_id = :ownerId)
                 ORDER BY f.opened_at DESC
                 LIMIT :limit
                """,
                params,
                (rs, i) -> {
                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("id", rs.getLong("id"));
                    row.put("dealId", rs.getLong("deal_id"));
                    row.put("dealName", rs.getString("deal_name"));
                    row.put("ownerId", rs.getLong("owner_id"));
                    row.put("stage", rs.getString("stage"));
                    row.put("ruleCode", rs.getString("rule_code"));
                    row.put("ruleName", rs.getString("rule_name"));
                    row.put("severity", rs.getString("severity"));
                    row.put("status", rs.getString("status"));
                    row.put("openedAt", rs.getTimestamp("opened_at") == null
                            ? null : rs.getTimestamp("opened_at").toInstant());
                    row.put("resolvedAt", rs.getTimestamp("resolved_at") == null
                            ? null : rs.getTimestamp("resolved_at").toInstant());
                    String detail = rs.getString("detail");
                    try {
                        row.put("detail", detail == null ? null : objectMapper.readTree(detail));
                    } catch (Exception e) {
                        row.put("detail", null);
                    }
                    return row;
                });
    }

    private static String truncate(String value) {
        return value.length() <= 500 ? value : value.substring(0, 500);
    }
}
