package com.dealflow.analytics.outbox.handler;

import com.dealflow.analytics.outbox.EventEnvelope;
import com.dealflow.analytics.projection.ProjectionRepository;
import java.util.HashMap;
import java.util.Map;
import java.util.Set;
import org.springframework.stereotype.Component;

/**
 * Projects deal events.
 *
 * <p>{@code deal.snapshot} is handled by the same code as {@code deal.created}:
 * a snapshot is current state as of the backfill, so it upserts identically. The
 * {@code last_event_id} guard is what stops a backfill snapshot from overwriting
 * a newer live event, which is why the two can share a path safely.
 */
@Component
public class DealEventHandler implements EventHandler {

    private static final String[] TEXT_FIELDS = {
        "company_id", "company_name", "owner_id", "owner_email", "owner_name",
        "name", "stage", "priority", "expected_close_date", "created_at", "stage_changed_at"
    };

    /**
     * Every payload field this handler reads for a created/snapshot event.
     *
     * <p>Exposed so the contract test can assert it against
     * {@code contracts/events/deal.created.v1.json} -- the same file the Python
     * producer asserts. That stops this service quietly depending on a field the
     * CRM never promised to send, which would break the moment the producer
     * dropped it.
     */
    public static final Set<String> CREATED_PAYLOAD_FIELDS;

    static {
        Set<String> fields = new java.util.HashSet<>(Set.of(TEXT_FIELDS));
        fields.add("value");
        fields.add("score");
        CREATED_PAYLOAD_FIELDS = Set.copyOf(fields);
    }

    private final ProjectionRepository projections;

    public DealEventHandler(ProjectionRepository projections) {
        this.projections = projections;
    }

    @Override
    public Set<String> handles() {
        return Set.of("deal.created", "deal.updated", "deal.stage_changed", "deal.snapshot");
    }

    @Override
    public void handle(EventEnvelope event) {
        Map<String, String> text = new HashMap<>();
        for (String field : TEXT_FIELDS) {
            text.put(field, event.text(field));
        }

        projections.upsertDeal(
                event.id(),
                event.aggregateId(),
                text,
                event.text("value"),
                event.decimal("score"),
                event.occurredAt());

        if ("deal.stage_changed".equals(event.eventType())) {
            projections.insertTransition(
                    event.id(),
                    event.aggregateId(),
                    event.text("from_stage"),
                    event.text("to_stage"),
                    event.occurredAt());
        }
    }
}
