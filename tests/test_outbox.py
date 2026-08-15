"""Tests for the outbox table itself.

Service-level tests (that a deal write produces an outbox row in the same
transaction) come with the B2 refactor. These pin the schema contract that
a future consumer in another service will depend on.
"""

from sqlalchemy import text

from app.db.base import Base
from app.models import OutboxEvent


def make_event(**overrides) -> OutboxEvent:
    defaults = {
        "aggregate_type": "deal",
        "aggregate_id": 1,
        "event_type": "deal.created",
        "payload": {"deal_id": 1, "value": "1000.00"},
    }
    return OutboxEvent(**{**defaults, **overrides})


def test_model_is_registered_on_the_metadata():
    """If the import is dropped from app/models/__init__.py, alembic autogenerate
    silently skips the table and the test DB never creates it."""
    assert "outbox_events" in Base.metadata.tables


def test_row_round_trips(db):
    db.add(make_event())
    db.commit()

    stored = db.query(OutboxEvent).one()
    assert stored.id is not None
    assert stored.aggregate_type == "deal"
    assert stored.event_type == "deal.created"
    assert stored.payload == {"deal_id": 1, "value": "1000.00"}


def test_event_version_defaults_to_one(db):
    """Consumers branch on this to tolerate a payload shape change."""
    db.add(make_event())
    db.commit()

    assert db.query(OutboxEvent).one().event_version == 1


def test_occurred_at_is_timezone_aware(db):
    """The legacy created_at columns are naive; the event stream must not be,
    because it is read by a service that may run in another timezone."""
    db.add(make_event())
    db.commit()

    occurred_at = db.query(OutboxEvent).one().occurred_at
    assert occurred_at.tzinfo is not None

    # Compare against the *database* clock, not the host's. occurred_at is set by
    # the server, and a Docker VM clock routinely drifts from the host by a minute
    # or more after the host sleeps -- asserting against datetime.now() here makes
    # the test flaky for reasons that have nothing to do with the code.
    db_now = db.execute(text("SELECT now()")).scalar_one()
    assert abs((db_now - occurred_at).total_seconds()) < 60


def test_ids_are_monotonic_within_a_session(db):
    db.add_all([make_event(aggregate_id=i) for i in range(3)])
    db.commit()

    ids = [e.id for e in db.query(OutboxEvent).order_by(OutboxEvent.id)]
    assert ids == sorted(ids)
    assert len(set(ids)) == 3


def test_payload_survives_nested_structures(db):
    """Payloads carry denormalised nested objects, not just flat key/value."""
    payload = {
        "deal": {"id": 7, "value": "75000.00"},
        "owner": {"email": "rep@test.com"},
        "tags": ["a", "b"],
        "score": None,
    }
    db.add(make_event(payload=payload))
    db.commit()
    db.expire_all()

    assert db.query(OutboxEvent).one().payload == payload


def test_table_has_no_consumer_state_columns():
    """Deliberate design decision: consumer progress lives in the consumer's own
    schema, so this table can be granted SELECT-only to another service."""
    columns = set(OutboxEvent.__table__.columns.keys())

    assert not columns & {"status", "processed_at", "attempts", "consumer"}
