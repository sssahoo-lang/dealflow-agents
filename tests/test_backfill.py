"""Tests for the outbox backfill and the JWT claims added for cross-service auth."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jose import jwt  # noqa: E402

from app.config import settings  # noqa: E402
from app.core.security import create_access_token, decode_access_token  # noqa: E402
from app.models import Activity, OutboxEvent  # noqa: E402
from app.models.enums import ActivityType  # noqa: E402
from scripts.backfill_outbox import (  # noqa: E402
    backfill_activities,
    backfill_contacts,
    backfill_deals,
)


def snapshots(db, event_type: str) -> list[OutboxEvent]:
    return db.query(OutboxEvent).filter(OutboxEvent.event_type == event_type).all()


# --- backfill ----------------------------------------------------------------


def test_deals_get_snapshot_rows(db, crm_data):
    written = backfill_deals(db)
    db.commit()

    assert written == 2  # the two deals in crm_data
    rows = snapshots(db, "deal.snapshot")
    assert {r.aggregate_id for r in rows} == {
        crm_data["deal"].id,
        crm_data["other_deal"].id,
    }


def test_snapshot_payload_matches_the_live_event_shape(db, crm_data):
    """A consumer parses snapshots with the same code as real events, so the
    payload shape must not diverge."""
    backfill_deals(db)
    db.commit()

    payload = snapshots(db, "deal.snapshot")[0].payload
    assert payload["owner_email"]
    assert payload["company_name"] == "Acme"
    assert isinstance(payload["value"], str)


def test_snapshots_use_a_distinct_event_type(db, crm_data):
    """"Current state as of the backfill" must be distinguishable from "this
    change just happened" -- reusing deal.created would conflate them."""
    backfill_deals(db)
    db.commit()

    assert snapshots(db, "deal.created") == []
    assert snapshots(db, "deal.snapshot")


def test_running_twice_writes_nothing_the_second_time(db, crm_data):
    first = backfill_deals(db)
    db.commit()
    second = backfill_deals(db)
    db.commit()

    assert first == 2
    assert second == 0
    assert len(snapshots(db, "deal.snapshot")) == 2


def test_aggregates_with_a_real_event_are_skipped(db, crm_data, users):
    """A deal created after the outbox shipped already has deal.created; adding
    a snapshot for it would double-count it in a consumer's projection."""
    from app.schemas.crm import DealCreate
    from app.services import deal_service

    new_deal, _ = deal_service.create_deal(
        db,
        users["rep"],
        DealCreate(name="Post-outbox", company_id=crm_data["company"].id, value=1),
    )

    backfill_deals(db)
    db.commit()

    snapshotted = {r.aggregate_id for r in snapshots(db, "deal.snapshot")}
    assert new_deal.id not in snapshotted


def test_contacts_are_backfilled(db, crm_data):
    written = backfill_contacts(db)
    db.commit()

    assert written == 1
    assert snapshots(db, "contact.snapshot")[0].payload["company_name"] == "Acme"


def test_agent_activities_are_excluded_from_the_backfill(db, crm_data, users):
    """Consistent with live behaviour: agent notes are not customer touchpoints."""
    db.add_all(
        [
            Activity(
                deal_id=crm_data["deal"].id,
                type=ActivityType.call,
                body="Human call",
                created_by_user_id=users["rep"].id,
            ),
            Activity(
                deal_id=crm_data["deal"].id,
                type=ActivityType.agent_generated,
                body="Agent reasoning",
                created_by_user_id=None,
            ),
        ]
    )
    db.commit()

    written = backfill_activities(db)
    db.commit()

    assert written == 1
    assert snapshots(db, "activity.snapshot")[0].payload["type"] == "call"


# --- JWT claims for a consumer with no users table ---------------------------


def decoded(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, [settings.jwt_algorithm])


def test_login_token_carries_uid_and_role(client, users, token):
    """The Java service can't resolve an email to an id or role, so it can't
    scope a query without these."""
    claims = decoded(token("rep@test.com")["Authorization"].removeprefix("Bearer "))

    assert claims["sub"] == "rep@test.com"
    assert claims["uid"] == users["rep"].id
    assert claims["role"] == "rep"


def test_admin_role_is_carried_accurately(client, users, token):
    claims = decoded(token("admin@test.com")["Authorization"].removeprefix("Bearer "))

    assert claims["role"] == "admin"


def test_claims_are_optional_and_omitted_when_absent():
    """Backwards compatible: a token minted without them is still valid."""
    claims = decoded(create_access_token("someone@example.com"))

    assert claims["sub"] == "someone@example.com"
    assert "uid" not in claims
    assert "role" not in claims


def test_python_still_authenticates_off_sub_alone():
    """Python resolves the user from the database, so adding claims changed
    nothing about how this side validates a token."""
    assert decode_access_token(create_access_token("x@y.com")) == "x@y.com"
    assert (
        decode_access_token(create_access_token("x@y.com", uid=1, role="admin"))
        == "x@y.com"
    )
