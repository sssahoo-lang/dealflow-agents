# DealFlow Agents

Two services around one event stream. A **Python/FastAPI** sales CRM with three
LangGraph agents, and a **Java/Spring Boot** analytics service with a deterministic
rules engine — connected by a transactional outbox, not by an API call between them.

The interesting part is the contrast: the agents react to events as they arrive, while
the rules engine sweeps on a schedule, because a rule about the *absence* of activity
has no event to trigger it.

## What it does

**CRM core** — companies, contacts, deals, and activities, with JWT auth and two roles.
Reps see and act on only their own records; admins see everything. Pipeline transitions
are stage-aware: a rep can advance a deal freely, but only an admin can close it as
`won` or `lost`.

**Agent layer** — three agents, each a different agentic pattern:

| Agent | Trigger | Pattern |
|---|---|---|
| **Lead scoring** | Event (`DealCreated`) | Linear graph with a conditional branch |
| **Follow-up drafting** | `POST /agents/follow-up` | Linear graph, human-in-the-loop output |
| **NL query** | `POST /agents/query` | Tool-calling loop over read-only tools |

**Analytics service (Java)** — a second service in a second language, fed by the outbox.
It cannot call the CRM and cannot read its tables; it consumes events and builds its own
read model.

| Surface | What it does |
|---|---|
| `GET /analytics/leaderboard` | Wins, losses, open value and win rate per rep |
| `GET /analytics/conversion` | Stage-by-stage funnel |
| `GET /analytics/velocity` | Days spent per stage (avg and median) |
| `GET /analytics/forecast` | Pipeline weighted by stage probability |
| `GET/PATCH /rules`, `POST /rules/run`, `GET /rules/findings` | Deterministic rules engine |
| `GET /admin/outbox/status` | Consumer lag, dead letters, pending count |

## Architecture

```
                    ┌─ one transaction ──────────────┐
POST /deals ──► deal_service ──► INSERT deal         │
                    │            INSERT outbox_event │──► commit
                    └────────────────────────────────┘        │
                                                              ├──► outbox_events ──┐
                                                              │    (durable log)    │
                                                              │                     ▼
                                                              │        Java analytics service
                                                              │        polls ──► projections
                                                              │                ──► rules sweep
                                                              │
                                            BackgroundTasks ──┴──► EventBus
                                                                     │
                                                             DealCreated
                                                                     │
                                                                     ▼
                                                lead_scoring graph (LangGraph)
                                      fetch_context → score_lead → [≥80?] → persist
```

The deal and its event commit **together** — neither can exist without the other. The
in-process bus fires only *after* that commit, so agents never react to state that might
roll back, and it runs through `BackgroundTasks` so a multi-second LLM call never delays
the HTTP response.

### Design decisions

**Transactional outbox for durability; in-process bus for immediacy.** Every domain
change writes an `outbox_events` row *in the same transaction* as the change itself, so
the event and the change land together or not at all — `tests/test_outbox.py` proves
both directions. The in-process bus is layered on top as a best-effort, low-latency
notification for the lead-scoring agent: if the process dies before the background task
runs, that publish is lost, but the event is still durably on disk for a consumer to
replay. Scoping matters here — **analytics is exactly-once-effect; lead scoring is
best-effort.**

The outbox table is deliberately append-only, with no `status`/`processed_at` column.
Consumer progress belongs to the consumer, tracked in its own schema — which is what
lets the Java service be granted `SELECT` and nothing else on this table. A
status column would force write access and turn a published contract back into a shared
mutable table.

Two payload rules, both easy to get wrong and expensive to undo: **money crosses the
wire as a string** (`"75000.10"`), never a JSON number, because a float round-trip
silently loses precision; and `owner_email` / `company_name` are **denormalised into the
payload** so a consumer can render a rep leaderboard without access to the `users` or
`companies` tables. `contracts/events/deal.created.v1.json` is asserted from **both** sides —
`tests/test_outbox.py` in Python and `EventContractTest` in Java read the same file, so
neither service can change the payload shape alone.

