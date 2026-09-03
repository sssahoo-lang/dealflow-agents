package com.dealflow.analytics;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * Pipeline analytics and a deterministic rules engine, fed by the CRM's
 * transactional outbox.
 *
 * <p>This service never talks to the Python API and cannot read the CRM's tables:
 * it connects as the {@code analytics} Postgres role, which is granted SELECT on
 * exactly one table -- {@code public.outbox_events}, a published versioned
 * contract -- and owns the {@code analytics} schema it writes its own projections
 * into.
 */
@SpringBootApplication
@ConfigurationPropertiesScan
@EnableScheduling
public class AnalyticsApplication {

    public static void main(String[] args) {
        SpringApplication.run(AnalyticsApplication.class, args);
    }
}
