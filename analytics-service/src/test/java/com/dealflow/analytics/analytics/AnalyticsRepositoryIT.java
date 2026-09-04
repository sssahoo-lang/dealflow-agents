package com.dealflow.analytics.analytics;

import static org.assertj.core.api.Assertions.assertThat;

import com.dealflow.analytics.dto.ConversionRow;
import com.dealflow.analytics.dto.ForecastResponse;
import com.dealflow.analytics.dto.LeaderboardRow;
import com.dealflow.analytics.dto.VelocityRow;
import java.math.BigDecimal;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.List;
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
 * Analytics aggregates over a controlled fixture.
 *
 * <p>Rows are written straight into the projection rather than replayed through
 * the outbox: the consumer already has its own tests, and these need precise
 * control over dates and stages to assert on averages and funnels.
 *
 * <p>Ids are in a reserved range so the fixture can be cleaned up without
 * touching real data, and every assertion is scoped to it.
 */
@SpringBootTest
@ActiveProfiles("test")
@DisplayName("Analytics aggregates")
class AnalyticsRepositoryIT {

    private static final long REP_A = 910_001L;
    private static final long REP_B = 910_002L;
    private static final long BASE_DEAL = 910_000L;

    @Autowired private AnalyticsRepository repository;
    @Autowired private DataSource dataSource;

    private JdbcTemplate jdbc;
    private final Instant now = Instant.now();

    @BeforeEach
    void setUp() {
        jdbc = new JdbcTemplate(dataSource);
        cleanUp();
        seed();
    }

    @AfterEach
    void tearDown() {
        cleanUp();
    }

    private void cleanUp() {
        jdbc.update("DELETE FROM analytics.deal_stage_transition WHERE deal_id >= ?", BASE_DEAL);
        jdbc.update("DELETE FROM analytics.activity_fact WHERE deal_id >= ?", BASE_DEAL);
        jdbc.update("DELETE FROM analytics.deal_projection WHERE deal_id >= ?", BASE_DEAL);
    }

    private void deal(long id, long owner, String stage, String value, String closeDate, int createdDaysAgo) {
        jdbc.update(
                """
                INSERT INTO analytics.deal_projection (
                    deal_id, company_id, company_name, owner_id, owner_email, owner_name,
                    name, stage, value, expected_close_date, created_at, stage_changed_at,
                    last_event_id)
                VALUES (?, 1, 'Fixture Co', ?, ?, ?, ?, ?, ?::numeric, ?::date,
                        now() - make_interval(days => ?), now(), 0)
                """,
                id, owner,
                "rep" + owner + "@fixture.test", "Rep " + owner,
                "Fixture deal " + id, stage, value, closeDate, createdDaysAgo);
    }

    private void transition(long dealId, String from, String to, int daysAgo) {
        jdbc.update(
                """
                INSERT INTO analytics.deal_stage_transition
                    (deal_id, from_stage, to_stage, occurred_at, event_id)
                VALUES (?, ?, ?, now() - make_interval(days => ?), ?)
                """,
                dealId, from, to, daysAgo, -(dealId * 100 + daysAgo));
    }

    /**
     * Rep A: one won (10 days to close), one lost, one open in proposal.
     * Rep B: one open in negotiation. Enough to make every aggregate non-trivial
     * and to prove one rep's numbers never leak into the other's.
     */
    private void seed() {
        deal(BASE_DEAL + 1, REP_A, "won", "100000.00", null, 40);
        transition(BASE_DEAL + 1, "new", "qualified", 35);
        transition(BASE_DEAL + 1, "qualified", "proposal", 33);
        transition(BASE_DEAL + 1, "proposal", "won", 30);

        deal(BASE_DEAL + 2, REP_A, "lost", "50000.00", null, 40);
        transition(BASE_DEAL + 2, "new", "qualified", 36);
        transition(BASE_DEAL + 2, "qualified", "lost", 32);

        deal(BASE_DEAL + 3, REP_A, "proposal", "75000.50", "2026-10-15", 20);
        transition(BASE_DEAL + 3, "new", "qualified", 15);
        transition(BASE_DEAL + 3, "qualified", "proposal", 10);

        deal(BASE_DEAL + 4, REP_B, "negotiation", "200000.00", "2026-11-20", 25);
        transition(BASE_DEAL + 4, "new", "negotiation", 12);
    }