**The analytics service's access limits are enforced by Postgres, not convention.**
The Java service connects as a dedicated `analytics` role that can `SELECT`
exactly one table — `public.outbox_events`, the published contract — and owns its own
`analytics` schema. It cannot read `deals`, `users`, `contacts`, `companies` or
`activities`, and cannot write to the outbox, even if its code tried to.
`tests/test_db_grants.py` asserts all of that, so the invariant can't quietly rot:

```sql
has_table_privilege('analytics','public.deals','SELECT')          -- false
has_table_privilege('analytics','public.outbox_events','SELECT')  -- true
has_table_privilege('analytics','public.outbox_events','UPDATE')  -- false
```

Sharing one Postgres instance between two services *is* the shared-database
anti-pattern in the strict sense. What makes it defensible here is that the shared
surface is a single append-only, versioned contract table rather than the CRM's
internals — and that the boundary is enforced by grants rather than good intentions.
The residual coupling is real and worth naming: Python can still break Java by changing
the payload shape, which is what `event_version` and the shared contract fixtures exist
to catch.

**RBAC lives inside the agent's tools, not just the API layer.** The NL query agent
never sees or writes SQL. Each tool is a fixed SQLAlchemy `select()` with an allowlisted
set of filterable columns, a hard 50-row limit, and an ownership filter applied
server-side from the authenticated user. A confused or adversarially-prompted model
cannot widen its own access — `tests/test_agents/test_nl_query_tools.py` asserts this
directly.

**One LLM construction point.** Every model call goes through
`app/agents/llm.py::get_chat_model()`. Tests patch that one function, so the default
suite makes zero network calls and needs no API key — and swapping providers is a
config change, not a code change.

**Sync SQLAlchemy.** No concurrency requirement justifies async here, and it keeps
LangGraph nodes as plain functions.

**The consumer tracks a ledger, not a high-water mark.** `BIGSERIAL` ids are assigned at
`INSERT` but only become visible at `COMMIT`, so transaction A can take id 100 while B
takes 101 and commits first. A consumer storing `last_seen = 101` would *never* see event
100 — silently, showing up later as a leaderboard that is quietly a fraction of a percent
wrong. Progress is instead an anti-join against a table of processed ids: an event is
unprocessed iff it has no ledger row, which is correct regardless of commit order.

**No counters anywhere in the read model.** Facts are immutable rows carrying the id of
the event that produced them, and every aggregate is computed by SQL at read time. That
is what makes redelivery provably harmless — there is nothing to double count — and it
means the entire read model can be dropped and rebuilt by replaying the log.

**Rules are data, not code.** A rule is a JSON condition tree evaluated by a pure
function, so it can be retuned or disabled through the API with no redeploy. Two
semantics worth stating: it **fails closed** (an unknown field disables the rule with the
reason recorded, rather than firing on everything), and a comparison against a null fact
is **false for every operator except `is_null`** — including `!=`, which reads as though
absence should match. The `Clock` is injected, so the 14-day staleness boundary is tested
at exactly 14 days rather than approximately.

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # runs as-is; no API key required
docker compose up -d db
.venv/bin/alembic upgrade head
.venv/bin/python scripts/seed.py
.venv/bin/uvicorn app.main:app --reload
```

Swagger UI at http://localhost:8000/docs

### Or run the whole stack in Docker

```bash
docker compose up -d --build     # db → migrate (one-shot) → api
docker compose exec -T api python scripts/seed.py
```

`migrate` runs `alembic upgrade head` and exits; `api` waits for it to *complete*
(`service_completed_successfully`) rather than for another service to be healthy. The
host workflow above still works unchanged — `db` publishes 5433 either way, so `.venv`,
`alembic`, `pytest` and `seed.py` are unaffected. This adds a second way in, it doesn't
replace the first.

**Gotcha on an existing volume:** `db/init/` scripts run only when Postgres initialises
an *empty* data directory. If you already have a `pgdata` volume, the analytics role
won't be created automatically — apply it once by hand (the script is rerunnable):

```bash
docker compose exec -T db psql -U crm -d crm < db/init/01-analytics-role.sql
```

Seeded logins (all password `demo1234`): `admin@demo.com` (admin),
`rep@demo.com` (owns deals 1–2), `rep2@demo.com` (owns deal 3).

### LLM provider

`LLM_PROVIDER` selects what backs the agents:

| Value | Behavior |
|---|---|
| `stub` (default) | Deterministic, no API key, no network. Every endpoint, graph, tool call, and DB write runs for real. |
| `anthropic` | Real Claude calls. Requires `ANTHROPIC_API_KEY`. |

The stub is **not a language model and doesn't imitate one** — it's rule-based
(`app/agents/stub.py`). Lead scores come from a weighted heuristic over deal value,
contact seniority, activity count, and stage; the query agent routes to a tool by
keyword. What it exercises is the *system*: the event bus fires, the LangGraph state
machines execute their real conditional edges, the RBAC-scoped tools run real queries,
and the results are written to Postgres. What it can't demonstrate is judgment — the
rows the query agent returns are live, but the sentences around them are templated.
Set `LLM_PROVIDER=anthropic` for that.

This exists so the repo is runnable by anyone who clones it, and so CI needs no secret.

## Verifying it works

```bash
TOKEN=$(curl -s -X POST localhost:8000/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"rep@demo.com","password":"demo1234"}' | jq -r .access_token)

