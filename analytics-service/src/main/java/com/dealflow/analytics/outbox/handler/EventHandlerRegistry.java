package com.dealflow.analytics.outbox.handler;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.springframework.stereotype.Component;

/** Maps event type to handler, built from every EventHandler bean at startup. */
@Component
public class EventHandlerRegistry {

    private final Map<String, EventHandler> byType = new HashMap<>();

    public EventHandlerRegistry(List<EventHandler> handlers) {
        for (EventHandler handler : handlers) {
            for (String type : handler.handles()) {
                EventHandler previous = byType.put(type, handler);
                if (previous != null) {
                    // Two handlers claiming one type means one silently wins and
                    // the other's projection never happens. Fail at startup.
                    throw new IllegalStateException(
                            "Duplicate handler for event type '" + type + "': "
                                    + previous.getClass().getSimpleName() + " and "
                                    + handler.getClass().getSimpleName());
                }
            }
        }
    }

    public Optional<EventHandler> forType(String eventType) {
        return Optional.ofNullable(byType.get(eventType));
    }
}
