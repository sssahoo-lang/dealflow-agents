package com.dealflow.analytics.outbox;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.Instant;

/**
 * One row of public.outbox_events, as published by the Python API.
 *
 * <p>The payload stays a JsonNode rather than being bound to a typed class: this
 * service must tolerate the producer adding fields it doesn't know about, and a
 * strict binding would turn a forwards-compatible change into a dead-lettered
 * event.
 */
public record EventEnvelope(
        long id,
        String aggregateType,
        long aggregateId,
        String eventType,
        int eventVersion,
        JsonNode payload,
        Instant occurredAt) {

    /** Null-safe string read; the producer may legitimately omit optional fields. */
    public String text(String field) {
        JsonNode node = payload.get(field);
        return node == null || node.isNull() ? null : node.asText();
    }

    public Long number(String field) {
        JsonNode node = payload.get(field);
        return node == null || node.isNull() ? null : node.asLong();
    }

    public Double decimal(String field) {
        JsonNode node = payload.get(field);
        return node == null || node.isNull() ? null : node.asDouble();
    }
}
