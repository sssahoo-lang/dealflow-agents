package com.dealflow.analytics.observability;

import static org.assertj.core.api.Assertions.assertThat;

import com.dealflow.analytics.outbox.EventEnvelope;
import com.fasterxml.jackson.databind.node.NullNode;
import io.opentelemetry.api.trace.SpanKind;
import io.opentelemetry.sdk.testing.exporter.InMemorySpanExporter;
import io.opentelemetry.sdk.trace.SdkTracerProvider;
import io.opentelemetry.sdk.trace.data.SpanData;
import io.opentelemetry.sdk.trace.export.SimpleSpanProcessor;
import java.time.Instant;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/**
 * Resuming the CRM's trace, and what happens when there is nothing to resume.
 *
 * <p>A real {@link SdkTracerProvider} backed by {@link InMemorySpanExporter},
 * not a mocked {@code Tracer} -- the property under test is whether the
 * *parent-child link OpenTelemetry itself records* matches what the CRM sent,
 * and a mock cannot answer that; only the real propagator can.
 */
class OutboxTracingTest {

    private InMemorySpanExporter exporter;
    private SdkTracerProvider provider;
    private OutboxTracing tracing;

    @BeforeEach
    void setUp() {
        exporter = InMemorySpanExporter.create();
        provider = SdkTracerProvider.builder()
                .addSpanProcessor(SimpleSpanProcessor.create(exporter))
                .build();
        tracing = new OutboxTracing(provider.get("test"));
    }

    @AfterEach
    void tearDown() {
        provider.shutdown();
    }

    private EventEnvelope event(String traceContext) {
        return new EventEnvelope(
                42L, "deal", 7L, "deal.created", 1, NullNode.getInstance(),
                Instant.now(), traceContext);
    }

    @Test
    void resumesTheTraceRecordedByTheCrm() {
        // A traceparent as the CRM's Python side would actually write one:
        // version-traceid-spanid-flags, sampled.
        String traceId = "4bf92f3577b34da6a3ce929d0e0e4736";
        String parentSpanId = "00f067aa0ba902b7";
        String traceContext =
                "{\"traceparent\":\"00-" + traceId + "-" + parentSpanId + "-01\"}";

        tracing.traced(event(traceContext), () -> null);

        SpanData span = onlySpan();
        assertThat(span.getTraceId())
                .as("the child must land in the SAME trace as the CRM's request")
                .isEqualTo(traceId);
        assertThat(span.getParentSpanId()).isEqualTo(parentSpanId);
        assertThat(span.getKind()).isEqualTo(SpanKind.CONSUMER);
    }

    @Test
    void startsAFreshTraceWhenThereIsNoStoredContext() {
        // Tracing was off in the CRM (the default), or this row predates the
        // column. Either way: dispatch normally, under an unlinked trace.
        tracing.traced(event(null), () -> null);

        SpanData span = onlySpan();
        assertThat(span.getParentSpanId()).isEqualTo("0000000000000000");
    }

    @Test
    void startsAFreshTraceRatherThanFailingOnAMalformedContext() {
        // A malformed value here must never become a reason to skip a real
        // business event -- dispatch proceeds, just untraced.
        tracing.traced(event("not valid json"), () -> "still ran");

        SpanData span = onlySpan();
        assertThat(span.getParentSpanId()).isEqualTo("0000000000000000");
    }

    @Test
    void alwaysRunsTheWorkAndReturnsItsResult() {
        Object result = tracing.traced(event(null), () -> "the handler's result");

        assertThat(result).isEqualTo("the handler's result");
    }

    @Test
    void endsTheSpanAndRecordsTheExceptionWhenWorkFails() {
        RuntimeException boom = new RuntimeException("handler blew up");

        try {
            tracing.traced(event(null), () -> {
                throw boom;
            });
        } catch (RuntimeException caught) {
            assertThat(caught).isSameAs(boom);
        }

        SpanData span = onlySpan();
        assertThat(span.hasEnded()).isTrue();
        assertThat(span.getEvents()).anySatisfy(e -> assertThat(e.getName()).isEqualTo("exception"));
    }

    @Test
    void namesTheSpanAndTagsItWithTheEventIdentity() {
        tracing.traced(event(null), () -> null);

        SpanData span = onlySpan();
        assertThat(span.getName()).isEqualTo("outbox.dispatch deal.created");
        assertThat(span.getAttributes().get(io.opentelemetry.api.common.AttributeKey.longKey(
                "dealflow.outbox.event_id"))).isEqualTo(42L);
        assertThat(span.getAttributes().get(io.opentelemetry.api.common.AttributeKey.stringKey(
                "dealflow.outbox.aggregate_type"))).isEqualTo("deal");
    }

    private SpanData onlySpan() {
        var spans = exporter.getFinishedSpanItems();
        assertThat(spans).hasSize(1);
        return spans.get(0);
    }
}
