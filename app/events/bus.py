import logging
from collections import defaultdict
from typing import Callable, TypeVar

from app.events.schemas import DomainEvent

logger = logging.getLogger(__name__)

E = TypeVar("E", bound=DomainEvent)


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[type, list[Callable]] = defaultdict(list)

    def subscribe(self, event_type: type[E], handler: Callable[[E], None]) -> None:
        self._handlers[event_type].append(handler)

    def publish(self, event: DomainEvent) -> None:
        for handler in self._handlers.get(type(event), []):
            # A failing handler must never break its siblings or the request that
            # triggered it. Starlette silently swallows BackgroundTasks exceptions,
            # so this logging is the only visibility into agent failures.
            try:
                handler(event)
            except Exception:
                logger.exception(
                    "event handler %s failed for %s", handler.__name__, event
                )


event_bus = EventBus()
