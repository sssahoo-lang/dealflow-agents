package com.dealflow.analytics.outbox;

import static org.assertj.core.api.Assertions.assertThat;

import com.dealflow.analytics.config.AnalyticsProperties;
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
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.test.context.ActiveProfiles;

/**
 * End-to-end consumer behaviour against the real schema.
 *
 * <p>Fixtures are inserted through a second connection as the {@code crm} role,
 * because the service's own role is SELECT-only on the outbox -- so the test
 * setup mirrors production rather than working around the grant.
 *
 * <p>Test events use ids in a reserved high range so they can be cleaned up
 * without touching real data.
 */
@SpringBootTest
@ActiveProfiles("test")
@DisplayName("Outbox consumer")
class OutboxConsumerIT {

    private static final long TEST_DEAL_ID = 900_001L;
    private static final long TEST_DEAL_ID_2 = 900_002L;

    @Autowired private OutboxPoller poller;
    @Autowired private OutboxRepository outbox;
    @Autowired private AnalyticsProperties properties;
    @Autowired private DataSource analyticsDataSource;

    /** Writes as the CRM would. */
    private JdbcTemplate crm;
    /** Reads/cleans the analytics schema as its owner. */
    private JdbcTemplate analytics;

    @BeforeEach
    void setUp() {
        DriverManagerDataSource crmSource = new DriverManagerDataSource();
        crmSource.setUrl(System.getenv().getOrDefault(
                "SPRING_DATASOURCE_URL", "jdbc:postgresql://db:5432/crm"));
        crmSource.setUsername("crm");
        crmSource.setPassword("crm");
        crm = new JdbcTemplate(crmSource);
        analytics = new JdbcTemplate(analyticsDataSource);

        cleanUp();
    }

    /** Clean up after as well as before, so a run leaves no residue behind in a
     *  shared dev database (a dead-lettered fixture would otherwise linger in
     *  /admin/outbox/status forever). */
    @AfterEach
    void tearDown() {
        cleanUp();
    }

    private void cleanUp() {
        crm.update("DELETE FROM public.outbox_events WHERE aggregate_id >= 900000");
        analytics.update("DELETE FROM analytics.deal_stage_transition WHERE deal_id >= 900000");
        analytics.update("DELETE FROM analytics.activity_fact WHERE activity_id >= 900000");
        analytics.update("DELETE FROM analytics.deal_projection WHERE deal_id >= 900000");
        // Ledger rows for events that no longer exist would otherwise mask reruns.
        analytics.update("""
                DELETE FROM analytics.processed_event
                 WHERE event_id NOT IN (SELECT id FROM public.outbox_events)
                """);
        analytics.update("""
                DELETE FROM analytics.failed_event
                 WHERE event_id NOT IN (SELECT id FROM public.outbox_events)
                """);
    }

    /** @return the generated outbox event id */
    private long seedDealEvent(String eventType, long dealId, String stage, String value) {
        return crm.queryForObject(
                """
                INSERT INTO public.outbox_events
                    (aggregate_type, aggregate_id, event_type, event_version, payload)
                VALUES ('deal', ?, ?, 1, ?::jsonb)
                RETURNING id
                """,
                Long.class,
                dealId,
                eventType,
                """
                {"deal_id": %d, "name": "Test deal", "stage": "%s", "value": "%s",
                 "priority": null, "score": null, "expected_close_date": null,
                 "company_id": 1, "company_name": "Acme", "company_industry": "Manufacturing",
                 "owner_id": 2, "owner_email": "rep@demo.com", "owner_name": "Rep",
                 "primary_contact_id": null, "primary_contact_name": null,
                 "created_at": "2026-08-01T10:00:00+00:00",
                 "stage_changed_at": "2026-08-01T10:00:00+00:00"}
                """.formatted(dealId, stage, value));
    }

    private Map<String, Object> projection(long dealId) {
        List<Map<String, Object>> rows = analytics.queryForList(
                "SELECT * FROM analytics.deal_projection WHERE deal_id = ?", dealId);
        return rows.isEmpty() ? null : rows.get(0);
    }

    @Test
    @DisplayName("projects a created deal")
    void projectsACreatedDeal() {
        seedDealEvent("deal.created", TEST_DEAL_ID, "qualified", "50000.00");

        poller.pollOnce();

        Map<String, Object> row = projection(TEST_DEAL_ID);
        assertThat(row).isNotNull();
        assertThat(row.get("stage")).isEqualTo("qualified");
        assertThat(row.get("owner_email")).isEqualTo("rep@demo.com");
        assertThat(row.get("company_name")).isEqualTo("Acme");
    }

    @Test
    @DisplayName("money survives the wire as an exact decimal")
    void moneyIsExact() {
        seedDealEvent("deal.created", TEST_DEAL_ID, "new", "75000.10");

        poller.pollOnce();

        assertThat(projection(TEST_DEAL_ID).get("value").toString()).isEqualTo("75000.10");
    }

    @Test
    @DisplayName("reprocessing the same events changes nothing")
    void isIdempotent() {
        seedDealEvent("deal.created", TEST_DEAL_ID, "qualified", "50000.00");
        long changed = seedDealEvent("deal.stage_changed", TEST_DEAL_ID, "proposal", "50000.00");
        crm.update("UPDATE public.outbox_events SET payload = payload || "
                + "'{\"from_stage\":\"qualified\",\"to_stage\":\"proposal\"}'::jsonb WHERE id = ?", changed);

        poller.pollOnce();
        Object firstValue = projection(TEST_DEAL_ID).get("value");
        int transitionsAfterFirst = countTransitions();

        // Force a full replay: clear the ledger so every event looks unprocessed.
        analytics.update("DELETE FROM analytics.processed_event");
        analytics.update("UPDATE analytics.consumer_offset SET floor_event_id = 0");
        poller.pollOnce();

        assertThat(projection(TEST_DEAL_ID).get("value")).isEqualTo(firstValue);
        assertThat(countTransitions())
                .as("a replayed stage change must not create a second transition")
                .isEqualTo(transitionsAfterFirst);
    }

