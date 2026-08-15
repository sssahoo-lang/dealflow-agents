-- Provisions the `analytics` role used by the Java analytics service.
--
-- The point of this file is that the service's access limits are enforced by
-- Postgres, not by convention or code review. The Java service reads exactly one
-- table -- public.outbox_events, a published versioned contract -- and cannot see
-- deals, contacts, activities, companies or users even if its code tried to.
--
-- Verify with:
--   SELECT has_table_privilege('analytics','public.deals','SELECT');          -- f
--   SELECT has_table_privilege('analytics','public.outbox_events','SELECT');  -- t
--   SELECT has_table_privilege('analytics','public.outbox_events','UPDATE');  -- f
--
-- NOTE: scripts in /docker-entrypoint-initdb.d run ONLY when the data directory
-- is empty. On an existing volume, apply this by hand instead:
--   docker compose exec -T db psql -U crm -d crm < db/init/01-analytics-role.sql
-- It is written to be safely rerunnable either way.

\set analytics_password `echo "${ANALYTICS_DB_PASSWORD:-analytics}"`

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'analytics') THEN
        CREATE ROLE analytics LOGIN;
    END IF;
END
$$;

ALTER ROLE analytics WITH PASSWORD :'analytics_password';

-- A runaway analytics query must not be able to hold connections on the shared
-- instance indefinitely. Paired with a small Hikari pool on the Java side.
ALTER ROLE analytics SET statement_timeout = '10s';
ALTER ROLE analytics SET search_path = analytics;

-- The analytics service owns this schema outright, so Flyway needs no superuser.
CREATE SCHEMA IF NOT EXISTS analytics AUTHORIZATION analytics;

-- Deny-by-default on everything Python owns...
REVOKE ALL ON SCHEMA public FROM analytics;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM analytics;

-- ...then grant back exactly one table, read-only. USAGE alone does not expose
-- any table; it only permits naming objects inside the schema.
GRANT USAGE ON SCHEMA public TO analytics;

DO $$
BEGIN
    IF to_regclass('public.outbox_events') IS NOT NULL THEN
        GRANT SELECT ON public.outbox_events TO analytics;
    ELSE
        -- The table is created by an Alembic migration, which may not have run
        -- yet on a fresh volume. The migration re-issues this grant, so first
        -- boot ordering does not matter.
        RAISE NOTICE 'public.outbox_events does not exist yet; the Alembic migration will grant SELECT.';
    END IF;
END
$$;

-- Future tables created in public must NOT become readable by default.
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM analytics;
