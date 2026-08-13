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
