package com.dealflow.analytics.rules;

import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * Hourly sweep.
 *
 * <p><b>Scheduled, not event-driven -- and that is the whole point.</b> A rule
 * about the ABSENCE of activity has no triggering event: nothing happens when a
 * deal goes quiet, which is precisely the condition worth alerting on. This is
 * the structural difference between the deterministic rules engine and the LLM
 * agents on the other side of the outbox, which react to events as they arrive.
 */
@Component
public class RuleScheduler {

    private static final Logger log = LoggerFactory.getLogger(RuleScheduler.class);

    private final RuleEngine engine;
    private final boolean enabled;

    public RuleScheduler(
            RuleEngine engine, @Value("${analytics.rules.enabled:true}") boolean enabled) {
        this.engine = engine;
        this.enabled = enabled;
    }

    @Scheduled(cron = "${analytics.rules.cron:0 5 * * * *}")
    public void sweep() {
        if (!enabled) {
            return;
        }
        try {
            List<RuleEngine.RunSummary> summaries = engine.runAll();
            for (RuleEngine.RunSummary summary : summaries) {
                if (summary.opened() > 0 || summary.resolved() > 0) {
                    log.info(
                            "Rule '{}': evaluated {}, opened {}, resolved {}",
                            summary.ruleCode(), summary.evaluated(),
                            summary.opened(), summary.resolved());
                }
            }
        } catch (Exception e) {
            // An escaping exception would silently cancel the scheduled task.
            log.error("Rule sweep failed; will retry on the next tick", e);
        }
    }
}
