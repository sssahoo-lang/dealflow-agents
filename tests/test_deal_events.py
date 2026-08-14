"""Event semantics of the deal service.

These pin the contract the Milestone 2 outbox depends on: an event is emitted on
a real stage transition and on nothing else. If a non-stage update started
emitting events, the outbox would record phantom transitions and the analytics
read model would silently drift.
"""

import pytest

from app.events.schemas import DealCreated, DealStageChanged
from app.models.enums import DealStage
from app.schemas.crm import DealCreate, DealUpdate
from app.services import deal_service


@pytest.fixture
def deal(db, crm_data):
    return crm_data["deal"]


def test_create_emits_deal_created(db, crm_data, users):
    payload = DealCreate(name="New one", company_id=crm_data["company"].id, value=1000)

    created, event = deal_service.create_deal(db, users["rep"], payload)

    assert isinstance(event, DealCreated)
    assert event.deal_id == created.id
    assert event.owner_id == users["rep"].id
    assert event.company_id == crm_data["company"].id


def test_stage_change_emits_the_transition(db, deal, users):
    before = deal.stage

    _, event = deal_service.update_deal(
        db, users["admin"], deal.id, DealUpdate(stage=DealStage.negotiation)
    )

    assert isinstance(event, DealStageChanged)
    assert event.from_stage is before
    assert event.to_stage is DealStage.negotiation


def test_non_stage_update_emits_nothing(db, deal, users):
    """Renaming or repricing a deal is not a pipeline transition."""
    _, event = deal_service.update_deal(
        db, users["rep"], deal.id, DealUpdate(name="Renamed", value=999)
    )

    assert event is None


def test_setting_the_stage_to_its_current_value_emits_nothing(db, deal, users):
    """A no-op write must not look like a transition to a downstream consumer."""
    _, event = deal_service.update_deal(
        db, users["rep"], deal.id, DealUpdate(stage=deal.stage)
    )

    assert event is None


def test_stage_changed_at_moves_only_on_a_real_transition(db, deal, users):
    original = deal.stage_changed_at

    deal_service.update_deal(db, users["rep"], deal.id, DealUpdate(name="Renamed"))
    db.refresh(deal)
    assert deal.stage_changed_at == original

    deal_service.update_deal(
        db, users["admin"], deal.id, DealUpdate(stage=DealStage.won)
    )
    db.refresh(deal)
    assert deal.stage_changed_at > original


def test_a_forbidden_transition_emits_nothing_and_does_not_persist(db, deal, users):
    """The RBAC check must fire before any mutation or event is produced."""
    before = deal.stage

    with pytest.raises(Exception):
        deal_service.update_deal(
            db, users["rep"], deal.id, DealUpdate(stage=DealStage.won)
        )

    db.rollback()
    db.refresh(deal)
    assert deal.stage is before
