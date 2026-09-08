import pytest

from app.events.bus import EventBus
from app.events.schemas import ContactCreated, DealCreated
from app.models.enums import DealStage


@pytest.fixture
def bus():
    return EventBus()


def test_handler_receives_matching_event(bus):
    received = []
    bus.subscribe(DealCreated, received.append)
    event = DealCreated(deal_id=1, company_id=2, owner_id=3)

    bus.publish(event)

    assert received == [event]


def test_handler_ignores_other_event_types(bus):
    received = []
    bus.subscribe(DealCreated, received.append)

    bus.publish(ContactCreated(contact_id=1, owner_id=2))

    assert received == []


def test_failing_handler_does_not_block_siblings(bus):
    received = []

    def explodes(event):
        raise RuntimeError("agent crashed")

    bus.subscribe(DealCreated, explodes)
    bus.subscribe(DealCreated, received.append)

    bus.publish(DealCreated(deal_id=1, company_id=2, owner_id=3))

    assert len(received) == 1


def test_publish_with_no_subscribers_is_a_noop(bus):
    bus.publish(DealCreated(deal_id=1, company_id=2, owner_id=3))


def test_deal_stage_changed_event_carries_both_stages(bus):
    received = []
    from app.events.schemas import DealStageChanged

    bus.subscribe(DealStageChanged, received.append)
    bus.publish(
        DealStageChanged(deal_id=1, from_stage=DealStage.new, to_stage=DealStage.won)
    )

    assert received[0].from_stage is DealStage.new
    assert received[0].to_stage is DealStage.won


# --- wiring: app/events/handlers.py -----------------------------------------


def test_register_agent_handlers_subscribes_lead_scoring():
    from app.events.handlers import register_agent_handlers, score_new_deal

    bus = EventBus()
    register_agent_handlers(bus)

    assert score_new_deal in bus._handlers[DealCreated]


def test_handler_opens_and_closes_its_own_session(monkeypatch):
    """It runs in a background task, so the request session is already closed."""
    from app.events import handlers

    closed = []

    class FakeSession:
        def close(self):
            closed.append(True)

    monkeypatch.setattr(handlers, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(handlers.lead_scoring, "run", lambda db, deal_id: None)

    handlers.score_new_deal(DealCreated(deal_id=1, company_id=1, owner_id=1))

    assert closed == [True]


def test_handler_closes_its_session_even_when_the_agent_raises(monkeypatch):
    """A leaked connection per failed scoring would exhaust the pool."""
    from app.events import handlers

    closed = []

    class FakeSession:
        def close(self):
            closed.append(True)

    def boom(db, deal_id):
        raise RuntimeError("agent exploded")

    monkeypatch.setattr(handlers, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(handlers.lead_scoring, "run", boom)

    # Does NOT re-raise -- see the next test for why. Absence of an
    # exception here is itself the assertion.
    handlers.score_new_deal(DealCreated(deal_id=1, company_id=1, owner_id=1))

    assert closed == [True]


def test_a_scoring_failure_is_logged_rather_than_lost(monkeypatch, caplog):
    """This runs inside FastAPI's BackgroundTasks, with no request left to
    return an error to. Left unhandled, the exception goes to asyncio's
    default handler, not this logger -- invisible from an operator's point
    of view, and the deal simply stays unscored with no trace of why. A real
    provider (unlike the stub) can fail for reasons that have nothing to do
    with this deal -- a bad key, a rate limit -- so a failure has to show up
    in the logs somewhere, or "best-effort" quietly becomes "silently
    broken."""
    from app.events import handlers

    class FakeSession:
        def close(self):
            pass

    def boom(db, deal_id):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(handlers, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(handlers.lead_scoring, "run", boom)

    with caplog.at_level("ERROR"):
        handlers.score_new_deal(DealCreated(deal_id=7, company_id=1, owner_id=1))

    assert any("deal 7" in r.message for r in caplog.records)
    assert any(r.exc_info for r in caplog.records)  # the traceback, not just a line
