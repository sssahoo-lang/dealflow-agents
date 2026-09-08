"""Quantifies the one claim the dashboard's Event pipeline tab only shows
qualitatively: how far behind is the Java consumer, really, and how long does
a full read-model rebuild take.

Two numbers, both real measurements against the running stack, not estimates:

1. **Consumer lag** -- for a burst of N synthetic `deal.created` events
   inserted in one transaction, the distribution of `processed_at - occurred_at`
   once the poller (default: every `ANALYTICS_OUTBOX_POLL_INTERVAL_MS`, 200 per
   batch) has drained them all. Reported as p50 and p99, in seconds.
2. **Replay time** -- with those same N events still sitting in the outbox,
   truncate the analytics read model and time how long a full rebuild takes,
   from empty to fully caught up. This is the "documented operation" the
   schema comment in V1__baseline.sql refers to, actually timed.

Deliberately writes synthetic outbox rows directly rather than N HTTP calls to
POST /deals: the CRM's request path (bcrypt, JWT, the ORM) is not what this
measures, and would dominate the wall-clock time of a real burst-load test
without telling you anything about the consumer. What's under test is the
poll -> dispatch -> project pipeline, so that's what gets isolated.

**Destructive.** Truncates public.outbox_events and every analytics table.
Run this against a disposable stack, not one you want the demo data in --
`docker compose down -v && docker compose up -d --build` first, then re-seed
afterward if you want the dashboard populated again.

Two DB connections on purpose, matching the actual access boundary: the `crm`
role owns public.outbox_events (insert + truncate); the `analytics` role owns
its own schema and cannot touch the CRM's tables at all -- it can only ever
SELECT outbox_events, which is the whole point of this repo's security model.
A benchmark script that could get away with using one omniscient connection
would be quietly asserting a weaker boundary than the one that's actually
enforced.

Run: python scripts/bench_outbox_lag.py --force
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.config import settings  # noqa: E402

DEAL_EVENT_TYPE = "deal.created"


def percentile(values: list[float], p: float) -> float:
    """Linear interpolation between closest ranks -- the same convention
    numpy.percentile uses by default, so a p50/p99 quoted here means the same
    thing it would anywhere else these numbers get compared.

    A pure function, kept free of anything DB- or Docker-shaped, so the
    percentile math itself has a unit test independent of a running stack.
    """
    if not values:
        raise ValueError("percentile of an empty sequence is undefined")
    if not 0 <= p <= 100:
        raise ValueError(f"p must be within [0, 100], got {p}")

    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]

    rank = (p / 100) * (len(ordered) - 1)
    lo, hi = int(rank), min(int(rank) + 1, len(ordered) - 1)
    frac = rank - lo
    return ordered[lo] + (ordered[hi] - ordered[lo]) * frac


@dataclass
class DbTarget:
    host: str
    port: int
    dbname: str
    user: str
    password: str

    def connect(self) -> psycopg.Connection:
        return psycopg.connect(
            host=self.host,
            port=self.port,
            dbname=self.dbname,
            user=self.user,
            password=self.password,
            autocommit=True,
        )


def crm_target() -> DbTarget:
    url = make_url(settings.database_url)
    return DbTarget(
        host=url.host or "localhost",
        port=url.port or 5433,
        dbname=url.database or "crm",
        user=url.username or "crm",
        password=url.password or "crm",
    )


def analytics_target(crm: DbTarget, user: str, password: str) -> DbTarget:
    # Same instance, different role -- see the module docstring for why this
    # is two connections rather than one.
    return DbTarget(
        host=crm.host, port=crm.port, dbname=crm.dbname, user=user, password=password
    )


# aggregate_id offset for synthetic rows, matching the convention
# OutboxConsumerIT already uses for its own throwaway fixtures -- so a stray
# benchmark row and a stray test row are recognizable by the same rule, and
# neither can collide with a real seeded deal (which stay well under this).
SYNTHETIC_ID_FLOOR = 900_000


def reset(crm: psycopg.Connection, analytics: psycopg.Connection) -> None:
    """Empties the outbox and the read model. Destructive by design -- see the
    module docstring for why this script requires --force."""
    crm.execute("TRUNCATE public.outbox_events RESTART IDENTITY CASCADE")
    analytics.execute(
        "TRUNCATE analytics.deal_projection, analytics.deal_stage_transition, "
        "analytics.activity_fact, analytics.processed_event, "
        "analytics.failed_event"
    )
    analytics.execute(
        "UPDATE analytics.consumer_offset SET floor_event_id = 0, updated_at = now() "
        "WHERE consumer = 'analytics'"
    )


def seed(crm: psycopg.Connection, count: int) -> float:
    """Inserts `count` synthetic deal.created rows in one INSERT, all sharing
    the same occurred_at -- a burst, the way a real spike in traffic would
    actually arrive, not a slow trickle that would flatter the lag numbers.

    Set-based (generate_series + jsonb_build_object), not `count` round trips
    from Python: 10,000 individual INSERTs would spend most of the benchmark's
    wall-clock time on network latency to Postgres, which is not what a
    consumer-lag number is supposed to measure.

    created_at/stage_changed_at are computed in Python and passed in as a
    literal string, not built with Postgres's now()::text: that produces
    "2026-09-08 04:31:53.423203+00" -- no "T", a 2-digit UTC offset -- which
    is valid Postgres output but not what Instant.parse on the Java side
    accepts. app.events.outbox._utc() calls dt.isoformat(), which is the
    format real payloads carry; matching it here means a payload shape bug in
    this script fails LOUDLY (a dead-lettered synthetic event) rather than
    quietly measuring a pipeline that isn't the real one.

    Relies on RESTART IDENTITY from `reset()` having just run, so the inserted
    rows are exactly ids [1, count] -- verified by the row count returned,
    not assumed silently.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    result = crm.execute(
        """
        INSERT INTO public.outbox_events
            (aggregate_type, aggregate_id, event_type, event_version, payload, occurred_at)
        SELECT
            'deal',
            %(floor)s + gs,
            'deal.created',
            1,
            jsonb_build_object(
                'deal_id', %(floor)s + gs,
                'name', 'Bench deal ' || gs,
                'stage', 'new',
                'value', '1000.00',
                'priority', NULL,
                'score', NULL,
                'expected_close_date', NULL,
                'company_id', 1,
                'company_name', 'Bench Co',
                'company_industry', NULL,
                'owner_id', 1,
                'owner_email', 'bench@demo.com',
                'owner_name', 'Bench Owner',
                'primary_contact_id', NULL,
                'primary_contact_name', NULL,
                'created_at', %(now_iso)s::text,
                'stage_changed_at', %(now_iso)s::text
            ),
            now()
        FROM generate_series(1, %(count)s) AS gs
        RETURNING id, occurred_at
        """,
        {"floor": SYNTHETIC_ID_FLOOR, "count": count, "now_iso": now_iso},
    )
    rows = result.fetchall()
    if len(rows) != count:
        raise RuntimeError(f"expected to insert {count} rows, inserted {len(rows)}")
    ids = [r[0] for r in rows]
    if sorted(ids) != list(range(1, count + 1)):
        raise RuntimeError(
            "inserted ids were not a clean [1, count] range -- was reset() run "
            "first, and is anything else writing to outbox_events concurrently?"
        )
    # All rows share one occurred_at (same INSERT, same transaction), so any
    # row's value is the burst's start time.
    return rows[0][1].timestamp()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--count", type=int, default=10_000, help="events per burst")
    p.add_argument(
        "--force",
        action="store_true",
        help="required: this truncates the outbox and the analytics read model",
    )
    p.add_argument(
        "--analytics-user", default=os.environ.get("ANALYTICS_DB_USER", "analytics")
    )
    p.add_argument(
        "--analytics-password",
        default=os.environ.get("ANALYTICS_DB_PASSWORD", "analytics"),
    )
    p.add_argument(
        "--poll-every",
        type=float,
        default=0.25,
        help="how often this script checks processed_event's count (seconds)",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=600,
        help="give up waiting for a phase to finish after this many seconds",
    )
    p.add_argument(
        "--report",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "docs" / "benchmarks.md",
    )
    return p.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    if not args.force:
        print(
            "Refusing to run without --force: this truncates public.outbox_events "
            "and every analytics table. Run against a disposable stack -- see the "
            "module docstring.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    crm = crm_target()
    analytics = analytics_target(crm, args.analytics_user, args.analytics_password)

    with crm.connect() as crm_conn, analytics.connect() as analytics_conn:
        print(f"Resetting the outbox and read model at {crm.host}:{crm.port}/{crm.dbname}...")
        reset(crm_conn, analytics_conn)

        print(f"Seeding {args.count} synthetic deal.created events in one burst...")
        burst_at = seed(crm_conn, args.count)
        print(f"Seeded. Burst occurred_at = {time.strftime('%H:%M:%S', time.localtime(burst_at))}")
