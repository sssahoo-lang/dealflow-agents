package com.dealflow.analytics.outbox;

import com.dealflow.analytics.config.AnalyticsProperties;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * Polls the CRM outbox and hands each event to the dispatcher.
 *
 * <p>Deliberately NOT {@code @Transactional}: the batch is fetched read-only and
 * each event is then applied in its own transaction (see
 * {@link OutboxDispatcher#dispatch}).
 *
 * <p>Polling latency (~2s) is fine here. LISTEN/NOTIFY would cut it to
 * milliseconds but only reaches currently-connected listeners, so a polling
 * backstop would still be required -- pure added complexity for a dashboard
 * nobody reads in real time.
 */
@Component
public class OutboxPoller {

    private static final Logger log = LoggerFactory.getLogger(OutboxPoller.class);

    private final OutboxRepository outbox;
    private final OutboxDispatcher dispatcher;
    private final AnalyticsProperties properties;

    public OutboxPoller(
            OutboxRepository outbox, OutboxDispatcher dispatcher, AnalyticsProperties properties) {
        this.outbox = outbox;
        this.dispatcher = dispatcher;
        this.properties = properties;
    }

    /**
     * fixedDelay, not fixedRate: a slow batch must never overlap the next poll and
     * process the same events twice concurrently.
     */
    @Scheduled(fixedDelayString = "${analytics.outbox.poll-interval-ms:2000}")
    public void poll() {
        // The flag gates the background loop, not the bean: tests still need to
        // inject this and drive pollOnce() directly.
        if (!properties.enabled()) {
            return;
        }
        try {
            int handled = pollOnce();
            if (handled > 0) {
                log.info("Processed {} outbox event(s)", handled);
            }
        } catch (Exception e) {
            // The scheduler silently cancels a task whose exception escapes.
            log.error("Poll cycle failed; will retry on the next tick", e);
        }
    }

    /** Visible for tests, which drive it directly rather than waiting on the clock. */
    public int pollOnce() {
        List<EventEnvelope> batch =
                outbox.fetchBatch(properties.consumerName(), properties.batchSize());

        int handled = 0;
        for (EventEnvelope event : batch) {
            try {
                dispatcher.dispatch(event);
                handled++;
            } catch (Exception e) {
                boolean deadLettered = dispatcher.recordFailure(event, e);
                if (!deadLettered) {
                    // Stop the batch. Per-deal ordering matters: applying a
                    // stage_changed before the created that precedes it would
                    // build a phantom projection row. Head-of-line blocking is
                    // the correct trade -- a stuck pipeline is loud, a silently
                    // reordered one is not.
                    break;
                }
                // Dead-lettered events are permanently skipped, so it is safe to
                // keep going rather than block the stream forever on one bad row.
            }
        }
        return handled;
    }
}
