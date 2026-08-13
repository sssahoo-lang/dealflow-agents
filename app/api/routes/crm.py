from fastapi import APIRouter, BackgroundTasks, status

from app.api.deps import CurrentUser, DbSession
from app.events.bus import event_bus
from app.schemas.crm import (
    ActivityCreate,
    ActivityOut,
    CompanyCreate,
    CompanyOut,
    ContactCreate,
    ContactOut,
    DealCreate,
    DealOut,
    DealUpdate,
)
from app.services import crm_service, deal_service

companies = APIRouter(prefix="/companies", tags=["companies"])
contacts = APIRouter(prefix="/contacts", tags=["contacts"])
deals = APIRouter(prefix="/deals", tags=["deals"])
activities = APIRouter(prefix="/activities", tags=["activities"])


@companies.post("", response_model=CompanyOut, status_code=status.HTTP_201_CREATED)
def create_company(db: DbSession, user: CurrentUser, payload: CompanyCreate):
    return crm_service.create_company(db, user, payload)


@companies.get("", response_model=list[CompanyOut])
def list_companies(db: DbSession, user: CurrentUser):
    return crm_service.list_companies(db)


@contacts.post("", response_model=ContactOut, status_code=status.HTTP_201_CREATED)
def create_contact(
    db: DbSession, user: CurrentUser, payload: ContactCreate, tasks: BackgroundTasks
):
    contact, event = crm_service.create_contact(db, user, payload)
    tasks.add_task(event_bus.publish, event)
    return contact


@contacts.get("", response_model=list[ContactOut])
def list_contacts(db: DbSession, user: CurrentUser):
    return crm_service.list_contacts(db, user)


@deals.post("", response_model=DealOut, status_code=status.HTTP_201_CREATED)
def create_deal(
    db: DbSession, user: CurrentUser, payload: DealCreate, tasks: BackgroundTasks
):
    deal, event = deal_service.create_deal(db, user, payload)
    # Published after commit so the lead-scoring agent only ever sees durable state.
    tasks.add_task(event_bus.publish, event)
    return deal


@deals.get("", response_model=list[DealOut])
def list_deals(db: DbSession, user: CurrentUser):
    return deal_service.list_deals(db, user)


@deals.get("/{deal_id}", response_model=DealOut)
def get_deal(db: DbSession, user: CurrentUser, deal_id: int):
    return deal_service.get_deal(db, user, deal_id)


@deals.patch("/{deal_id}", response_model=DealOut)
def update_deal(
    db: DbSession,
    user: CurrentUser,
    deal_id: int,
    payload: DealUpdate,
    tasks: BackgroundTasks,
):
    deal, event = deal_service.update_deal(db, user, deal_id, payload)
    if event is not None:
        tasks.add_task(event_bus.publish, event)
    return deal


@activities.post("", response_model=ActivityOut, status_code=status.HTTP_201_CREATED)
def create_activity(db: DbSession, user: CurrentUser, payload: ActivityCreate):
    return crm_service.create_activity(db, user, payload)


@activities.get("", response_model=list[ActivityOut])
def list_activities(
    db: DbSession,
    user: CurrentUser,
    deal_id: int | None = None,
    is_draft: bool | None = None,
):
    return crm_service.list_activities(db, user, deal_id, is_draft)
