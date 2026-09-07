package com.dealflow.analytics.observability;

import com.dealflow.analytics.outbox.EventEnvelope;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanKind;
import io.opentelemetry.api.trace.Tracer;
import io.opentelemetry.context.Context;
import io.opentelemetry.context.propagation.TextMapGetter;
import io.opentelemetry.api.trace.propagation.W3CTraceContextPropagator;
import java.util.Map;
import java.util.function.Supplier;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/**
 * Resumes the CRM's trace for one outbox event, rather than starting a new one.
 *
 * <p>This is the piece that makes the cross-service trace a single trace and not
 * two unrelated ones that happen to share a deal id. The CRM writes a
 * {@code traceparent} onto the row at the moment it becomes durable
 * (app/observability/tracing.py); this class reads it back -- possibly one poll
 * interval later, on an unrelated thread, in an unrelated process -- and starts
 * this service's span as a CHILD of that original request span. A trace viewer
 * then renders one continuous trace from {@code POST /deals} down into the
 * projection write, with the real wall-clock gap in the middle shown as exactly
 * what it is.
 *
 * <p>Absent context (tracing was off, or the row predates the column) is not an
 * error: the event is still dispatched, just under its own untraced span,
 * because a missing trace must never become a reason to skip real work.
 */
@Component
public class OutboxTracing {

    private static final Logger log = LoggerFactory.getLogger(OutboxTracing.class);

    private static final TextMapGetter<Map<String, String>> GETTER =
            new TextMapGetter<>() {
                @Override
                public Iterable<String> keys(Map<String, String> carrier) {
                    return carrier.keySet();
                }

                @Override
                public String get(Map<String, String> carrier, String key) {
                    return carrier == null ? null : carrier.get(key);
                }
            };

    private final Tracer tracer;
    private final ObjectMapper mapper = new ObjectMapper();

    public OutboxTracing(Tracer tracer) {
        this.tracer = tracer;
    }

    /**
     * Runs {@code work} inside a CONSUMER span resumed from {@code event}'s
     * stored trace context, named and tagged so it reads clearly beside the
     * producing request in a trace viewer.
     */
    public <T> T traced(EventEnvelope event, Supplier<T> work) {
        Context parent = extract(event.traceContext());

        Span span =
                tracer.spanBuilder("outbox.dispatch " + event.eventType())
                        .setParent(parent)
                        .setSpanKind(SpanKind.CONSUMER)
                        .setAttribute("dealflow.outbox.event_id", event.id())
                        .setAttribute("dealflow.outbox.event_type", event.eventType())
                        .setAttribute("dealflow.outbox.aggregate_type", event.aggregateType())
                        .setAttribute("dealflow.outbox.aggregate_id", event.aggregateId())
                        .startSpan();

        try (var ignored = span.makeCurrent()) {
            return work.get();
        } catch (RuntimeException e) {
            span.recordException(e);
            throw e;
        } finally {
            span.end();
        }
    }

    /** {@link Context#root()} (a fresh, unlinked trace) when there is nothing to resume. */
    private Context extract(String traceContextJson) {
        if (traceContextJson == null || traceContextJson.isBlank()) {
            return Context.root();
        }
        try {
            @SuppressWarnings("unchecked")
            Map<String, String> carrier = mapper.readValue(traceContextJson, Map.class);
            return W3CTraceContextPropagator.getInstance()
                    .extract(Context.root(), carrier, GETTER);
        } catch (Exception e) {
            // A malformed value here must never block processing of the event it
            // rode in on -- dispatch it untraced rather than dead-lettering a
            // perfectly good business event over an observability field.
            log.debug("Could not parse trace_context, dispatching untraced: {}", e.toString());
            return Context.root();
        }
    }
}
