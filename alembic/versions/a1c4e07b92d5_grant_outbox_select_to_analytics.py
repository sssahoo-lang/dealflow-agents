"""grant outbox select to analytics

Revision ID: a1c4e07b92d5
Revises: 631ff3f8661c
Create Date: 2026-08-15

The `analytics` role is provisioned by db/init/01-analytics-role.sql, which may
run *before* outbox_events exists (init scripts run on an empty data directory,
Alembic runs later). This migration re-issues the grant so the ordering of those
two steps doesn't matter.

Guarded on the role existing, so `alembic upgrade head` still works against a
database that has no analytics role at all -- crm_test in CI, or a fresh clone
that hasn't provisioned it.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1c4e07b92d5"
down_revision: Union[str, None] = "631ff3f8661c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'analytics') THEN
                GRANT USAGE ON SCHEMA public TO analytics;
                GRANT SELECT ON public.outbox_events TO analytics;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'analytics') THEN
                REVOKE SELECT ON public.outbox_events FROM analytics;
            END IF;
        END
        $$;
        """
    )
