package com.dealflow.analytics.outbox.handler;

import com.dealflow.analytics.outbox.EventEnvelope;
import java.util.Set;

/** Applies one family of outbox events to the read model. */
public interface EventHandler {

    /** Event types this handler claims, e.g. {@code deal.created}. */
    Set<String> handles();

    void handle(EventEnvelope event);
}
