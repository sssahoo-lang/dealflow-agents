"""Serialises domain events into outbox rows.

This is the *only* place an event's wire shape is decided. The frozen dataclasses
in app/events/schemas.py stay the single definition of "an event happened"; the
in-process bus and the outbox both derive from the same object, so the two
consumers can't drift apart.

`to_envelope` re-reads the aggregate from the session rather than widening the
dataclasses. The row is already in the transaction post-flush, so this is a local
read -- and it keeps the existing event-bus tests untouched.
"""

from datetime import datetime, timezone
from decimal import Decimal
from functools import singledispatch
from typing import Any

from sqlalchemy.orm import Session

from app.events.schemas import (
    ActivityCreated,
    ContactCreated,
    DealCreated,
    DealStageChanged,
    DomainEvent,
)
from app.models.activity import Activity
from app.models.contact import Contact
from app.models.deal import Deal
from app.models.outbox import OutboxEvent

EVENT_VERSION = 1


def _money(value: Decimal | float | None) -> str | None:
    """Money crosses the wire as a string, never a JSON number.

    json.dumps can't serialise Decimal, and casting to float silently loses
    precision -- 75000.10 does not round-trip. The consumer parses this back with
    BigDecimal(String).
    """
    if value is None:
        return None
    return f"{Decimal(str(value)):.2f}"


def _utc(dt: datetime | None) -> str | None:
    """The legacy timestamp columns are naive but hold UTC (the container runs UTC).

    Attach the zone explicitly so no consumer has to guess -- emitting a naive ISO
    string across a service boundary is how off-by-hours bugs start.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _deal_payload(db: Session, deal_id: int) -> dict[str, Any]:
    deal = db.get(Deal, deal_id)
    if deal is None:  # pragma: no cover - defensive; the row is in this transaction
        raise ValueError(f"Deal {deal_id} not found while building an outbox payload")

    company = deal.company
    owner = deal.owner
    contact = deal.primary_contact

    # owner_email / owner_name / company_name are denormalised on purpose: it is
    # what lets a consumer render a rep leaderboard without ever being granted
    # access to the users or companies tables.
    return {
        "deal_id": deal.id,
        "name": deal.name,
        "stage": deal.stage.value,
        "value": _money(deal.value),
        "priority": deal.priority.value if deal.priority else None,
        "score": deal.score,
        "expected_close_date": deal.expected_close_date.isoformat()
        if deal.expected_close_date
        else None,
        "company_id": deal.company_id,
        "company_name": company.name if company else None,
        "company_industry": company.industry if company else None,
        "owner_id": deal.owner_id,
        "owner_email": owner.email if owner else None,
        "owner_name": owner.full_name if owner else None,
        "primary_contact_id": deal.primary_contact_id,
        "primary_contact_name": f"{contact.first_name} {contact.last_name}"
        if contact
        else None,
        "created_at": _utc(deal.created_at),
        "stage_changed_at": _utc(deal.stage_changed_at),
    }


@singledispatch
def to_envelope(event: DomainEvent, db: Session) -> OutboxEvent:
    raise NotImplementedError(
        f"No outbox mapping for {type(event).__name__}. Add one in app/events/outbox.py "
        "-- an unmapped event would be silently invisible to every consumer."
    )


@to_envelope.register
def _(event: DealCreated, db: Session) -> OutboxEvent:
    return OutboxEvent(
        aggregate_type="deal",
        aggregate_id=event.deal_id,
        event_type="deal.created",
        event_version=EVENT_VERSION,
        payload=_deal_payload(db, event.deal_id),
    )


@to_envelope.register
def _(event: DealStageChanged, db: Session) -> OutboxEvent:
    payload = _deal_payload(db, event.deal_id)
    payload["from_stage"] = event.from_stage.value
    payload["to_stage"] = event.to_stage.value
    return OutboxEvent(
        aggregate_type="deal",
        aggregate_id=event.deal_id,
        event_type="deal.stage_changed",
        event_version=EVENT_VERSION,
        payload=payload,
    )


@to_envelope.register
def _(event: ContactCreated, db: Session) -> OutboxEvent:
    contact = db.get(Contact, event.contact_id)
    company = contact.company if contact else None
    return OutboxEvent(
        aggregate_type="contact",
        aggregate_id=event.contact_id,
        event_type="contact.created",
        event_version=EVENT_VERSION,
        payload={
            "contact_id": contact.id,
            "first_name": contact.first_name,
            "last_name": contact.last_name,
            "email": contact.email,
            "title": contact.title,
            "company_id": contact.company_id,
            "company_name": company.name if company else None,
            "owner_id": contact.owner_id,
        },
    )


@to_envelope.register
def _(event: ActivityCreated, db: Session) -> OutboxEvent:
    activity = db.get(Activity, event.activity_id)
    return OutboxEvent(
        aggregate_type="activity",
        aggregate_id=event.activity_id,
        event_type="activity.created",
        event_version=EVENT_VERSION,
        payload={
            "activity_id": activity.id,
            "deal_id": activity.deal_id,
            "contact_id": activity.contact_id,
            "type": activity.type.value,
            "subject": activity.subject,
            "is_draft": activity.is_draft,
            "created_by_user_id": activity.created_by_user_id,
            "created_at": _utc(activity.created_at),
        },
    )


def record(db: Session, event: DomainEvent) -> OutboxEvent:
    """Stage an outbox row in the CURRENT transaction. Does not commit.

    The caller must have flushed the aggregate first (so its id exists) and must
    commit afterwards. That ordering is the whole point: the event and the change
    it describes land together or not at all.
    """
    row = to_envelope(event, db)
    db.add(row)
    return row
