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
    print(f"(scaffold) would benchmark {args.count} events; phases not yet implemented")
