from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.deal import Deal


def load_deal_context(db: Session, deal_id: int) -> dict:
    """Shared context loader for the lead-scoring and follow-up agents."""
    deal = db.get(Deal, deal_id)
    if deal is None:
        raise ValueError(f"Deal {deal_id} not found")

    company = deal.company
    contact = deal.primary_contact
    history = (
        db.query(Activity)
        .filter(Activity.deal_id == deal_id)
        .order_by(Activity.created_at.desc())
        .limit(10)
        .all()
    )

    return {
        "deal": {
            "id": deal.id,
            "name": deal.name,
            "stage": deal.stage.value,
            "value": float(deal.value),
            "expected_close_date": str(deal.expected_close_date or ""),
        },
        "company": {
            "name": company.name if company else None,
            "industry": company.industry if company else None,
            "domain": company.domain if company else None,
        },
        "contact": {
            "name": f"{contact.first_name} {contact.last_name}" if contact else None,
            "title": contact.title if contact else None,
        },
        "activity_history": [
            {
                "type": a.type.value,
                "subject": a.subject,
                "body": a.body[:500],
                "created_at": str(a.created_at),
            }
            for a in history
        ],
    }
