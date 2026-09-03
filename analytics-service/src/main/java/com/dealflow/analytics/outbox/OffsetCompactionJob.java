package com.dealflow.analytics.outbox;

import com.dealflow.analytics.config.AnalyticsProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * Keeps the anti-join bounded by advancing the floor past the contiguous
 * processed prefix and pruning the ledger below it.
 *
 * <p>Purely an optimisation. If this never ran, the consumer would still be
 * correct -- just doing progressively wider index scans.
 */
@Component
public class OffsetCompactionJob {

    private static final Logger log = LoggerFactory.getLogger(OffsetCompactionJob.class);

    private final OutboxRepository outbox;
    private final AnalyticsProperties properties;

    public OffsetCompactionJob(OutboxRepository outbox, AnalyticsProperties properties) {
        this.outbox = outbox;
        this.properties = properties;
    }

    @Scheduled(fixedDelay = 300_000, initialDelay = 60_000)
    public void compact() {
        if (!properties.enabled()) {
            return;
        }
        try {
            int pruned = outbox.compactOffset(properties.consumerName());
            if (pruned > 0) {
                log.info("Compacted ledger: pruned {} processed_event row(s)", pruned);
            }
        } catch (Exception e) {
            log.error("Offset compaction failed; correctness is unaffected", e);
        }
    }
}
