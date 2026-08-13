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
