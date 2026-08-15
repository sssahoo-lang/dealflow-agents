from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, Integer, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OutboxEvent(Base):
    """An append-only log of domain events, written in the same transaction as the
    change that produced them.

    This is the durability fix for the in-process event bus: the bus is a
    best-effort in-process notification, whereas a row here is committed
    atomically with the deal or contact it describes. If the process dies, the
    event is still on disk.

    Deliberately has no `status`, `processed_at`, or `attempts` column. Consumer
    progress belongs to the consumer, tracked in its own schema -- which is what
    lets a future consumer be granted SELECT and nothing else on this table.
    Adding a status column here would force write access and turn a published
    contract back into a shared mutable table.
    """

    __tablename__ = "outbox_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # What the event is about: ("deal", 42) etc.
    aggregate_type: Mapped[str] = mapped_column(String(50))
    aggregate_id: Mapped[int] = mapped_column(BigInteger)

    # e.g. "deal.created", "deal.stage_changed", "deal.snapshot"
    event_type: Mapped[str] = mapped_column(String(80))

    # Lets the payload shape change without breaking a deployed consumer.
    event_version: Mapped[int] = mapped_column(SmallInteger, default=1, server_default="1")

    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)

    # timestamptz on purpose. The legacy columns on deals/activities are naive
    # `timestamp`, which only stores UTC by accident of the container's timezone;
    # the event stream is a cross-service contract and must be unambiguous.
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_outbox_aggregate", "aggregate_type", "aggregate_id", "id"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<OutboxEvent id={self.id} {self.event_type} "
            f"{self.aggregate_type}:{self.aggregate_id}>"
        )
