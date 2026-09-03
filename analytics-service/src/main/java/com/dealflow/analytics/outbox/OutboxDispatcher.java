package com.dealflow.analytics.outbox;

import com.dealflow.analytics.config.AnalyticsProperties;
import com.dealflow.analytics.outbox.handler.EventHandler;
import com.dealflow.analytics.outbox.handler.EventHandlerRegistry;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

/** Applies one event, and owns what happens when that fails. */
@Component
public class OutboxDispatcher {

    private static final Logger log = LoggerFactory.getLogger(OutboxDispatcher.class);

    private final EventHandlerRegistry registry;
    private final OutboxRepository outbox;
    private final AnalyticsProperties properties;

    public OutboxDispatcher(
            EventHandlerRegistry registry,
            OutboxRepository outbox,
            AnalyticsProperties properties) {
        this.registry = registry;
        this.outbox = outbox;
        this.properties = properties;
    }

    /**
     * One transaction per event: the projection write and the ledger insert commit
     * together, so a crash mid-batch simply leaves the event unprocessed rather
     * than half-applied. Batching would be faster but would conflate unrelated
     * aggregates on failure -- at this volume, per-event is the right trade.
     */
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void dispatch(EventEnvelope event) {
        Optional<EventHandler> handler = registry.forType(event.eventType());

        if (handler.isEmpty()) {
            // Forward compatibility: the CRM must be able to publish a new event
            // type without bricking this consumer. Not an error -- but loud
            // enough to notice if it was supposed to be handled.
            log.warn(
                    "No handler for event type '{}' (event {}); marking done and skipping",
                    event.eventType(),
                    event.id());
            outbox.markDone(event.id());
            return;
        }

        handler.get().handle(event);
        outbox.markDone(event.id());
    }

    /**
     * Runs in its own transaction so it survives the rollback of the event that
     * failed -- otherwise the failure record would be rolled back too and the
     * event would retry forever with attempts stuck at zero.
     *
     * @return true if the event was dead-lettered and the poller may continue
     */
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public boolean recordFailure(EventEnvelope event, Exception failure) {
        String message = failure.getClass().getSimpleName() + ": " + failure.getMessage();
        int attempts = outbox.recordFailure(event.id(), message);

        if (attempts >= properties.maxAttempts()) {
            log.error(
                    "Event {} ({}) failed {} times; dead-lettering. Last error: {}",
                    event.id(),
                    event.eventType(),
                    attempts,
                    message);
            outbox.markDead(event.id(), attempts, message);
            return true;
        }

        log.warn(
                "Event {} ({}) failed (attempt {}/{}): {}",
                event.id(),
                event.eventType(),
                attempts,
                properties.maxAttempts(),
                message);
        return false;
    }
}