# RBAC: rep sees 2 deals, cannot close one
curl -s localhost:8000/deals -H "Authorization: Bearer $TOKEN"
curl -s -X PATCH localhost:8000/deals/1 -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"stage":"won"}'      # 403

# Agent 1: create a deal, wait, see score + reasoning appear
curl -s -X POST localhost:8000/deals -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name":"New opportunity","company_id":1,"value":75000}'
sleep 5
curl -s localhost:8000/deals/4 -H "Authorization: Bearer $TOKEN"        # score, priority
curl -s "localhost:8000/activities?deal_id=4" -H "Authorization: Bearer $TOKEN"

# Agent 2: draft a follow-up (saved as a draft, never sent)
curl -s -X POST localhost:8000/agents/follow-up -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"deal_id":1}'

# Agent 3: ask a question in natural language
curl -s -X POST localhost:8000/agents/query -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"question":"Which of my deals are worth the most?"}'
```

The outbox, verified against the database rather than through the API:

```bash
# A stage change writes an event; a rename does not.
curl -s -X PATCH localhost:8000/deals/1 -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"stage":"negotiation"}'
curl -s -X PATCH localhost:8000/deals/1 -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"name":"Renamed"}'

docker compose exec -T db psql -U crm -d crm -c \
  "SELECT id, event_type, aggregate_id, payload->>'value' AS value,
          payload->>'from_stage' AS from_stage, payload->>'to_stage' AS to_stage
     FROM outbox_events ORDER BY id;"
```

Backfilling aggregates that predate the outbox (rerunnable — a second run is a no-op):

```bash
.venv/bin/python scripts/backfill_outbox.py --dry-run
.venv/bin/python scripts/backfill_outbox.py
```

The Java service, consuming those same events:

```bash
# Wait ~2s for the poller, then see the projection it built
curl -s localhost:8081/analytics/leaderboard -H "Authorization: Bearer $TOKEN"
curl -s localhost:8081/analytics/forecast?horizonMonths=6 -H "Authorization: Bearer $TOKEN"
curl -s localhost:8081/admin/outbox/status -H "Authorization: Bearer $TOKEN"   # lag, dead letters
```

The rules engine. Age a deal into staleness, sweep, and watch the finding open — then
resolve itself once contact resumes:

```bash
docker compose exec -T db psql -U crm -d crm -c \
  "UPDATE analytics.deal_projection
      SET stage='negotiation', last_activity_at = now() - interval '21 days'
    WHERE deal_id = 1;"

curl -s -X POST localhost:8081/rules/run -H "Authorization: Bearer $TOKEN"
curl -s "localhost:8081/rules/findings?status=open" -H "Authorization: Bearer $TOKEN"

# Sweeping again does NOT duplicate the finding — the engine reconciles.
curl -s -X POST localhost:8081/rules/run -H "Authorization: Bearer $TOKEN"

