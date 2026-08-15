"""Emit snapshot events for rows that predate the outbox.

A consumer starting from an empty outbox would only ever see deals created
after the outbox shipped -- every existing deal would be invisible to it. This
writes one `*.snapshot` row per existing aggregate so a consumer can build a
complete projection by replaying the log alone, without ever reading the CRM's
own tables.

Snapshots use a distinct event_type rather than pretending to be `deal.created`:
a consumer should be able to tell "this is current state as of the backfill"
from "this is a change that happened".

Rerunnable. Skips aggregates that already have any outbox row, so running it
twice is a no-op rather than a duplicate-event bug.

Run: python scripts/backfill_outbox.py [--dry-run]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.base import SessionLocal  # noqa: E402
from app.events.outbox import EVENT_VERSION, _deal_payload, _utc  # noqa: E402
from app.models import Activity, Contact, Deal, OutboxEvent  # noqa: E402


def _already_recorded(db: Session, aggregate_type: str) -> set[int]:
    """Aggregate ids that already appear in the outbox, for any event type."""
    return set(
        db.scalars(
            select(OutboxEvent.aggregate_id).where(
                OutboxEvent.aggregate_type == aggregate_type
            )
        )
    )


def backfill_deals(db: Session) -> int:
    seen = _already_recorded(db, "deal")
    rows = 0
    for deal in db.scalars(select(Deal).order_by(Deal.id)):
        if deal.id in seen:
            continue
        db.add(
            OutboxEvent(
                aggregate_type="deal",
                aggregate_id=deal.id,
                event_type="deal.snapshot",
                event_version=EVENT_VERSION,
                payload=_deal_payload(db, deal.id),
            )
        )
        rows += 1
    return rows


def backfill_contacts(db: Session) -> int:
    seen = _already_recorded(db, "contact")
    rows = 0
    for contact in db.scalars(select(Contact).order_by(Contact.id)):
        if contact.id in seen:
            continue
        company = contact.company
        db.add(
            OutboxEvent(
                aggregate_type="contact",
                aggregate_id=contact.id,
                event_type="contact.snapshot",
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
        )
        rows += 1
    return rows


def backfill_activities(db: Session) -> int:
    """Human activities only -- agent notes deliberately stay out of the stream
    (see ActivityCreated in app/events/schemas.py)."""
    seen = _already_recorded(db, "activity")
    rows = 0
    stmt = select(Activity).where(Activity.created_by_user_id.is_not(None))
    for activity in db.scalars(stmt.order_by(Activity.id)):
        if activity.id in seen:
            continue
        db.add(
            OutboxEvent(
                aggregate_type="activity",
                aggregate_id=activity.id,
                event_type="activity.snapshot",
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
        )
        rows += 1
    return rows


def backfill(dry_run: bool = False) -> dict[str, int]:
    db = SessionLocal()
    try:
        counts = {
            "deal": backfill_deals(db),
            "contact": backfill_contacts(db),
            "activity": backfill_activities(db),
        }
        if dry_run:
            db.rollback()
        else:
            db.commit()
        return counts
    finally:
        db.close()


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    counts = backfill(dry_run=dry_run)
    total = sum(counts.values())

    if total == 0:
        print("Nothing to backfill -- every aggregate already has an outbox row.")
    else:
        for aggregate, count in counts.items():
            if count:
                print(f"  {aggregate:<9} {count} snapshot row(s)")
        print(f"{'Would write' if dry_run else 'Wrote'} {total} row(s).")


if __name__ == "__main__":
    main()
