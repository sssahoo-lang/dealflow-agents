"""Retention safety.

Pruning is irreversible: the outbox is the only record of an event, so anything
deleted can never be replayed. These pin the refusals that stop a routine
cleanup job from quietly destroying a consumer's ability to catch up.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.models import OutboxEvent  # noqa: E402
from scripts.prune_outbox import prune  # noqa: E402


@pytest.fixture
def offsets(db):
    """The consumer_offset table lives in the analytics schema, which only exists
    once the Java service's Flyway migrations have run. Create a stand-in so this
    test does not depend on the other service having started."""
    db.execute(text("CREATE SCHEMA IF NOT EXISTS analytics"))
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS analytics.consumer_offset (
                consumer TEXT PRIMARY KEY,
                floor_event_id BIGINT NOT NULL DEFAULT 0,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    db.execute(text("DELETE FROM analytics.consumer_offset"))
    db.commit()

    def _set(**consumers: int):
        for name, floor in consumers.items():
            db.execute(
                text(
                    "INSERT INTO analytics.consumer_offset (consumer, floor_event_id) "
                    "VALUES (:c, :f)"
                ),
                {"c": name, "f": floor},
            )
        db.commit()

    yield _set
    db.execute(text("DELETE FROM analytics.consumer_offset"))
    db.commit()


def seed_events(db, count: int) -> list[int]:
    rows = []
    for i in range(count):
        event = OutboxEvent(
            aggregate_type="deal",
            aggregate_id=i,
            event_type="deal.created",
            payload={"deal_id": i},
        )
        db.add(event)
        rows.append(event)
    db.commit()
    return [e.id for e in rows]


def test_refuses_when_no_consumer_is_registered(db, offsets):
    """An empty offset table means the consumer never started -- not that its
    work is done. Treating those as equivalent deletes everything."""
    seed_events(db, 3)

    result = prune(dry_run=False, older_than_days=0)

    assert result["status"] == "refused"
    assert "no registered consumers" in result["reason"]
    assert db.query(OutboxEvent).count() == 3


def test_refuses_when_the_slowest_consumer_has_read_nothing(db, offsets):
    seed_events(db, 3)
    offsets(analytics=0)

    result = prune(dry_run=False, older_than_days=0)

    assert result["status"] == "refused"
    assert db.query(OutboxEvent).count() == 3


def test_prunes_only_up_to_the_slowest_consumer(db, offsets):
    """The rule that matters. Pruning to the fastest consumer's position would
    delete events the slower one has not read, leaving an unrecoverable hole."""
    ids = seed_events(db, 5)
    offsets(analytics=ids[4], reporting=ids[1])  # one caught up, one behind

    result = prune(dry_run=False, older_than_days=0)

    assert result["status"] == "pruned"
    assert result["safe_floor"] == ids[1]
    remaining = {e.id for e in db.query(OutboxEvent).all()}
    assert ids[0] not in remaining and ids[1] not in remaining
    assert {ids[2], ids[3], ids[4]}.issubset(remaining)


def test_retention_window_keeps_recent_events(db, offsets):
    """Consumed is not the same as safe to delete: recent history stays for
    debugging even once every consumer has read it."""
    ids = seed_events(db, 3)
    offsets(analytics=ids[2])

    result = prune(dry_run=False, older_than_days=30)

    assert result["deleted"] == 0
    assert db.query(OutboxEvent).count() == 3


def test_dry_run_reports_without_deleting(db, offsets):
    ids = seed_events(db, 3)
    offsets(analytics=ids[2])

    result = prune(dry_run=True, older_than_days=0)

    assert result["status"] == "dry-run"
    assert result["eligible"] == 3
    assert db.query(OutboxEvent).count() == 3