    private int countTransitions() {
        return analytics.queryForObject(
                "SELECT count(*) FROM analytics.deal_stage_transition WHERE deal_id = ?",
                Integer.class,
                TEST_DEAL_ID);
    }

    @Test
    @DisplayName("an older event arriving late cannot clobber newer state")
    void guardsAgainstOutOfOrderArrival() {
        long older = seedDealEvent("deal.created", TEST_DEAL_ID, "new", "1000.00");
        seedDealEvent("deal.updated", TEST_DEAL_ID, "negotiation", "99000.00");

        poller.pollOnce();
        assertThat(projection(TEST_DEAL_ID).get("stage")).isEqualTo("negotiation");

        // Replay only the older event.
        analytics.update("DELETE FROM analytics.processed_event WHERE event_id = ?", older);
        analytics.update("UPDATE analytics.consumer_offset SET floor_event_id = 0");
        poller.pollOnce();

        assertThat(projection(TEST_DEAL_ID).get("stage"))
                .as("last_event_id guard should reject the stale event")
                .isEqualTo("negotiation");
    }

    @Test
    @DisplayName("an unknown event type is skipped, not dead-lettered")
    void toleratesUnknownEventTypes() {
        long id = crm.queryForObject(
                """
                INSERT INTO public.outbox_events
                    (aggregate_type, aggregate_id, event_type, event_version, payload)
                VALUES ('widget', 900003, 'widget.invented_later', 1, '{}'::jsonb)
                RETURNING id
                """,
                Long.class);

        poller.pollOnce();

        String status = analytics.queryForObject(
                "SELECT status FROM analytics.processed_event WHERE event_id = ?", String.class, id);
        assertThat(status)
                .as("the CRM must be able to add an event type without bricking this consumer")
                .isEqualTo("done");
    }

    @Test
    @DisplayName("a malformed payload is retried, then dead-lettered")
    void deadLettersAPoisonEvent() {
        // owner_id is required by the projection; omitting it makes the handler throw.
        long poison = crm.queryForObject(
                """
                INSERT INTO public.outbox_events
                    (aggregate_type, aggregate_id, event_type, event_version, payload)
                VALUES ('deal', 900004, 'deal.created', 1, '{"owner_id": "not-a-number"}'::jsonb)
                RETURNING id
                """,
                Long.class);

        for (int i = 0; i < properties.maxAttempts() + 1; i++) {
            // Clear backoff so the retries don't have to wait out the delay.
            analytics.update("UPDATE analytics.failed_event SET next_attempt_at = now()");
            poller.pollOnce();
        }

        Map<String, Object> ledger = analytics.queryForMap(
                "SELECT status, attempts FROM analytics.processed_event WHERE event_id = ?", poison);
        assertThat(ledger.get("status")).isEqualTo("dead");
        assertThat((Integer) ledger.get("attempts")).isGreaterThanOrEqualTo(properties.maxAttempts());
    }

    @Test
    @DisplayName("a dead-lettered event does not block the ones behind it")
    void deadLetterDoesNotBlockTheStream() {
        crm.update("""
                INSERT INTO public.outbox_events
                    (aggregate_type, aggregate_id, event_type, event_version, payload)
                VALUES ('deal', 900004, 'deal.created', 1, '{"owner_id": "not-a-number"}'::jsonb)
                """);
        seedDealEvent("deal.created", TEST_DEAL_ID_2, "new", "500.00");

        for (int i = 0; i < properties.maxAttempts() + 2; i++) {
            analytics.update("UPDATE analytics.failed_event SET next_attempt_at = now()");
            poller.pollOnce();
        }

        assertThat(projection(TEST_DEAL_ID_2))
                .as("the healthy event behind the poison one must eventually land")
                .isNotNull();
    }

    @Test
    @DisplayName("status stays accurate after the ledger is compacted")
    void statusIsFloorAware() {
        // Regression: compaction prunes processed_event rows below the floor, so a
        // status query that only looks for a missing ledger row reports every
        // compacted event as pending and shows climbing lag on a caught-up
        // consumer.
        seedDealEvent("deal.created", TEST_DEAL_ID, "new", "10.00");
        poller.pollOnce();

        outbox.compactOffset(properties.consumerName());
        Map<String, Object> status = outbox.status(properties.consumerName());

        assertThat(((Number) status.get("floor_event_id")).longValue()).isGreaterThan(0);
        assertThat(((Number) status.get("pending_count")).intValue())
                .as("a fully caught-up consumer has nothing pending, compacted or not")
                .isZero();
        assertThat(((Number) status.get("lag_seconds")).doubleValue())
                .as("no pending work means no lag")
                .isZero();
    }

    @Test
    @DisplayName("status reports pending work and dead letters")
    void reportsStatus() {
        seedDealEvent("deal.created", TEST_DEAL_ID, "new", "10.00");

        Map<String, Object> before = outbox.status(properties.consumerName());
        assertThat(((Number) before.get("pending_count")).intValue()).isGreaterThan(0);

        poller.pollOnce();

        Map<String, Object> after = outbox.status(properties.consumerName());
        assertThat(((Number) after.get("pending_count")).intValue())
                .isLessThan(((Number) before.get("pending_count")).intValue());
    }
}
