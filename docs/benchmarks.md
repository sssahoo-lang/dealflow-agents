## Outbox consumer lag

Run 2026-09-08 against a stock `docker compose up` on a single developer
laptop -- Postgres, the CRM, and the analytics service all sharing one
machine's CPU, not isolated benchmarking hardware. Not a claim about a
production deployment's absolute throughput; a real, reproducible reading of
*this pipeline's own bottleneck* (poll cadence and batch size, not per-event
work -- see below), which holds regardless of what hardware it's run on.

Measured against a burst of 10,000 synthetic `deal.created` events, all
sharing one `occurred_at`, against the consumer as configured
(`poll-interval-ms=2000`, `batch-size=200` --
100 events/s sustained throughput at that config).
Reproduce with `python scripts/bench_outbox_lag.py --count 10000 --force`
against a disposable stack.

| Metric | Value |
|---|---|
| Events | 10,000 |
| p50 consumer lag | 55.18s |
| p99 consumer lag | 110.19s |
| Max consumer lag | 110.33s |
| Full read-model rebuild (10,000 events) | 111.53s |

**Reading these numbers:** lag is dominated by queue position, not per-event
cost -- an event seeded near the end of the burst waits through every poll
tick ahead of it before its batch comes up, which is why p99 is a multiple of
p50 rather than close to it. The fix for a lower p99 under sustained load is
`ANALYTICS_OUTBOX_POLL_INTERVAL_MS` and `batch-size`, not code -- both are
config, not constants (see application.yml).

Rebuild time is bounded by the same two knobs from a cold start (queue depth
0, so no polling latency to hide behind) -- it's a direct read on raw
insert-and-project throughput, which is why it lands close to
`count / events_per_poll` above.