    private List<LeaderboardRow> leaderboardFor(Long ownerId) {
        return repository
                .leaderboard(ownerId, now.minus(90, ChronoUnit.DAYS), now, 50)
                .stream()
                .filter(r -> r.ownerId() == REP_A || r.ownerId() == REP_B)
                .toList();
    }

    // --- leaderboard ---------------------------------------------------------

    @Test
    @DisplayName("counts wins, losses and open value per rep")
    void leaderboardAggregates() {
        LeaderboardRow repA = leaderboardFor(null).stream()
                .filter(r -> r.ownerId() == REP_A).findFirst().orElseThrow();

        assertThat(repA.dealsWon()).isEqualTo(1);
        assertThat(repA.dealsLost()).isEqualTo(1);
        assertThat(repA.wonValue()).isEqualByComparingTo("100000.00");
        // Only the open proposal counts as open; won and lost are excluded.
        assertThat(repA.openValue()).isEqualByComparingTo("75000.50");
        assertThat(repA.winRate()).isEqualTo(0.5);
    }

    @Test
    @DisplayName("average days to close is measured from creation to the won transition")
    void leaderboardAverageDaysToClose() {
        LeaderboardRow repA = leaderboardFor(null).stream()
                .filter(r -> r.ownerId() == REP_A).findFirst().orElseThrow();

        // Created 40 days ago, won 30 days ago.
        assertThat(repA.avgDaysToClose()).isCloseTo(10.0, org.assertj.core.data.Offset.offset(0.5));
    }

    @Test
    @DisplayName("a rep with nothing closed reports a null win rate, not zero")
    void nullWinRateWhenNothingClosed() {
        LeaderboardRow repB = leaderboardFor(null).stream()
                .filter(r -> r.ownerId() == REP_B).findFirst().orElseThrow();

        assertThat(repB.dealsWon()).isZero();
        assertThat(repB.winRate())
                .as("0% and 'no data' are different claims and must not look alike")
                .isNull();
    }

    @Test
    @DisplayName("a rep sees only their own row")
    void leaderboardIsScoped() {
        List<LeaderboardRow> scoped = leaderboardFor(REP_A);

        assertThat(scoped).hasSize(1);
        assertThat(scoped.get(0).ownerId()).isEqualTo(REP_A);
    }

    @Test
    @DisplayName("an admin sees every rep")
    void leaderboardUnscopedForAdmin() {
        assertThat(leaderboardFor(null))
                .extracting(LeaderboardRow::ownerId)
                .contains(REP_A, REP_B);
    }

    // --- conversion ----------------------------------------------------------

    @Test
    @DisplayName("the funnel never widens as it deepens")
    void conversionIsMonotonic() {
        List<ConversionRow> rows = repository.conversion(null);

        for (int i = 1; i < rows.size(); i++) {
            assertThat(rows.get(i).entered())
                    .as("stage %s cannot have more deals than %s before it",
                            rows.get(i).fromStage(), rows.get(i - 1).fromStage())
                    .isLessThanOrEqualTo(rows.get(i - 1).entered());
        }
    }

    @Test
    @DisplayName("funnel counts each deal at the furthest stage it reached")
    void conversionFunnel() {
        List<ConversionRow> rows = repository.conversion(REP_A);

        ConversionRow newToQualified = rows.stream()
                .filter(r -> r.fromStage().equals("new")).findFirst().orElseThrow();
        // All three of rep A's deals reached at least 'qualified'.
        assertThat(newToQualified.entered()).isEqualTo(3);
        assertThat(newToQualified.advanced()).isEqualTo(3);

        ConversionRow proposalToNegotiation = rows.stream()
                .filter(r -> r.fromStage().equals("proposal")).findFirst().orElseThrow();
        // Two reached proposal: the open one, and the won one that passed through it.
        assertThat(proposalToNegotiation.entered()).isEqualTo(2);
        // The won deal jumped straight from proposal to won. "Reached" is ordinal, so
        // it counts at every rung below won -- including the negotiation it skipped.
        // Without that, a skipped stage would push a later rate above 100%.
        assertThat(proposalToNegotiation.advanced()).isEqualTo(1);
    }

