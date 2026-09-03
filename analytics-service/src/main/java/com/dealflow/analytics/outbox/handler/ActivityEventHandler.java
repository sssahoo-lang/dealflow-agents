package com.dealflow.analytics.outbox.handler;

import com.dealflow.analytics.outbox.EventEnvelope;
import com.dealflow.analytics.projection.ProjectionRepository;
import java.util.Set;
import org.springframework.stereotype.Component;

/**
 * Projects activity events into immutable facts.
 *
 * <p>These are the facts the rules engine needs to answer "no touchpoint in N
 * days". Note that agent-written activities never reach this handler: the CRM
 * deliberately keeps them out of the event stream, because an agent scoring a
 * deal is not contact with the customer and counting it would make a stale deal
 * look freshly touched.
 */
@Component
public class ActivityEventHandler implements EventHandler {

    private final ProjectionRepository projections;

    public ActivityEventHandler(ProjectionRepository projections) {
        this.projections = projections;
    }

    @Override
    public Set<String> handles() {
        return Set.of("activity.created", "activity.snapshot");
    }

    @Override
    public void handle(EventEnvelope event) {
        projections.insertActivityFact(
                event.id(),
                event.aggregateId(),
                event.number("deal_id"),
                event.text("type") == null ? "unknown" : event.text("type"),
                event.occurredAt());
    }
}
