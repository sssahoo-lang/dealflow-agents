from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.enums import ActivityType, DealStage, Priority


class CompanyCreate(BaseModel):
    name: str
    domain: str | None = None
    industry: str | None = None


class CompanyOut(CompanyCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int | None
    created_at: datetime


class ContactCreate(BaseModel):
    first_name: str
    last_name: str
    company_id: int | None = None
    email: str | None = None
    phone: str | None = None
    title: str | None = None


class ContactOut(ContactCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    created_at: datetime


class DealCreate(BaseModel):
    name: str
    company_id: int
    primary_contact_id: int | None = None
    value: Decimal = Decimal(0)
    stage: DealStage = DealStage.new
    expected_close_date: date | None = None


class DealUpdate(BaseModel):
    name: str | None = None
    value: Decimal | None = None
    stage: DealStage | None = None
    expected_close_date: date | None = None


class DealOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    company_id: int
    primary_contact_id: int | None
    owner_id: int
    stage: DealStage
    value: Decimal
    priority: Priority | None
    score: float | None
    expected_close_date: date | None
    created_at: datetime
    stage_changed_at: datetime


class ActivityCreate(BaseModel):
    type: ActivityType
    body: str
    subject: str | None = None
    deal_id: int | None = None
    contact_id: int | None = None


class ActivityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    deal_id: int | None
    contact_id: int | None
    created_by_user_id: int | None
    type: ActivityType
    subject: str | None
    body: str
    is_draft: bool
    meta: dict[str, Any] | None
    created_at: datetime
