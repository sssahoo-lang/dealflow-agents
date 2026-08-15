"""The analytics role's access boundary, asserted rather than assumed.

Sharing one database between two services is only defensible because Postgres
grants -- not convention, not code review -- stop the analytics service from
reading anything except one published contract table. That guarantee is worth
exactly as much as the test that proves it, so it is checked here from the
Python side today and will be checked again from the Java side (step 5+).

These run against the `crm` database, not `crm_test`: the grants live where the
real tables do. Skipped entirely when the role has not been provisioned, so a
fresh clone or a CI run without db/init applied stays green.
"""

import pytest
from sqlalchemy import create_engine, text

CRM_URL = "postgresql+psycopg://crm:crm@localhost:5433/crm"


@pytest.fixture(scope="module")
def crm_conn():
    try:
        engine = create_engine(CRM_URL)
        conn = engine.connect()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"crm database unreachable: {exc}")

    role_exists = conn.execute(
        text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'analytics')")
    ).scalar_one()
    if not role_exists:
        conn.close()
        pytest.skip(
            "analytics role not provisioned; apply db/init/01-analytics-role.sql"
        )

    yield conn
    conn.close()


def privilege(conn, table: str, action: str) -> bool:
    return conn.execute(
        text("SELECT has_table_privilege('analytics', :t, :a)"),
        {"t": table, "a": action},
    ).scalar_one()


def test_analytics_can_read_the_outbox(crm_conn):
    """The one thing it is allowed to do."""
    assert privilege(crm_conn, "public.outbox_events", "SELECT") is True


@pytest.mark.parametrize("action", ["INSERT", "UPDATE", "DELETE"])
def test_analytics_cannot_write_to_the_outbox(crm_conn, action):
    """The log is owned by Python. A consumer that could write to it would make
    the table shared mutable state instead of a published contract."""
    assert privilege(crm_conn, "public.outbox_events", action) is False


@pytest.mark.parametrize(
    "table", ["public.deals", "public.users", "public.contacts",
              "public.companies", "public.activities"]
)
def test_analytics_cannot_read_crm_tables(crm_conn, table):
    """This is what makes the shared database defensible: the analytics service
    physically cannot reach CRM internals, so the payload contract is the only
    coupling between the two services."""
    assert privilege(crm_conn, table, "SELECT") is False


def test_analytics_owns_its_own_schema(crm_conn):
    """Flyway must be able to create tables in `analytics` without superuser."""
    owner = crm_conn.execute(
        text(
            "SELECT pg_get_userbyid(nspowner) FROM pg_namespace "
            "WHERE nspname = 'analytics'"
        )
    ).scalar_one_or_none()

    assert owner == "analytics"


def test_analytics_has_a_statement_timeout(crm_conn):
    """A runaway query must not hold connections on the shared instance."""
    settings = crm_conn.execute(
        text("SELECT rolconfig FROM pg_roles WHERE rolname = 'analytics'")
    ).scalar_one()

    assert settings is not None
    assert any(s.startswith("statement_timeout=") for s in settings)
