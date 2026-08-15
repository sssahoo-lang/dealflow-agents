from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rbac import assert_can_access
from app.events import outbox
from app.events.schemas import ActivityCreated, ContactCreated
from app.models.activity import Activity
from app.models.company import Company
from app.models.contact import Contact
from app.models.deal import Deal
from app.models.enums import RoleEnum
from app.models.user import User
from app.schemas.crm import ActivityCreate, CompanyCreate, ContactCreate
from app.services.errors import NotFound


def create_company(db: Session, user: User, payload: CompanyCreate) -> Company:
    company = Company(**payload.model_dump(), owner_id=user.id)
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def list_companies(db: Session) -> list[Company]:
    return list(db.scalars(select(Company).order_by(Company.name)))


def create_contact(
    db: Session, user: User, payload: ContactCreate
) -> tuple[Contact, ContactCreated]:
    contact = Contact(**payload.model_dump(), owner_id=user.id)
    db.add(contact)
    db.flush()
    event = ContactCreated(contact_id=contact.id, owner_id=contact.owner_id)
    outbox.record(db, event)
    db.commit()
    db.refresh(contact)
    return contact, event


def list_contacts(db: Session, user: User) -> list[Contact]:
    stmt = select(Contact)
    if user.role is not RoleEnum.admin:
        stmt = stmt.where(Contact.owner_id == user.id)
    return list(db.scalars(stmt.order_by(Contact.last_name)))


def create_activity(db: Session, user: User, payload: ActivityCreate) -> Activity:
    if payload.deal_id is not None:
        deal = db.get(Deal, payload.deal_id)
        if deal is None:
            raise NotFound("Deal not found")
        assert_can_access(user, deal.owner_id)

    activity = Activity(**payload.model_dump(), created_by_user_id=user.id)
    db.add(activity)
    db.flush()
    # Recorded to the outbox but not published on the in-process bus: nothing
    # subscribes in-process, and the future rules engine needs activity facts to
    # answer "no touchpoint in 14 days". Keeping it out of the return signature
    # means no route or test has to change.
    outbox.record(
        db,
        ActivityCreated(
            activity_id=activity.id,
            deal_id=activity.deal_id,
            contact_id=activity.contact_id,
        ),
    )
    db.commit()
    db.refresh(activity)
    return activity


def list_activities(
    db: Session,
    user: User,
    deal_id: int | None = None,
    is_draft: bool | None = None,
) -> list[Activity]:
    stmt = select(Activity)
    if deal_id is not None:
        stmt = stmt.where(Activity.deal_id == deal_id)
    if is_draft is not None:
        stmt = stmt.where(Activity.is_draft == is_draft)
    if user.role is not RoleEnum.admin:
        # Reps only see activities on deals they own (plus their own dealless notes).
        owned = select(Deal.id).where(Deal.owner_id == user.id)
        stmt = stmt.where(
            (Activity.deal_id.in_(owned))
            | (Activity.created_by_user_id == user.id)
        )
    return list(db.scalars(stmt.order_by(Activity.created_at.desc())))