    @Test
    @DisplayName("funnel is scoped per rep")
    void conversionIsScoped() {
        long repAEnteredNew = repository.conversion(REP_A).stream()
                .filter(r -> r.fromStage().equals("new")).findFirst().orElseThrow().entered();
        long repBEnteredNew = repository.conversion(REP_B).stream()
                .filter(r -> r.fromStage().equals("new")).findFirst().orElseThrow().entered();

        assertThat(repAEnteredNew).isEqualTo(3);
        assertThat(repBEnteredNew).isEqualTo(1);
    }

    // --- velocity ------------------------------------------------------------

    @Test
    @DisplayName("measures days between consecutive transitions")
    void velocityPerStage() {
        List<VelocityRow> rows = repository.velocity(REP_A);

        VelocityRow qualified = rows.stream()
                .filter(r -> r.stage().equals("qualified")).findFirst().orElseThrow();
        // Deal 1: 35->33 = 2 days. Deal 2: 36->32 = 4. Deal 3: 15->10 = 5.
        assertThat(qualified.sampleSize()).isEqualTo(3);
        assertThat(qualified.avgDays())
                .isCloseTo(11.0 / 3, org.assertj.core.data.Offset.offset(0.2));
        assertThat(qualified.medianDays())
                .isCloseTo(4.0, org.assertj.core.data.Offset.offset(0.2));
    }

    @Test
    @DisplayName("a terminal stage has no outgoing duration and is omitted")
    void velocityExcludesTerminalStages() {
        assertThat(repository.velocity(REP_A))
                .extracting(VelocityRow::stage)
                .doesNotContain("won", "lost");
    }

    // --- forecast ------------------------------------------------------------

    @Test
    @DisplayName("weights open pipeline by stage probability")
    void forecastWeights() {
        ForecastResponse forecast = repository.forecast(REP_A, 24);

        // One open deal: 75000.50 in proposal, weighted at 0.5.
        assertThat(forecast.rawPipeline()).isEqualByComparingTo("75000.50");
        assertThat(forecast.weightedTotal()).isEqualByComparingTo("37500.25");
    }

    @Test
    @DisplayName("closed deals are excluded from the forecast")
    void forecastExcludesClosedDeals() {
        ForecastResponse forecast = repository.forecast(REP_A, 24);

        assertThat(forecast.rawPipeline())
                .as("the won and lost deals must not appear in a forward-looking forecast")
                .isEqualByComparingTo("75000.50");
    }

    @Test
    @DisplayName("open deals with no close date are reported rather than dropped")
    void forecastSurfacesUnscheduledDeals() {
        deal(BASE_DEAL + 5, REP_A, "qualified", "12345.00", null, 5);

        ForecastResponse forecast = repository.forecast(REP_A, 24);

        assertThat(forecast.unscheduledDealCount())
                .as("silently omitting them would make the pipeline look smaller than it is")
                .isEqualTo(1);
        assertThat(forecast.unscheduledValue()).isEqualByComparingTo("12345.00");
    }

    @Test
    @DisplayName("forecast is scoped per rep")
    void forecastIsScoped() {
        assertThat(repository.forecast(REP_B, 24).rawPipeline())
                .isEqualByComparingTo("200000.00");
        assertThat(repository.forecast(REP_A, 24).rawPipeline())
                .isEqualByComparingTo("75000.50");
    }

    @Test
    @DisplayName("the horizon actually bounds the buckets")
    void forecastRespectsHorizon() {
        // Rep B's deal closes in Nov 2026; a one-month horizon must exclude it.
        BigDecimal shortHorizon = repository.forecast(REP_B, 1).rawPipeline();

        assertThat(shortHorizon).isEqualByComparingTo("0.00");
    }
}
