package com.dealflow.analytics.observability;

import io.opentelemetry.api.OpenTelemetry;
import io.opentelemetry.api.trace.Tracer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * The one {@link Tracer} this service signs spans with.
 *
 * <p>The Spring Boot OpenTelemetry starter auto-configures the {@link
 * OpenTelemetry} facade itself (wired from the {@code otel.*} properties in
 * application.yml, including the {@code otel.sdk.disabled} master switch), but
 * leaves obtaining a named {@code Tracer} to the application. When tracing is
 * disabled that facade is the no-op implementation, so {@link OutboxTracing}
 * needs no separate disabled-check of its own -- every span it starts is simply
 * discarded rather than exported.
 */
@Configuration
public class TracingConfig {

    @Bean
    public Tracer tracer(OpenTelemetry openTelemetry) {
        return openTelemetry.getTracer("dealflow-analytics");
    }
}
