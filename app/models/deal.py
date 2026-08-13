from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Enum, Float, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import DealStage, Priority


class Deal(Base):
    __tablename__ = "deals"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    primary_contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id"), nullable=True
    )
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    stage: Mapped[DealStage] = mapped_column(
        Enum(DealStage, name="deal_stage"), default=DealStage.new
    )
    value: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)

    # Populated by the lead-scoring agent, not by users.
    priority: Mapped[Priority | None] = mapped_column(
        Enum(Priority, name="priority"), nullable=True
    )
    score: Mapped[float | None] = mapped_column(Float, nullable=True)

    expected_close_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    stage_changed_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    company: Mapped["Company"] = relationship(back_populates="deals")
    primary_contact: Mapped["Contact | None"] = relationship()
    activities: Mapped[list["Activity"]] = relationship(back_populates="deal")
