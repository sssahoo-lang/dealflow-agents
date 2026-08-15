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


# --- service integration: rows are written in the domain transaction ---------

import json  # noqa: E402
from decimal import Decimal  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from app.events import outbox  # noqa: E402
from app.events.schemas import DomainEvent  # noqa: E402
from app.models.deal import Deal  # noqa: E402
from app.models.enums import DealStage  # noqa: E402
from app.schemas.crm import ActivityCreate, ContactCreate, DealCreate, DealUpdate  # noqa: E402
from app.services import crm_service, deal_service  # noqa: E402

CONTRACT_DIR = Path(__file__).resolve().parents[1] / "contracts" / "events"


def events(db, event_type: str | None = None) -> list[OutboxEvent]:
    q = db.query(OutboxEvent)
    if event_type is not None:
        q = q.filter(OutboxEvent.event_type == event_type)
    return q.order_by(OutboxEvent.id).all()


def test_creating_a_deal_writes_exactly_one_row(db, crm_data, users):
    deal, _ = deal_service.create_deal(
        db,
        users["rep"],
        DealCreate(name="Outbox deal", company_id=crm_data["company"].id, value=1000),
    )

    rows = events(db, "deal.created")
    assert len(rows) == 1
    assert rows[0].aggregate_type == "deal"
    assert rows[0].aggregate_id == deal.id
    assert rows[0].event_version == 1


def test_payload_matches_the_shared_contract_fixture(db, crm_data, users):
    """The Java consumer will assert against this same file. If either side
    changes the shape without the other, one of the two tests goes red."""
    contract = json.loads((CONTRACT_DIR / "deal.created.v1.json").read_text())

    deal_service.create_deal(
        db,
        users["rep"],
        DealCreate(name="Contract deal", company_id=crm_data["company"].id, value=1000),
    )

    payload = events(db, "deal.created")[0].payload
    assert set(payload) == set(contract["payload_keys"])


def test_money_is_a_string_with_two_decimals(db, crm_data, users):
    """A float round-trip silently corrupts money; BigDecimal(String) does not."""
    deal_service.create_deal(
        db,
        users["rep"],
        DealCreate(
            name="Precise", company_id=crm_data["company"].id, value=Decimal("75000.10")
        ),
    )

    value = events(db, "deal.created")[0].payload["value"]
    assert isinstance(value, str)
    assert value == "75000.10"


def test_payload_denormalises_owner_and_company(db, crm_data, users):
    """This is what lets a consumer render a leaderboard with no access to the
    users or companies tables."""
    deal_service.create_deal(
        db,
        users["rep"],
        DealCreate(name="Denorm", company_id=crm_data["company"].id, value=1),
    )

    payload = events(db, "deal.created")[0].payload
    assert payload["owner_email"] == users["rep"].email
    assert payload["company_name"] == "Acme"


def test_timestamps_carry_an_explicit_offset(db, crm_data, users):
    deal_service.create_deal(
        db,
        users["rep"],
        DealCreate(name="Stamped", company_id=crm_data["company"].id, value=1),
    )

    created_at = events(db, "deal.created")[0].payload["created_at"]
    assert created_at.endswith("+00:00")


def test_stage_change_records_both_stages(db, crm_data, users):
    deal = crm_data["deal"]
    before = deal.stage

    deal_service.update_deal(
        db, users["admin"], deal.id, DealUpdate(stage=DealStage.negotiation)
    )

    rows = events(db, "deal.stage_changed")
    assert len(rows) == 1
    assert rows[0].payload["from_stage"] == before.value
    assert rows[0].payload["to_stage"] == "negotiation"
    # The payload describes post-update state, not the row as it was before.
    assert rows[0].payload["stage"] == "negotiation"


def test_non_stage_update_writes_no_row(db, crm_data, users):
    """The counterpart to test_deal_events: no phantom transitions in the log."""
    deal_service.update_deal(
        db, users["rep"], crm_data["deal"].id, DealUpdate(name="Renamed", value=42)
    )

    assert events(db) == []


def test_creating_a_contact_writes_a_row(db, crm_data, users):
    crm_service.create_contact(
        db,
        users["rep"],
        ContactCreate(
            first_name="New", last_name="Person", company_id=crm_data["company"].id
        ),
    )

    rows = events(db, "contact.created")
    assert len(rows) == 1
    assert rows[0].payload["first_name"] == "New"
    assert rows[0].payload["company_name"] == "Acme"


def test_creating_an_activity_writes_a_row(db, crm_data, users):
    """Recorded for the future rules engine, which needs activity recency."""
    crm_service.create_activity(
        db,
        users["rep"],
        ActivityCreate(deal_id=crm_data["deal"].id, type="call", body="Spoke to Dana"),
    )

    rows = events(db, "activity.created")
    assert len(rows) == 1
    assert rows[0].payload["deal_id"] == crm_data["deal"].id
    assert rows[0].payload["type"] == "call"


def test_deal_and_event_commit_atomically(db, crm_data, users, monkeypatch):
    """The whole point of the outbox: if the event can't be written, the change
    it describes must not survive either."""
    deals_before = db.query(Deal).count()

    def explode(db_, event):
        raise RuntimeError("serialiser failed")

    monkeypatch.setattr(outbox, "record", explode)

    with pytest.raises(RuntimeError):
        deal_service.create_deal(
            db,
            users["rep"],
            DealCreate(name="Doomed", company_id=crm_data["company"].id, value=1),
        )

    db.rollback()
    assert db.query(Deal).count() == deals_before
    assert not db.query(Deal).filter(Deal.name == "Doomed").first()
    assert events(db) == []


def test_unmapped_event_fails_loudly(db):
    """Silently skipping an unmapped event would make it invisible to consumers."""

    class Unmapped(DomainEvent):
        pass

    with pytest.raises(NotImplementedError, match="Unmapped"):
        outbox.record(db, Unmapped())


def test_failed_deal_insert_leaves_no_event(db, users):
    """The reverse direction: an event must never outlive a change that never
    landed. A bad company_id fails at flush, before record() is reached."""
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        deal_service.create_deal(
            db,
            users["rep"],
            DealCreate(name="Orphan", company_id=999999, value=1),
        )

    db.rollback()
    assert events(db) == []
    assert not db.query(Deal).filter(Deal.name == "Orphan").first()


def test_agent_written_activities_stay_out_of_the_event_stream(db, crm_data, users, fake_llm):
    """Agent notes are not customer touchpoints. If they reached the stream, a
    rule like "no touchpoint in 14 days" would treat scoring as engagement."""
    from app.agents.lead_scoring.graph import LeadScore, run
    from app.models.enums import Priority

    fake_llm(LeadScore(score=50.0, priority=Priority.medium, reasoning="Mid."))

    run(db, crm_data["deal"].id)

    assert events(db, "activity.created") == []
