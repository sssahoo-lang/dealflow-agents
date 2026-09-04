# DealFlow Agents — Milestone 2: Java analytics service

> **Status: steps 1–8 are done and shipped. Only step 9 remains (README, contract
> tests asserted from both languages, retention note).** See "Build order" at the bottom for the
> per-step state, and "What actually shipped" immediately below for the places
> implementation diverged from or went beyond this plan.

## Context

Milestone 1 is **done, tested, and pushed** to github.com/sssahoo-lang/dealflow-agents (private):
a FastAPI + SQLAlchemy + Postgres CRM with JWT/RBAC and three LangGraph/Claude agents
(lead scoring, follow-up drafting, NL query). The Python suite has since grown from 38
to **125 tests**, still with no network calls and no API key required. The Java service
adds **69** (38 unit, 31 integration).

Milestone 2 adds a **Java/Spring Boot analytics service** — a second service in a second
language, fed by a transactional outbox. Two reasons this earns its place rather than
being resume-padding:

1. Enterprise CRM backends really are Java/Spring, and heavy read-side analytics really
   is what gets split into its own service. This is a realistic polyglot boundary.
2. It forces the fix for the durability gap the Milestone 1 README already documents.
   A second *process* consuming events makes in-process pub/sub insufficient, so the
   outbox pattern stops being theoretical.

