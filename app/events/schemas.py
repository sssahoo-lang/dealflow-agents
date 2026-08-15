from dataclasses import dataclass

from app.models.enums import DealStage


@dataclass(frozen=True)
class DomainEvent:
    pass


@dataclass(frozen=True)
class DealCreated(DomainEvent):
    deal_id: int
    company_id: int
    owner_id: int


@dataclass(frozen=True)
class DealStageChanged(DomainEvent):
    deal_id: int
    from_stage: DealStage
    to_stage: DealStage


@dataclass(frozen=True)
class ContactCreated(DomainEvent):
    contact_id: int
    owner_id: int


@dataclass(frozen=True)
class ActivityCreated(DomainEvent):
    """Emitted to the outbox only -- nothing subscribes to it in-process.

    The future rules engine needs activity facts to answer "no touchpoint in 14
    days", which is why it is recorded now rather than when that engine is built.

    Deliberately covers human activity only. The agents write their reasoning
    notes and drafts straight to the activities table inside their graphs, so
    those never reach this event -- and they should not: an agent scoring a deal
    is not contact with the customer, and counting it would make a stale deal
    look freshly touched. If agent output ever does need to be observable
    downstream, give it its own event type rather than widening this one.
    """

    activity_id: int
    deal_id: int | None
    contact_id: int | None
