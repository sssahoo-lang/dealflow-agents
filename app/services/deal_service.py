from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rbac import assert_can_access, assert_can_set_stage
from app.events.schemas import DealCreated, DealStageChanged
from app.models.deal import Deal
from app.models.enums import RoleEnum
from app.models.user import User
from app.schemas.crm import DealCreate, DealUpdate
from app.services.errors import NotFound


def create_deal(db: Session, user: User, payload: DealCreate) -> tuple[Deal, DealCreated]:
    assert_can_set_stage(user, payload.stage)
    deal = Deal(**payload.model_dump(), owner_id=user.id)
    db.add(deal)
    db.commit()
    db.refresh(deal)
    return deal, DealCreated(
        deal_id=deal.id, company_id=deal.company_id, owner_id=deal.owner_id
    )


def list_deals(db: Session, user: User) -> list[Deal]:
    stmt = select(Deal)
    if user.role is not RoleEnum.admin:
        stmt = stmt.where(Deal.owner_id == user.id)
    return list(db.scalars(stmt.order_by(Deal.created_at.desc())))


def get_deal(db: Session, user: User, deal_id: int) -> Deal:
    deal = db.get(Deal, deal_id)
    if deal is None:
        raise NotFound("Deal not found")
    assert_can_access(user, deal.owner_id)
    return deal


def update_deal(
    db: Session, user: User, deal_id: int, payload: DealUpdate
) -> tuple[Deal, DealStageChanged | None]:
    deal = get_deal(db, user, deal_id)
    changes = payload.model_dump(exclude_unset=True)

    event = None
    new_stage = changes.get("stage")
    if new_stage is not None and new_stage != deal.stage:
        assert_can_set_stage(user, new_stage)
        event = DealStageChanged(
            deal_id=deal.id, from_stage=deal.stage, to_stage=new_stage
        )

    for field, value in changes.items():
        setattr(deal, field, value)
    if event is not None:
        from sqlalchemy import func

        deal.stage_changed_at = func.now()

    db.commit()
    db.refresh(deal)
    return deal, event