The service also pairs a **deterministic rules engine** with the existing LLM agents —
both consuming the same event stream. That contrast (a rule about the *absence* of
activity can't be event-triggered; it needs a scheduled sweep) is the sharpest
architectural story in the project.

**Decisions already fixed:** Docker-only Java (no JDK/Maven on the host);
Postgres outbox + Java polling (no Kafka, no broker, no Python→Java REST);
scope = analytics + rules engine.

---

## What actually shipped (steps 1–3)

The design below held up — the outbox schema, the `flush → record → commit` ordering, the
money-as-string and denormalisation rules, and the "no status column" decision all went in
as written. Five things are worth recording because they were **decided during
implementation**, not in this plan:

**An `LLM_PROVIDER` switch, so the repo runs with no API key.** `stub` (the default) is a
rule-based stand-in; `anthropic` is real Claude. This was not part of the original plan but
it changes the project's economics: anyone can clone and run the full system, and CI needs
no secret. It also means the Java service's future CI can exercise the Python stack for free.

**Agent-written activities deliberately stay out of the event stream.** The agents write
their reasoning notes and drafts straight to the `activities` table inside their graphs, so
they never reach `activity.created`. This is correct — an agent scoring a deal is not contact
with the customer, and counting it would stop the planned "no touchpoint in 14 days" rule
from ever firing on a genuinely stale deal. It was originally an accident of where the
writes happen; it is now documented in `app/events/schemas.py` and pinned by a test.

**`Deal.owner` relationship added.** Needed to denormalise `owner_email` / `owner_name` into
the payload. No schema change — `owner_id` already existed.

**Snapshots use their own event types** (`deal.snapshot`, not `deal.created`), so a consumer
can distinguish "current state as of the backfill" from "a change that happened". The
backfill also skips any aggregate that already has an outbox row, so a deal created after
the outbox shipped is never double-counted in a projection.

**Two bugs found by the new tests, both fixed:**
- The NL query agent returned HTTP 200 with an **empty answer string** when it hit
  `MAX_TOOL_ROUNDS` — the last message on that path is a tool call, whose content is `""`.
  It now reports the limit it hit.
- `conftest.py` could hang indefinitely: `DROP DATABASE` blocks on any other open
  connection, so a leftover dev server turned `pytest` into a silent stall (one run took
  26 minutes instead of 6 seconds). The fixture now terminates other `crm_test` backends
  first.

**One environment note for step 8:** the Docker VM clock was observed running ~72s behind
the host. Harmless so far — `occurred_at` is server-set, and tests compare against the
database clock — but it is direct evidence that the injected-`Clock` and duration-based
comparison prescribed for the rules engine are necessary rather than theoretical.

---

## 1. Outbox (Python side) — ✅ built

New `app/models/outbox.py` → table `outbox_events`:

| column | type | notes |
|---|---|---|
| `id` | BIGSERIAL PK | assignment order ≠ visibility order — see §2 |
| `aggregate_type` / `aggregate_id` | VARCHAR(50) / BIGINT | `deal`, `contact`, `activity` |
| `event_type` | VARCHAR(80) | `deal.created`, `deal.stage_changed`, `activity.created`, `*.snapshot` |
| `event_version` | SMALLINT default 1 | contract version |
| `payload` | JSONB | the `data` block |
| `occurred_at` | **TIMESTAMPTZ** | deliberately tz-aware, unlike the legacy columns |

**No `status`/`processed_at` columns.** The outbox is an append-only log owned by Python;
consumer progress lives in the consumer's schema. That's what lets the Java role be
`SELECT`-only, which is the whole answer to the shared-database concern.

**Two contract rules:** money is a **JSON string** (`"75000.00"` → `new BigDecimal(String)`;
a float round-trip silently corrupts money), and `owner_email` / `owner_name` /
`company_name` are **denormalized into the payload** so Java can render a leaderboard
without ever touching `users` or `companies`.

### The refactor

`app/events/outbox.py` provides `to_envelope(db, event)` and `record(db, event)`.
The frozen dataclasses in `app/events/schemas.py` stay the single definition of an event;
`to_envelope` re-reads the aggregate from the session to build the richer payload, so the
dataclasses are untouched and `test_event_bus.py` doesn't move.

```python
def create_deal(db, user, payload):
    deal = Deal(**payload.model_dump(), owner_id=user.id)
    db.add(deal)
    db.flush()                 # NEW: assigns deal.id, no commit
    event = DealCreated(...)
    outbox.record(db, event)   # NEW: same transaction as the INSERT
    db.commit()
    return deal, event
```

Same three-line treatment in `update_deal`, `create_contact`, `create_activity`.
**Routes are unchanged** — they keep `tasks.add_task(event_bus.publish, event)`.

**The in-process bus stays.** It is not a dual write: the outbox row is the only durable
record, the bus is best-effort in-process notification for one consumer (lead scoring).
Losing a publish loses an LLM call, not an event. Replacing it means writing a second
(Python) poller — a separate milestone. The README claim gets scoped honestly:
*analytics is exactly-once-effect; lead scoring is best-effort.*

`scripts/backfill_outbox.py` emits `*.snapshot` rows for existing data so Java can
bootstrap; rerunnable via `WHERE NOT EXISTS`.

**Test impact: zero existing tests change.** `conftest.py` auto-creates and auto-truncates
any model registered on `Base`. *(Confirmed in practice — all 86 pre-existing tests passed
with no test file edited. `tests/test_outbox.py` added 20 tests, `tests/test_backfill.py`
another 11.)*

---

## 2. Consumption, offsets, idempotency — ✅ built

**The trap:** BIGSERIAL ids are assigned at INSERT but visible at COMMIT. Txn A takes id
100, txn B takes 101 and commits first; a poller storing `last_seen = 101` **never sees
100**. Silent, and it manifests as a leaderboard that's quietly 0.3% wrong.

**The fix — anti-join against a ledger, not a watermark.** Java owns
`analytics.processed_event` (event_id PK, status done|dead, attempts),
`analytics.failed_event` (in-flight retries with backoff), and
`analytics.consumer_offset` (a `floor_event_id` that is a pure optimization —
correctness never depends on it).

```sql
SELECT e.* FROM public.outbox_events e
LEFT JOIN analytics.processed_event p ON p.event_id = e.id
LEFT JOIN analytics.failed_event    f ON f.event_id = e.id
WHERE e.id > :floor AND p.event_id IS NULL
  AND (f.event_id IS NULL OR f.next_attempt_at <= now())
ORDER BY e.id LIMIT :batch;
```

An event is unprocessed iff it has no ledger row — correct regardless of commit ordering.
This query is why both tables must live in one database (§3).

**Idempotency, three layers:** the ledger PK; one transaction per event (projection write
+ ledger insert commit together); and facts that are naturally idempotent
(`UNIQUE(event_id)`, `ON CONFLICT DO NOTHING`). `deal_projection.last_event_id` guards
replay *and* out-of-order arrival.

**Poison events:** exponential backoff, then `status='dead'` after 5 attempts, logged and
exposed at `GET /admin/outbox/status`. A failed event **aborts the rest of the batch** —
per-deal ordering matters, and head-of-line blocking is loud where silent reordering
isn't. Unknown `event_type` is *not* poison: WARN and mark done, so Python can add event
types without bricking the consumer.

---

## 3. Database ownership — ✅ built

**Separate schema `analytics`, same `crm` database, separate Postgres role.**
Not a separate database — the anti-join above needs one joinable transaction.

This *is* the shared-database anti-pattern in the strict sense. What makes it defensible:
Java reads exactly **one** table, `public.outbox_events`, which is a published versioned
contract, not an internal table — and that's enforced by **grants, not convention**:

```sql
has_table_privilege('analytics','public.deals','SELECT')          -- false
has_table_privilege('analytics','public.outbox_events','SELECT')  -- true
has_table_privilege('analytics','public.outbox_events','UPDATE')  -- false
```

Those three assertions become a Java integration test so the invariant can't rot.
Residual and named in the README: Python can still break Java by changing the payload
shape (mitigated by `event_version` + shared JSON fixtures asserted from *both* sides),
and the two services share one Postgres instance's resources.

Role provisioned by `db/init/01-analytics-role.sql`, with `statement_timeout=10s` and a
small Hikari pool. **Gotcha:** `/docker-entrypoint-initdb.d` only runs on an empty data
directory, and `pgdata` is already populated — so either `docker compose down -v` or
apply the SQL once by hand. Both go in the README.

**Flyway** for the Java schema (plain versioned SQL, same mental model as Alembic) with
`ddl-auto: validate`, so entity/schema drift is a startup failure rather than a runtime
surprise. Liquibase and `ddl-auto=update` both rejected.

---

## 4. The Java service — ✅ built

**Java 21 + Spring Boot 3.4.x**, Maven, multi-stage Dockerfile (Maven build stage → slim
JRE runtime). No `spring-boot-starter-security` — a ~60-line `OncePerRequestFilter` beats
pulling in the whole filter chain to do one HMAC check. `jjwt` over
`oauth2-resource-server` (that one is built for JWKS/RS256).

```
analytics-service/src/main/java/com/dealflow/analytics/
  outbox/     OutboxPoller (@Scheduled fixedDelay), OutboxDispatcher (per-event
              REQUIRES_NEW tx), handler/ (one EventHandler per event type)
  projection/ DealProjection, DealStageTransition, ActivityFact
  analytics/  Leaderboard/Conversion/Velocity/Forecast services + controller
  rules/      Condition (sealed interface), RuleEvaluator (pure, takes a Clock),
              RuleEngine, RuleScheduler, RulesController
  security/   JwtAuthFilter, Principal
```

### Read model — no counters, ever

`deal_projection`, `deal_stage_transition`, `activity_fact`, `stage_probability`.
Leaderboards, conversion, velocity and forecast are **computed by SQL on each request**
over immutable facts. This is the real answer to double-counting: there is nothing to
double count, and the whole read model can be dropped and rebuilt by replaying the outbox.

### Rules engine — rules are data, not code

`rule_definition.condition` is a JSONB tree parsed into a sealed `Condition` hierarchy:

```json
{"all":[{"field":"stage","op":"eq","value":"negotiation"},
        {"field":"days_since_last_activity","op":"gte","value":14}]}
```

Seeded rules: `stale_negotiation`, `high_value_needs_attention`, `close_date_slipped`.

- **Fails closed** — unknown field means the rule does not fire, logged at ERROR. Never
  fail open on a rules engine.
- Null semantics defined explicitly (every operator against a null fact is false except
  `is_null`), documented and asserted — this is where rules engines get subtly wrong.
- Findings have an **open/resolved lifecycle** with a partial unique index
  (`WHERE status='open'`), so the hourly sweep *reconciles* rather than appending 24
  rows/day/deal.
- Drools rejected (a KIE runtime for three rules); SpEL rejected (arbitrary expression
  evaluation is an injection surface once rules are editable via `PATCH /rules/{id}`).
- **Hourly cron, not event-driven** — a rule about the *absence* of activity has no
  triggering event. Worth calling out in the README.

### API (port 8081, direct — no Python proxy)

`GET /analytics/{leaderboard,conversion,velocity,forecast}`, `GET/PATCH /rules`,
`POST /rules/run`, `GET /rules/findings`, `GET /admin/outbox/status`, `/actuator/health`.
Money serializes as strings throughout.

**Auth:** Java validates the *same* HS256 JWT with the shared `JWT_SECRET`. Requires one
small backwards-compatible Python change — add `uid` and `role` claims in
`create_access_token`, since Java has no `users` table and can't resolve email → id/role.
`decode_access_token` still reads `sub`, so no Python behavior or test changes.

Tradeoffs stated plainly in the README: a symmetric secret means a compromised analytics
service could **forge an admin token** for the CRM; rotation is coordinated; Java can't
see `is_active` so a deactivated user works until token expiry (currently 24h). Accepted
for a read-only surface, with a concrete migration path documented (RS256 + JWKS,
~40 lines each side).

Rep-vs-admin scoping is an **explicit parameter on every repository method**, never a
global filter that can be forgotten.

---

## 5. docker-compose — ✅ built

Four services: `db` (+ `TZ=UTC`, `PGTZ=UTC`, init scripts), a one-shot **`migrate`**
service running `alembic upgrade head`, `api` (the Python app, containerized), and
`analytics`. Both `api` and `analytics` depend on `migrate` with
`condition: service_completed_successfully` — cleaner than coupling the analytics boot to
the API boot.

Containerizing Python is new, but **the existing host workflow keeps working unchanged**:
`db` still publishes 5433, so `.env`, `alembic`, `seed.py` and `pytest` from `.venv` are
untouched. This adds a second way in, it doesn't replace the current one.

---

## 6. Testing

**Java unit tests** (no Docker, no Spring context) carry most of the value: every operator
and type in `RuleEvaluator`, boolean composition, null semantics, fail-closed on unknown
fields, and **`Clock.fixed` boundary tests** for the 14-day rule (exactly 14d fires,
13h59m doesn't) — tests that only exist because `Clock` is injected.

**Java integration tests** run against the compose `db`, not Testcontainers by default —
`docker build` has no daemon, so Testcontainers would need a socket mount (root-equivalent
host access). Instead: `docker compose --profile test run --rm analytics-test` against a
`crm_java_test` database **migrated by Alembic itself**, so there's one source of DDL
truth. Testcontainers stays behind a Maven profile for CI runners that have a daemon.

Coverage: poller end-to-end, idempotency (same batch twice → identical totals),
out-of-order guard, poison → dead-letter → next event still processes, the three grant
assertions, and JWT valid/expired/wrong-secret/rep-scoping.

**Python:** `tests/test_outbox.py` — payload matches the shared contract fixture key-for-
key, `value` is a 2-dp string, `PATCH` without a stage change writes zero rows, backfill is
idempotent, and an **atomicity test** proving a failure in `record()` rolls back the deal.

No test path needs `ANTHROPIC_API_KEY`; the Java service never calls an LLM.

---

## 7. Risks worth knowing

- **Clock/timezone is the sharpest edge.** Existing `created_at` columns are `timestamp
  WITHOUT time zone` and only store UTC by accident of the postgres image default. Fix:
  explicit `TZ`/`PGTZ`, `TIMESTAMPTZ` on the outbox, Python attaches UTC explicitly when
  serializing, Java uses `Instant` never `LocalDateTime`, and "14 days" is an elapsed
  `Duration` (DST-immune) rather than `LocalDate.minusDays(14)`.
- **Enum coupling** — adding `DealStage.on_hold` in Python would make Java's
  `Enum.valueOf` dead-letter every event for that deal. Fix: `fromWire()` with an
  `UNKNOWN` fallback; projections store stage as TEXT.
- **Unbounded outbox growth** — retention job must never prune above the *minimum* floor
  across consumers, or a future second consumer starts with a hole. Cheap now, dangerous
  to retrofit.
- **Polling latency** (~2s) is fine: human-read dashboards, and the rules sweep is hourly
  anyway. `LISTEN/NOTIFY` explicitly rejected — it only reaches connected listeners, so a
  polling backstop is still required; pure added complexity.

---

## 8. Build order

Each step ends green before the next starts.

**Done — the Python half. No Java required for any of these.**

1. ✅ **Outbox model + migration.** `outbox_events` created; migration verified to
   round-trip (`downgrade` drops cleanly, `upgrade` recreates). No test files needed
   editing — `conftest` creates and truncates anything registered on `Base`.
   Commit `01cd5a7`. → 86 tests.
2. ✅ **`events/outbox.py` + service refactor.** All 86 pre-existing tests passed with
   *zero test files edited*, which is the evidence the refactor is transparent. Then
   `tests/test_outbox.py` added, including atomicity in both directions. Verified live:
   create + stage-change + rename produced exactly two rows, `"250000.55"` intact.
   Commit `86b3f52`. → 99 tests.
3. ✅ **JWT claims + backfill script.** `uid`/`role` added as optional claims (Python
   still authenticates off `sub`, so nothing moved). Backfill verified rerunnable:
   dry-run wrote nothing, first run wrote 10 rows, second was a no-op, and a deal with a
   real `deal.created` was skipped. Commit `e29217b`. → **110 tests.**

**Not started — the Java service.** Every step below needs the Docker-based Java
toolchain, which is a fresh setup (no JDK or Maven on the host by design).

4. ✅ **DB role + Python container + compose skeleton.** analytics role verified
   live: reads the outbox, refused on deals, refused on writing the outbox, owns its
   own schema. Deviation: the grant went in a *new* migration rather than editing the
   applied one, which would never have re-run. Commit `1c12247`.
5. ✅ **Java skeleton.** Flyway builds 11 tables, actuator healthcheck, JWT filter
   verifying Python-minted tokens. Found a real cross-language break: the 23-byte
   default secret worked in python-jose but jjwt enforces RFC 7518's 256-bit floor and
   refused to boot. Fixed on both sides. Commit `4152726`.
6. ✅ **Poller + projection handlers.** Anti-join consumer (not a watermark),
   per-event transactions, backoff then dead-letter, `last_event_id` guard. Replay of
   all events proved idempotent. Deviation: JDBC instead of JPA/`ddl-auto:validate` --
   every write is a guarded upsert and every read an aggregate, so there were no entity
   graphs to justify Hibernate. Fixed a floor-unaware `/admin/outbox/status` that
   reported a caught-up consumer as 14 events behind. Commit `0779150`.
7. ✅ **Analytics queries + controllers.** Four read-time aggregates, scoping decided
   once in the controller and passed down explicitly. Verified live: admin sees all
   reps, each rep sees only their own row. Three bugs surfaced: an uninferable NULL
   bind broke every admin query, `builder.modules()` clobbered Jackson's JavaTimeModule
   and 500'd anything returning an Instant, and the funnel's ordinal-reach semantics
   needed documenting (a won deal counts at every rung below it, which is what keeps
   conversion rates under 100%). Commits `0e64d0d`, `48a803b`.

<details><summary>original step 4-7 wording</summary>

4. ⬜ **DB role + Python container + compose skeleton** → `/health` responds; `\dn` shows `analytics`; the three grant checks return false/true/false.
5. ⬜ **Java skeleton** (Dockerfile, pom, Flyway V1/V2, actuator, JWT filter) → `/actuator/health` UP; no token → 401, Python-issued token → 200.
6. ⬜ **Poller + projection handlers** → create a deal, 3s later `analytics.deal_projection` has the row; IT suite green.
7. ⬜ **Analytics queries + controllers** → all four endpoints sane; rep sees own row, admin sees all.
8. ✅ **Rules engine + scheduler + findings.** JSON condition trees, a pure evaluator,
   injected `Clock` (14-day boundary tested exactly), hourly sweep. Verified live:
   repeated sweeps left the finding count unchanged, and logging activity resolved two
   findings on the next pass. Two bugs fixed -- `Map.of` rejecting the null that clears
   a validation error (NPE surfacing as "Invalid condition: null"), and the jsonb
   `detail` leaking the driver's PGobject wrapper into the API. Commit `6e9760b`.
9. ⬜ **README, contract tests both sides, retention note** → clean `down -v && up` passes the full E2E script.

</details>

**Picking this up again:** step 4 is the natural entry point, and the first real decision
is the one flagged in §5 — whether `analytics` depends on `api` being healthy, or whether
to extract a one-shot `migrate` service that both depend on. The latter is cleaner and is
what §5 recommends.

### Verification highlight

The proof worth keeping in the README permanently — one command showing redelivery cannot
corrupt the read model:

```bash
curl -s localhost:8081/analytics/leaderboard -H "Authorization: Bearer $TOKEN" > /tmp/before.json
docker compose exec -T db psql -U crm -d crm -c \
  "TRUNCATE analytics.processed_event; UPDATE analytics.consumer_offset SET floor_event_id=0;"
sleep 6
curl -s localhost:8081/analytics/leaderboard -H "Authorization: Bearer $TOKEN" > /tmp/after.json
diff /tmp/before.json /tmp/after.json && echo "IDEMPOTENT"
```

Plus: `pytest -q` → **125 passed** (no API key) and
`docker compose --profile test run --rm analytics-test` for the Java suite.

---

## Critical files

**Built (steps 1–3):**
- `app/models/outbox.py`, `app/events/outbox.py` — the contract boundary
- `app/services/deal_service.py`, `app/services/crm_service.py` — `flush()` → `record()` → `commit()`
- `app/core/security.py` — `uid`/`role` claims
- `scripts/backfill_outbox.py` — rerunnable snapshot emitter
- `contracts/events/deal.created.v1.json` — asserted from Python today, from Java at step 9
- `tests/test_outbox.py`, `tests/test_backfill.py`, `tests/test_deal_events.py` — the safety net

**Still to build (steps 4–9):**
- `db/init/01-analytics-role.sql` — the `SELECT`-only role
- `docker-compose.yml` — migrate/api/analytics services
- `analytics-service/` — the whole Java module
