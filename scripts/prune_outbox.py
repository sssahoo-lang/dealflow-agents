"""Prune outbox events every consumer has already processed.

The outbox is append-only, so without this it grows forever. Pruning is
straightforward but has one rule that is cheap to honour now and expensive to
retrofit:

    NEVER prune above the MINIMUM floor across all consumers.

A single consumer makes this look trivial. Add a second one that is behind, or
temporarily stopped, and pruning to the fastest consumer's position silently
deletes events the slower one has not read -- a hole it can never recover from,
because the outbox is the only record.

The same reasoning applies to consumers that do not exist yet. Anything pruned
can no longer be replayed, so a future service cannot rebuild its projection
from scratch beyond the prune point. That is the real cost of retention, and it
is why the default window is generous.

Run: python scripts/prune_outbox.py [--dry-run] [--older-than-days N]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.db.base import SessionLocal  # noqa: E402

DEFAULT_RETENTION_DAYS = 30


def prune(dry_run: bool = False, older_than_days: int = DEFAULT_RETENTION_DAYS) -> dict:
    db = SessionLocal()
    try:
        consumers = db.execute(
            text("SELECT consumer, floor_event_id FROM analytics.consumer_offset")
        ).all()

        if not consumers:
            # Refuse rather than treat "nobody has read anything" as "everything is
            # safe to delete". An empty table means the consumer has not started,
            # not that its work is done.
            return {
                "status": "refused",
                "reason": "no registered consumers; pruning would delete unread events",
                "deleted": 0,
            }

        safe_floor = min(row.floor_event_id for row in consumers)
        if safe_floor <= 0:
            return {
                "status": "refused",
                "reason": (
                    f"the slowest consumer is still at floor {safe_floor}; "
                    "nothing has been confirmed processed"
                ),
                "deleted": 0,
                "consumers": {row.consumer: row.floor_event_id for row in consumers},
            }

        # Both conditions matter: id <= safe_floor proves every consumer has read
        # it, and the age window keeps recent history around for debugging even
        # once it has been consumed.
        params = {"floor": safe_floor, "days": older_than_days}
        eligible = db.execute(
            text(
                """
                SELECT count(*) FROM public.outbox_events
                 WHERE id <= :floor
                   AND occurred_at < now() - make_interval(days => :days)
                """
            ),
            params,
        ).scalar_one()

        if dry_run:
            db.rollback()
            return {
                "status": "dry-run",
                "safe_floor": safe_floor,
                "eligible": eligible,
                "deleted": 0,
                "consumers": {row.consumer: row.floor_event_id for row in consumers},
            }

        deleted = db.execute(
            text(
                """
                DELETE FROM public.outbox_events
                 WHERE id <= :floor
                   AND occurred_at < now() - make_interval(days => :days)
                """
            ),
            params,
        ).rowcount
        db.commit()
        return {
            "status": "pruned",
            "safe_floor": safe_floor,
            "deleted": deleted,
            "consumers": {row.consumer: row.floor_event_id for row in consumers},
        }
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--older-than-days",
        type=int,
        default=DEFAULT_RETENTION_DAYS,
        help=f"retain events newer than this many days (default {DEFAULT_RETENTION_DAYS})",
    )
    args = parser.parse_args()

    result = prune(dry_run=args.dry_run, older_than_days=args.older_than_days)

    if result["status"] == "refused":
        print(f"Refused: {result['reason']}")
        sys.exit(1)

    print(f"Consumers: {result.get('consumers')}")
    print(f"Safe floor (slowest consumer): {result['safe_floor']}")
    if result["status"] == "dry-run":
        print(f"Would delete {result['eligible']} event(s) older than {args.older_than_days}d.")
    else:
        print(f"Deleted {result['deleted']} event(s).")


if __name__ == "__main__":
    main()
