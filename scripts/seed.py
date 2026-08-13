"""Seed the CRM with demo users, companies, contacts, deals, and activities.

Run: python scripts/seed.py
"""

import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.security import hash_password  # noqa: E402
from app.db.base import SessionLocal  # noqa: E402
from app.models import Activity, Company, Contact, Deal, User  # noqa: E402
from app.models.enums import ActivityType, DealStage, RoleEnum  # noqa: E402

DEMO_PASSWORD = "demo1234"


def seed() -> None:
    db = SessionLocal()
    try:
        if db.query(User).first():
            print("Database already seeded. Drop tables or `alembic downgrade base` first.")
            return

        admin = User(
            email="admin@demo.com",
            hashed_password=hash_password(DEMO_PASSWORD),
            full_name="Ada Admin",
            role=RoleEnum.admin,
        )
        rep = User(
            email="rep@demo.com",
            hashed_password=hash_password(DEMO_PASSWORD),
            full_name="Raj Rep",
            role=RoleEnum.rep,
        )
        other_rep = User(
            email="rep2@demo.com",
            hashed_password=hash_password(DEMO_PASSWORD),
            full_name="Nina Rep",
            role=RoleEnum.rep,
        )
        db.add_all([admin, rep, other_rep])
        db.commit()

        companies = [
            Company(name="Acme Manufacturing", domain="acme.com", industry="Manufacturing", owner_id=rep.id),
            Company(name="Northwind Health", domain="northwind.health", industry="Healthcare", owner_id=rep.id),
            Company(name="Cobalt Logistics", domain="cobaltlog.io", industry="Logistics", owner_id=other_rep.id),
        ]
        db.add_all(companies)
        db.commit()
        acme, northwind, cobalt = companies

        contacts = [
            Contact(company_id=acme.id, first_name="Dana", last_name="Reyes", email="dana@acme.com", title="VP of Operations", owner_id=rep.id),
            Contact(company_id=northwind.id, first_name="Sam", last_name="Okafor", email="sam@northwind.health", title="Chief Technology Officer", owner_id=rep.id),
            Contact(company_id=cobalt.id, first_name="Lee", last_name="Tran", email="lee@cobaltlog.io", title="Procurement Analyst", owner_id=other_rep.id),
        ]
        db.add_all(contacts)
        db.commit()
        dana, sam, lee = contacts

        deals = [
            Deal(name="Acme plant rollout", company_id=acme.id, primary_contact_id=dana.id, owner_id=rep.id, stage=DealStage.proposal, value=Decimal("125000"), expected_close_date=date.today() + timedelta(days=30)),
            Deal(name="Northwind platform pilot", company_id=northwind.id, primary_contact_id=sam.id, owner_id=rep.id, stage=DealStage.qualified, value=Decimal("48000"), expected_close_date=date.today() + timedelta(days=60)),
            Deal(name="Cobalt fleet upgrade", company_id=cobalt.id, primary_contact_id=lee.id, owner_id=other_rep.id, stage=DealStage.new, value=Decimal("9500")),
        ]
        db.add_all(deals)
        db.commit()

        db.add_all([
            Activity(deal_id=deals[0].id, created_by_user_id=rep.id, type=ActivityType.meeting, subject="Onsite walkthrough", body="Toured the Ohio plant with Dana. She confirmed budget is approved for Q4 and wants a phased rollout across three lines."),
            Activity(deal_id=deals[0].id, created_by_user_id=rep.id, type=ActivityType.email, subject="Sent proposal v2", body="Sent revised pricing reflecting the three-line phasing. Dana said she would review with finance this week."),
            Activity(deal_id=deals[1].id, created_by_user_id=rep.id, type=ActivityType.call, subject="Discovery call", body="Sam is evaluating us against two competitors. Main concern is integration effort with their existing EHR."),
        ])
        db.commit()

        print("Seeded successfully.\n")
        print(f"  admin@demo.com / {DEMO_PASSWORD}  (role=admin)")
        print(f"  rep@demo.com   / {DEMO_PASSWORD}  (role=rep, owns deals 1-2)")
        print(f"  rep2@demo.com  / {DEMO_PASSWORD}  (role=rep, owns deal 3)")
        print(f"\n  deal ids: {[d.id for d in deals]}")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
