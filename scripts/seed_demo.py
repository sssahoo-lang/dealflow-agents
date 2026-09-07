"""Generate a realistic pipeline on top of the base seed.

The base seed proves the app works; three deals make every chart look broken.
This builds enough history for the dashboard to say something: wins and losses
spread over months, deals at every stage, stage transitions with plausible gaps
so velocity has samples, and a few deliberately stale deals so the rules engine
has something to find.

Deterministic (fixed random seed) so the dashboard looks the same every run and
screenshots stay reproducible.

Run: python scripts/seed_demo.py
"""

import random
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.db.base import SessionLocal  # noqa: E402
from app.events import outbox  # noqa: E402
from app.events.schemas import ActivityCreated, DealCreated, DealStageChanged  # noqa: E402
from app.models import Activity, Company, Contact, Deal, User  # noqa: E402
from app.models.enums import ActivityType, DealStage, Priority  # noqa: E402

random.seed(20260904)

COMPANIES = [
    ("Northwind Health", "northwind.health", "Healthcare"),
    ("Cobalt Logistics", "cobaltlog.io", "Logistics"),
    ("Meridian Financial", "meridianfin.example", "Financial Services"),
    ("Sunward Energy", "sunward.example", "Energy"),
    ("Vertex Robotics", "vertexrobotics.example", "Manufacturing"),
    ("Harbor Retail Group", "harborretail.example", "Retail"),
    ("Lumen Analytics", "lumenanalytics.example", "Software"),
    ("Ironbridge Construction", "ironbridge.example", "Construction"),
]

TITLES = [
    "VP of Operations", "Chief Technology Officer", "Head of Procurement",
    "Director of Finance", "Operations Manager", "Chief Operating Officer",
    "Procurement Analyst", "VP of Engineering",
]

FIRST = ["Dana", "Sam", "Lee", "Priya", "Marcus", "Elena", "Tobias", "Ruth",
         "Amara", "Nikhil", "Sofia", "Ben"]
LAST = ["Reyes", "Okafor", "Tran", "Sharma", "Bell", "Novak", "Fischer",
        "Mbeki", "Costa", "Iyer", "Lindqvist", "Hale"]

DEAL_SUFFIXES = [
    "platform rollout", "pilot programme", "annual renewal", "capacity expansion",
    "site migration", "compliance upgrade", "fleet modernisation", "data integration",
]

# Ordered pipeline, with the fraction of deals that end up at each stage.
OUTCOMES = (
    [DealStage.won] * 7
    + [DealStage.lost] * 4
    + [DealStage.negotiation] * 3
    + [DealStage.proposal] * 5
    + [DealStage.qualified] * 4
    + [DealStage.new] * 3
)
LADDER = [DealStage.new, DealStage.qualified, DealStage.proposal,
          DealStage.negotiation]


