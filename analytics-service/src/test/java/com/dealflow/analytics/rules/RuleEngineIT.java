package com.dealflow.analytics.rules;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.List;
import java.util.Map;
import javax.sql.DataSource;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;

/**
 * Reconciliation behaviour against the real schema.
 *
 * <p>The property that matters here is that repeated sweeps converge: the open
 * finding set is a function of current state, not of how many times the engine
 * has run.
 */
@SpringBootTest
@ActiveProfiles("test")
@DisplayName("Rule engine")
class RuleEngineIT {

    private static final long STALE_DEAL = 920_001L;
    private static final long HEALTHY_DEAL = 920_002L;
    private static final long BASE = 920_000L;

    @Autowired private RuleEngine engine;
    @Autowired private RuleRepository repository;
    @Autowired private DataSource dataSource;

    private JdbcTemplate jdbc;

    @BeforeEach
    void setUp() {
        jdbc = new JdbcTemplate(dataSource);
        cleanUp();
        // A negotiation deal untouched for 30 days -> stale_negotiation should fire.
        deal(STALE_DEAL, "negotiation", "50000.00", 30);
        // Same stage, touched yesterday -> should not.
        deal(HEALTHY_DEAL, "negotiation", "50000.00", 1);
    }

    @AfterEach
    void tearDown() {
        cleanUp();
    }

    private void cleanUp() {
        // ALL findings, not just the fixture's. runAll() evaluates every deal in the
        // projection, so a sweep here opens findings on real data too -- leaving
        // those behind would pollute a shared dev database with test-triggered
        // alerts. Safe to clear: findings are entirely derived state that the next
        // sweep reconstructs.
        jdbc.update("DELETE FROM analytics.rule_finding");
        jdbc.update("DELETE FROM analytics.deal_projection WHERE deal_id >= ?", BASE);
    }

    private void deal(long id, String stage, String value, int quietDays) {
        jdbc.update(
                """
                INSERT INTO analytics.deal_projection (
                    deal_id, company_id, company_name, owner_id, owner_email, owner_name,
                    name, stage, value, created_at, stage_changed_at, last_activity_at,
                    last_event_id)
                VALUES (?, 1, 'Fixture Co', 920, 'rep920@fixture.test', 'Rep 920',
                        'Rule fixture', ?, ?::numeric,
                        now() - interval '90 days', now() - interval '90 days',
                        now() - make_interval(days => ?), 0)
                """,
                id, stage, value, quietDays);
    }

    private long ruleId(String code) {
        return jdbc.queryForObject(
                "SELECT id FROM analytics.rule_definition WHERE code = ?", Long.class, code);
    }

    private List<Map<String, Object>> openFindingsFor(long dealId) {
        return jdbc.queryForList(
                "SELECT * FROM analytics.rule_finding WHERE deal_id = ? AND status = 'open'",
                dealId);
    }

    @Test
    @DisplayName("opens a finding on a stale deal and spares a healthy one")
    void opensFindingsOnlyWhereTheRuleHolds() {
        engine.runAll();

        assertThat(openFindingsFor(STALE_DEAL)).hasSize(1);
        assertThat(openFindingsFor(HEALTHY_DEAL)).isEmpty();
    }

    @Test
    @DisplayName("running twice does not duplicate the finding")
    void reconcilesRatherThanAccumulates() {
        engine.runAll();
        engine.runAll();
        engine.runAll();

        assertThat(openFindingsFor(STALE_DEAL))
                .as("an hourly sweep must not create 24 rows a day for one stuck deal")
                .hasSize(1);
    }

    @Test
    @DisplayName("logging activity resolves the finding on the next sweep")
    void resolvesWhenTheConditionClears() {
        engine.runAll();
        assertThat(openFindingsFor(STALE_DEAL)).hasSize(1);

        // The rep finally makes contact.
        jdbc.update(
                "UPDATE analytics.deal_projection SET last_activity_at = now() WHERE deal_id = ?",
                STALE_DEAL);
        engine.runAll();

        assertThat(openFindingsFor(STALE_DEAL)).isEmpty();
        String status = jdbc.queryForObject(
                "SELECT status FROM analytics.rule_finding WHERE deal_id = ? ORDER BY id DESC LIMIT 1",
                String.class, STALE_DEAL);
        assertThat(status).isEqualTo("resolved");
    }

    @Test
    @DisplayName("a finding carries why it fired")
    void findingsExplainThemselves() {
        engine.runAll();

        Map<String, Object> finding = openFindingsFor(STALE_DEAL).get(0);
        assertThat(String.valueOf(finding.get("detail")))
                .contains("daysSinceLastActivity")
                .contains("negotiation");
    }

    @Test
    @DisplayName("a disabled rule does not fire")
    void disabledRulesAreSkipped() {
        long id = ruleId("stale_negotiation");
        repository.update(id, false, null, null);
        try {
            engine.runAll();
            assertThat(openFindingsFor(STALE_DEAL)).isEmpty();
        } finally {
            repository.update(id, true, null, null);
        }
    }

    @Test
    @DisplayName("a malformed rule is recorded and skipped, not guessed at")
    void malformedRuleFailsClosed() {
        long id = ruleId("stale_negotiation");
        jdbc.update(
                "UPDATE analytics.rule_definition SET condition = ?::jsonb WHERE id = ?",
                "{\"field\":\"stage\",\"op\":\"not_a_real_operator\",\"value\":1}", id);
        try {
            List<RuleEngine.RunSummary> summaries = engine.runAll();

            assertThat(openFindingsFor(STALE_DEAL))
                    .as("an unevaluable rule must not fire on anything")
                    .isEmpty();
            assertThat(summaries)
                    .filteredOn(s -> s.ruleCode().equals("stale_negotiation"))
                    .allSatisfy(s -> assertThat(s.error()).contains("not_a_real_operator"));
            assertThat(repository.byId(id).lastValidationError())
                    .as("the reason is stored so GET /rules can explain the silence")
                    .contains("not_a_real_operator");
        } finally {
            jdbc.update(
                    "UPDATE analytics.rule_definition SET condition = ?::jsonb, "
                            + "last_validation_error = NULL WHERE id = ?",
                    "{\"all\": [{\"op\": \"eq\", \"field\": \"stage\", \"value\": \"negotiation\"}, "
                            + "{\"op\": \"gte\", \"field\": \"days_since_last_activity\", \"value\": 14}]}",
                    id);
        }
    }

    @Test
    @DisplayName("every sweep is recorded, so silence is distinguishable from failure")
    void sweepsAreRecorded() {
        int before = jdbc.queryForObject(
                "SELECT count(*) FROM analytics.rule_run", Integer.class);

        engine.runAll();

        int after = jdbc.queryForObject(
                "SELECT count(*) FROM analytics.rule_run WHERE finished_at IS NOT NULL",
                Integer.class);
        assertThat(after).isGreaterThan(before);
    }
}
