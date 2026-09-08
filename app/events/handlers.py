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
    except Exception:
        # Broader than the anthropic.AnthropicError caught at the HTTP routes
        # on purpose: there's no request here to return an error to, so
        # "best-effort" (see README) must not quietly become "best-effort and
        # unobservable." An uncaught exception in a FastAPI BackgroundTask is
        # handed to asyncio's default handler, not this logger -- swallowed
        # from an operator's point of view. logger.exception() is what makes
        # a real provider failure (or anything else) show up in the logs
        # instead of vanishing along with the deal that never got scored.
        logger.exception("lead scoring failed for deal %s", event.deal_id)
    finally:
        db.close()


def register_agent_handlers(bus: EventBus) -> None:
    bus.subscribe(DealCreated, score_new_deal)