def utc_days_ago(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def seed_demo() -> None:
    db = SessionLocal()
    try:
        users = db.query(User).all()
        if not users:
            print("Run scripts/seed.py first -- this builds on top of it.")
            return
        if db.query(Deal).count() > 12:
            print("Demo pipeline already present. Nothing to do.")
            return

        reps = [u for u in users if u.role.value == "rep"] or users
        admin = next((u for u in users if u.role.value == "admin"), users[0])
        owners = reps + [admin]

        companies = []
        for name, domain, industry in COMPANIES:
            existing = db.query(Company).filter(Company.name == name).first()
            if existing:
                companies.append(existing)
                continue
            company = Company(
                name=name, domain=domain, industry=industry,
                owner_id=random.choice(owners).id)
            db.add(company)
            companies.append(company)
        db.flush()

        contacts = []
        for company in companies:
            for _ in range(random.randint(1, 2)):
                contact = Contact(
                    company_id=company.id,
                    first_name=random.choice(FIRST),
                    last_name=random.choice(LAST),
                    email=f"contact{random.randint(100, 999)}@{company.domain}",
                    title=random.choice(TITLES),
                    owner_id=company.owner_id,
                )
                db.add(contact)
                contacts.append(contact)
        db.flush()

        created = 0
        for outcome in OUTCOMES:
            company = random.choice(companies)
            company_contacts = [c for c in contacts if c.company_id == company.id]
            owner_id = company.owner_id
            owner = next(u for u in users if u.id == owner_id)
            opened_days_ago = random.randint(20, 150)

            deal = Deal(
                name=f"{company.name.split()[0]} {random.choice(DEAL_SUFFIXES)}",
                company_id=company.id,
                primary_contact_id=company_contacts[0].id if company_contacts else None,
                owner_id=owner_id,
                stage=DealStage.new,
                value=Decimal(random.choice(
                    [8_500, 12_000, 24_000, 38_500, 55_000, 72_000, 96_000,
                     125_000, 180_000, 240_000])),
                expected_close_date=(
                    date.today() + timedelta(days=random.randint(-20, 120))
                    if outcome not in (DealStage.won, DealStage.lost)
                    else None),
            )
            db.add(deal)
            db.flush()

            # Backdate creation so the funnel and velocity have real spans.
            opened_at = utc_days_ago(opened_days_ago)
            db.execute(
                text("UPDATE deals SET created_at = :t, stage_changed_at = :t WHERE id = :id"),
                {"t": opened_at.replace(tzinfo=None), "id": deal.id})
            outbox.record(db, DealCreated(
                deal_id=deal.id, company_id=deal.company_id, owner_id=deal.owner_id))
            # Flush now. ORM-added rows are written at commit, but the raw stage
            # INSERTs below execute immediately -- without this the created event
            # would get a HIGHER id than the transitions that follow it, and the
            # consumer's last_event_id guard would correctly reject them, leaving
            # every deal stuck in 'new'.
            db.flush()

            # Walk the ladder toward the outcome, leaving gaps between stages.
            path = LADDER[: LADDER.index(outcome) + 1] if outcome in LADDER else LADDER
            at = opened_days_ago
            previous = DealStage.new
            for stage in path[1:]:
                at = max(1, at - random.randint(3, 18))
                db.execute(
                    text("""INSERT INTO outbox_events
                            (aggregate_type, aggregate_id, event_type, event_version,
                             payload, occurred_at)
                            VALUES ('deal', :id, 'deal.stage_changed', 1,
                                    CAST(:payload AS jsonb), :t)"""),
                    {"id": deal.id, "t": utc_days_ago(at),
                     "payload": _stage_payload(deal, company, owner, previous, stage)})
                previous = stage

            if outcome in (DealStage.won, DealStage.lost):
                at = max(1, at - random.randint(2, 14))
                db.execute(
                    text("""INSERT INTO outbox_events
                            (aggregate_type, aggregate_id, event_type, event_version,
                             payload, occurred_at)
                            VALUES ('deal', :id, 'deal.stage_changed', 1,
                                    CAST(:payload AS jsonb), :t)"""),
                    {"id": deal.id, "t": utc_days_ago(at),
                     "payload": _stage_payload(deal, company, owner, previous, outcome)})

            deal.stage = outcome
            deal.score = round(random.uniform(15, 95), 1)
            deal.priority = (
                Priority.high if deal.score >= 80
                else Priority.medium if deal.score >= 50
                else Priority.low)

            # Some deals go deliberately quiet so the rules engine has findings.
            quiet_days = random.choice([1, 2, 4, 6, 9, 16, 21, 30])
            for i in range(random.randint(1, 4)):
                activity = Activity(
                    deal_id=deal.id,
                    type=random.choice(
                        [ActivityType.call, ActivityType.email, ActivityType.meeting,
                         ActivityType.note]),
                    subject=random.choice(
                        ["Discovery call", "Sent proposal", "Pricing questions",
                         "Onsite walkthrough", "Security review", "Contract redlines"]),
                    body="Logged by the demo seeder.",
                    created_by_user_id=owner_id,
                )
                db.add(activity)
                db.flush()
                when = utc_days_ago(quiet_days + i * random.randint(3, 10))
                db.execute(
                    text("UPDATE activities SET created_at = :t WHERE id = :id"),
                    {"t": when.replace(tzinfo=None), "id": activity.id})
                outbox.record(db, ActivityCreated(
                    activity_id=activity.id, deal_id=deal.id, contact_id=None))
            created += 1

        db.commit()
        print(f"  {len(companies)} companies, {len(contacts)} contacts, {created} deals")
        print("  Stage transitions and activity history backdated over ~5 months.")
        print("  Wait ~5s for the analytics service to consume the events.")
    finally:
        db.close()


def _stage_payload(deal, company, owner, from_stage, to_stage) -> str:
    import json
    return json.dumps({
        "deal_id": deal.id,
        "name": deal.name,
        "stage": to_stage.value,
        "value": f"{deal.value:.2f}",
        "priority": None,
        "score": None,
        "expected_close_date": deal.expected_close_date.isoformat()
        if deal.expected_close_date else None,
        "company_id": company.id,
        "company_name": company.name,
        "company_industry": company.industry,
        "owner_id": deal.owner_id,
        # Real values, not None: the consumer upserts the projection directly
        # from this payload, so a null here would blank the leaderboard's
        # owner column on every stage change.
        "owner_email": owner.email,
        "owner_name": owner.full_name,
        "primary_contact_id": deal.primary_contact_id,
        "primary_contact_name": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "stage_changed_at": datetime.now(timezone.utc).isoformat(),
        "from_stage": from_stage.value,
        "to_stage": to_stage.value,
    })


if __name__ == "__main__":
    seed_demo()
