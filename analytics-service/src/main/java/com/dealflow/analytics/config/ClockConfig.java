package com.dealflow.analytics.config;

import java.time.Clock;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * The clock is injected rather than read from {@code Instant.now()} so that
 * time-dependent rules ("no activity for 14 days") can be tested at their exact
 * boundary with {@code Clock.fixed}.
 *
 * <p>UTC explicitly: this container, the API container and Postgres are all
 * pinned to UTC, and the Docker VM clock has been observed drifting from the host
 * by over a minute -- so nothing here should depend on a local zone.
 */
@Configuration
public class ClockConfig {

    @Bean
    public Clock clock() {
        return Clock.systemUTC();
    }
}