# Log activity, sweep again, and it resolves.
docker compose exec -T db psql -U crm -d crm -c \
  "UPDATE analytics.deal_projection SET last_activity_at = now() WHERE deal_id = 1;"
curl -s -X POST localhost:8081/rules/run -H "Authorization: Bearer $TOKEN"
```

**The idempotency proof** — one command showing redelivery cannot corrupt the read model:

```bash
curl -s localhost:8081/analytics/leaderboard -H "Authorization: Bearer $TOKEN" > /tmp/before.json
docker compose exec -T db psql -U crm -d crm -c \
  "TRUNCATE analytics.processed_event; UPDATE analytics.consumer_offset SET floor_event_id = 0;"
sleep 8   # the poller replays every event from scratch
curl -s localhost:8081/analytics/leaderboard -H "Authorization: Bearer $TOKEN" > /tmp/after.json
diff /tmp/before.json /tmp/after.json && echo "IDEMPOTENT"
```

### Outbox retention

The outbox is append-only, so it needs pruning. One rule matters:

```bash
.venv/bin/python scripts/prune_outbox.py --dry-run
.venv/bin/python scripts/prune_outbox.py --older-than-days 30
```

**Never prune above the *minimum* floor across all consumers.** With one consumer that
looks trivial; add a second that is behind or stopped and pruning to the fastest one's
position silently deletes events the slower one has not read — a hole it can never
recover from, because the outbox is the only record. The script refuses to run when no
consumer is registered (an empty offset table means the consumer never started, not that
its work is done), and anything pruned can no longer be replayed, which is the real cost
of retention.

## Tests

```bash
.venv/bin/python -m pytest tests/ -q                       # 130, no network, no API key
docker compose --profile test run --rm analytics-test      # 77 Java (46 unit, 31 integration)
```

Both suites run without an API key. The Java suite runs inside the build stage, where
Maven and its dependency cache already live, against the real Postgres — so every
statement is exercised against the actual Flyway-built schema.

## Layout

```
app/
  models/      SQLAlchemy ORM — User, Company, Contact, Deal, Activity, OutboxEvent
  schemas/     Pydantic request/response models
  core/        security.py (JWT, bcrypt), rbac.py (role + stage rules)
  api/         deps.py (auth dependencies), routes/
  services/    business logic; returns (entity, event) so routes control publishing
  events/      bus.py, schemas.py, handlers.py, outbox.py (event -> row)
  agents/      llm.py (provider factory), stub.py, context.py, one package per agent
scripts/       seed.py, backfill_outbox.py, prune_outbox.py
contracts/     shared event fixtures, asserted from BOTH languages
tests/         130 tests; agent tests patch get_chat_model, never the network

analytics-service/           Java/Spring Boot, built by Maven inside Docker
  outbox/      poller, dispatcher, per-event-type handlers (the consumer)
  projection/  guarded upserts into the read model
  analytics/   the four read-time aggregates + controller
  rules/       condition tree, pure evaluator, engine, hourly scheduler
  security/    JwtAuthFilter — verifies the CRM's tokens, never mints them
  db/migration/  Flyway: V1 read model, V2 rules
```

## Known limitations

Named rather than hidden, because each is a deliberate trade:

**The shared JWT secret is symmetric.** The analytics service verifies the CRM's tokens
with the same HS256 key the CRM signs with, which means a compromise of the analytics
service could forge an admin token for the CRM. The fix is RS256 plus a JWKS endpoint —
roughly 40 lines on each side, deferred rather than overlooked. Note the two libraries
disagree on key strength: `python-jose` will sign with a short secret, `jjwt` enforces
RFC 7518's 256-bit floor, so both sides now validate the same minimum.

**Lead scoring is still best-effort.** The in-process bus can drop a publish if the
process dies before the background task runs. The event is durably in the outbox either
way, so nothing is lost — but the agent may not see it. The fix is a second (Python)
outbox consumer, at which point the bus and `BackgroundTasks` both go away.

**Two services, one Postgres instance.** Access is grant-enforced and the shared surface
is a single versioned contract table, but they still share the instance's resources.

**Not in scope:** frontend dashboard, email sending (the follow-up agent only drafts),
and multi-turn agent conversations.
