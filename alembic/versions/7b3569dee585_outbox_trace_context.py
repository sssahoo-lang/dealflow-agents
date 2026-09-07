"""outbox trace_context

Revision ID: 7b3569dee585
Revises: a1c4e07b92d5
Create Date: 2026-09-07 14:20:28.233959

Carries the W3C traceparent an outbox row was recorded under, so a distributed
trace can span the durability boundary: a request thread in the CRM writes the
row and returns; a Java consumer polls it, possibly seconds or minutes later, in
an unrelated thread in an unrelated process. Without something recorded at write
time there is nothing to link those two spans into one trace after the fact.

A sibling column rather than a payload field on purpose -- payload is the
cross-language contract asserted in contracts/events/*.json; this is
observability plumbing riding beside it, free to change shape independently.

No new GRANT needed: the existing `GRANT SELECT ON public.outbox_events` already
covers every column, this one included.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7b3569dee585'
down_revision: Union[str, None] = 'a1c4e07b92d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "outbox_events",
        sa.Column("trace_context", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("outbox_events", "trace_context")
