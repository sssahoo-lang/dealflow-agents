import logging

from app.agents.lead_scoring import graph as lead_scoring
from app.db.base import SessionLocal
from app.events.bus import EventBus
from app.events.schemas import DealCreated

logger = logging.getLogger(__name__)


def score_new_deal(event: DealCreated) -> None:
    # Runs in a background task, so it owns its own session rather than borrowing
    # the request-scoped one, which is already closed by now.
    db = SessionLocal()
    try:
        lead_scoring.run(db, event.deal_id)
        logger.info("scored deal %s", event.deal_id)
    finally:
        db.close()


def register_agent_handlers(bus: EventBus) -> None:
    bus.subscribe(DealCreated, score_new_deal)
