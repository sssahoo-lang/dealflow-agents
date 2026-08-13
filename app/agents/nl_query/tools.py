"""Read-only, RBAC-scoped query tools for the NL query agent.

The model never sees or writes SQL. Each tool is a fixed SQLAlchemy select() with an
allowlisted set of filterable columns, a hard row limit, and an ownership filter
applied server-side from the authenticated user -- not from anything the model says.
"""

from langchain_core.tools import StructuredTool
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.contact import Contact
from app.models.deal import Deal
from app.models.enums import DealStage, Priority, RoleEnum
from app.models.user import User

ROW_LIMIT = 50


def _scope(stmt, model, user: User):
    """Reps are hard-scoped to their own records regardless of model reasoning."""
    if user.role is not RoleEnum.admin:
        stmt = stmt.where(model.owner_id == user.id)
    return stmt


def build_tools(db: Session, user: User) -> list[StructuredTool]:
    def query_deals(
        stage: str | None = None,
        priority: str | None = None,
        min_value: float | None = None,
        min_score: float | None = None,
    ) -> list[dict]:
        """Look up deals in the CRM. Optionally filter by stage
        (new/qualified/proposal/negotiation/won/lost), priority (low/medium/high),
        minimum value, or minimum lead score."""
        stmt = _scope(select(Deal), Deal, user)
        if stage is not None:
            stmt = stmt.where(Deal.stage == DealStage(stage))
        if priority is not None:
            stmt = stmt.where(Deal.priority == Priority(priority))
        if min_value is not None:
            stmt = stmt.where(Deal.value >= min_value)
        if min_score is not None:
            stmt = stmt.where(Deal.score >= min_score)
        stmt = stmt.order_by(Deal.score.desc().nullslast()).limit(ROW_LIMIT)
        return [
            {
                "id": d.id,
                "name": d.name,
                "stage": d.stage.value,
                "value": float(d.value),
                "score": d.score,
                "priority": d.priority.value if d.priority else None,
                "company": d.company.name if d.company else None,
            }
            for d in db.scalars(stmt)
        ]

    def query_contacts(
        company_name: str | None = None, title_contains: str | None = None
    ) -> list[dict]:
        """Look up contacts in the CRM, optionally filtered by company name or by a
        substring of their job title."""
        stmt = _scope(select(Contact), Contact, user)
        if company_name is not None:
            stmt = stmt.join(Company).where(Company.name.ilike(f"%{company_name}%"))
        if title_contains is not None:
            stmt = stmt.where(Contact.title.ilike(f"%{title_contains}%"))
        stmt = stmt.limit(ROW_LIMIT)
        return [
            {
                "id": c.id,
                "name": f"{c.first_name} {c.last_name}",
                "title": c.title,
                "email": c.email,
                "company": c.company.name if c.company else None,
            }
            for c in db.scalars(stmt)
        ]

    def aggregate_stats(group_by: str = "stage") -> list[dict]:
        """Aggregate pipeline statistics: deal count and total value, grouped by
        either 'stage' or 'priority'."""
        column = {"stage": Deal.stage, "priority": Deal.priority}.get(group_by)
        if column is None:
            return [{"error": "group_by must be 'stage' or 'priority'"}]
        stmt = _scope(
            select(column, func.count(Deal.id), func.coalesce(func.sum(Deal.value), 0)),
            Deal,
            user,
        ).group_by(column)
        return [
            {
                group_by: key.value if key else None,
                "deal_count": count,
                "total_value": float(total),
            }
            for key, count, total in db.execute(stmt)
        ]

    return [
        StructuredTool.from_function(query_deals),
        StructuredTool.from_function(query_contacts),
        StructuredTool.from_function(aggregate_stats),
    ]
