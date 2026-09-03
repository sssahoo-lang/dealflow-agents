package com.dealflow.analytics.outbox.handler;

import com.dealflow.analytics.outbox.EventEnvelope;
import java.util.Set;
import org.springframework.stereotype.Component;

/**
 * Events this service knowingly does not need.
 *
 * <p>Distinct from an *unknown* event type, which is logged at WARN. Contacts
 * carry no analytics value today, but claiming them explicitly keeps that a
 * decision rather than something silently lumped in with genuine surprises.
 */
@Component
public class IgnoredEventHandler implements EventHandler {

    @Override
    public Set<String> handles() {
        return Set.of("contact.created", "contact.snapshot");
    }

    @Override
    public void handle(EventEnvelope event) {
        // Intentionally empty; the dispatcher still marks it done.
    }
}
