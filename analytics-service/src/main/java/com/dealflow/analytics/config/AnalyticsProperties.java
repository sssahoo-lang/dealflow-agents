package com.dealflow.analytics.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * @param consumerName    key in analytics.consumer_offset; a second consumer would
 *                        be a new row, not a schema change
 * @param pollIntervalMs  fixed *delay* between polls, so a slow batch never overlaps itself
 * @param batchSize       events fetched per poll; each is then processed in its own transaction
 * @param maxAttempts     failures before an event is dead-lettered and skipped
 * @param enabled         lets tests construct the context without a background poller running
 */
@ConfigurationProperties(prefix = "analytics.outbox")
public record AnalyticsProperties(
        String consumerName, long pollIntervalMs, int batchSize, int maxAttempts, boolean enabled) {

    public AnalyticsProperties {
        if (consumerName == null || consumerName.isBlank()) {
            consumerName = "analytics";
        }
        if (pollIntervalMs <= 0) {
            pollIntervalMs = 2000;
        }
        if (batchSize <= 0) {
            batchSize = 200;
        }
        if (maxAttempts <= 0) {
            maxAttempts = 5;
        }
    }
}
