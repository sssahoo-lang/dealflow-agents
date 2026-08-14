# DealFlow Agents

A sales CRM backend with an autonomous agent layer. Real Postgres, real migrations,
role-based access control, an event-driven workflow engine, and three LangGraph agents
built on the Anthropic Claude API.

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

## Architecture

```
POST /deals ──► deal_service ──► commit ──► BackgroundTasks ──► EventBus
                                                                   │
                                                          DealCreated
                                                                   │
                                                                   ▼
                                              lead_scoring graph (LangGraph)
                                    fetch_context → score_lead → [≥80?] → persist
```

Events publish **after** commit, so agents only ever react to durable state, and they
publish through `BackgroundTasks` so a multi-second LLM call never delays the HTTP
response.

### Design decisions

**In-process event bus, not a queue.** ~30 lines, no broker, no persistence. This is a
deliberate simplification: if the process dies between commit and background execution,
the event is lost. The production fix is a transactional outbox table plus a polling
consumer. At this scale the bus buys decoupling and testability without the operational
weight of Celery or Kafka.

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

```bash
.venv/bin/python -m pytest tests/ -q    # 38 tests, mocked LLM, no network, no API key
```

## Layout

```
app/
  models/      SQLAlchemy ORM — User, Company, Contact, Deal, Activity
  schemas/     Pydantic request/response models
  core/        security.py (JWT, bcrypt), rbac.py (role + stage rules)
  api/         deps.py (auth dependencies), routes/
  services/    business logic; returns (entity, event) so routes control publishing
  events/      bus.py, schemas.py, handlers.py
  agents/      llm.py (single Claude factory), context.py, one package per agent
tests/         38 tests; agent tests patch get_chat_model, never the network
```

## Not in scope yet

Frontend dashboard, email sending (the follow-up agent only drafts), event durability,
and multi-turn agent conversations.
