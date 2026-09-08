# Design decisions

The README keeps things simple on purpose. This file has the longer version —
why the system is built the way it is, written for anyone who wants to dig in
(a reviewer, an interviewer, or future me). Each section stands alone.

## The outbox: durability vs. immediacy

Every domain change writes an `outbox_events` row *in the same database
transaction* as the change itself, so the event and the change land together
or not at all — `tests/test_outbox.py` proves both directions. On top of
that, an in-process event bus fires a *second*, best-effort notification for
the lead-scoring agent: if the process dies before that notification runs,
it's lost, but the event is still durably on disk for a consumer to pick up
later. So: **analytics is exactly-once-effect; lead scoring is
best-effort.** That's a deliberate difference, not an oversight — analytics
needs to be provably correct, and a slightly-delayed lead score is a much
smaller problem than a wrong dashboard number.

The outbox table is deliberately append-only, with no `status` or
`processed_at` column. Consumer progress belongs to the consumer, tracked in
its own schema — that's what lets the Java service be granted `SELECT` and
nothing else on this table. A status column would force write access and
turn a published contract back into a shared mutable table.

Two payload rules that are easy to get wrong: **money crosses the wire as a
string** (`"75000.10"`), never a JSON number, because a float round-trip can
silently lose precision. And `owner_email` / `company_name` are
**denormalized into the payload**, so a consumer can render a rep leaderboard
without needing access to the `users` or `companies` tables.
`contracts/events/deal.created.v1.json` is asserted from **both** sides —
`tests/test_outbox.py` in Python and `EventContractTest` in Java read the
same file, so neither service can change the payload shape alone.

## Auth: a token that can be verified but not forged

The analytics service used to verify tokens with the same secret the CRM
signed with (HS256). That meant a read-only service could technically forge
an admin token for the CRM — which quietly undoes what its read-only
database access was supposed to guarantee.

It now signs with RS256 instead: the CRM holds a private key and publishes
the matching public key at `/.well-known/jwks.json`. The analytics service
fetches that public key and can verify a token, but has no way to *create*
one. The gap is closed by the cryptography, not by a promise about the code.

Three details make key rotation actually work, not just look correct:

- The key's ID (`kid`) is a **thumbprint derived from the key itself**
  (RFC 7638), not something assigned by hand. Two independent
  implementations, in two languages, agree on a key's name without ever
  coordinating one.
- An unrecognized `kid` triggers **one refetch** of the public key. That's
  what makes rotation self-healing — restart the CRM (which generates a new
  key) and the Java service picks up the change on its own.
- That refetch is **rate-limited**, because the `kid` in a token is chosen by
  whoever sent it. Without a limit, a stream of bad tokens would turn every
  verification attempt into an outbound network call.

## Database access is enforced by Postgres, not by convention

The Java service connects with a dedicated `analytics` Postgres role that can
only `SELECT` from one table — `public.outbox_events` — and owns its own
separate `analytics` schema. It cannot read `deals`, `users`, `contacts`, or
`companies`, and cannot write to the outbox, even if its code tried to.
`tests/test_db_grants.py` checks this directly:

```sql
has_table_privilege('analytics','public.deals','SELECT')          -- false
has_table_privilege('analytics','public.outbox_events','SELECT')  -- true
has_table_privilege('analytics','public.outbox_events','UPDATE')  -- false
```

Sharing one Postgres instance between two services is, strictly speaking, an
anti-pattern. What makes it defensible here is that the shared surface is a
single append-only table with a versioned contract, not the CRM's internals
— and the boundary is enforced by database grants, not just good intentions.
The remaining coupling is real, though: Python could still break Java by
changing the payload shape, which is exactly what `event_version` and the
shared contract fixtures exist to catch.

## The consumer tracks a ledger, not a "last seen" number

Postgres assigns row IDs when a transaction starts (`INSERT`), but they only
become visible when it finishes (`COMMIT`). So it's possible for one
transaction to grab ID 100 and a slightly later one to grab ID 101 — and for
101 to commit *first*. A consumer that just remembers "the highest ID I've
seen" would jump straight to 101, and permanently miss 100. No error,
nothing crashes — it just silently shows up later as a leaderboard number
that's a little bit wrong.

The fix: instead of remembering a single number, the consumer keeps a table
of every ID it has already processed, and asks "which rows in the outbox
have no matching row here?" That question gives the right answer no matter
what order transactions happen to commit in.

## No counters in the read model

Every fact in the analytics database is an immutable row that records which
event produced it. Nothing is ever incremented in place. That's what makes
redelivery harmless — if the same event arrives twice, there's nothing to
double-count — and it means the entire analytics database can be safely
deleted and rebuilt from scratch just by replaying the event log.

## Rules are data, not code

A rule (like "flag deals that have gone quiet") is stored as a small JSON
tree, not as a hardcoded `if` statement, so it can be changed through the API
with no code deploy. Two behaviors worth knowing about: a rule **fails
closed** — if it references a field that doesn't exist, it turns itself off
and records why, rather than accidentally matching everything. And comparing
against a missing value is **false for every check except "is missing"** —
including "not equal to," which can read as though a missing value should
count as a match, but doesn't.

## Tracing across two services and two languages

There's no direct function call between "the CRM wrote a deal" and "the Java
service applied it to the analytics database" — they're connected only
through a database table, read up to a couple of seconds later, in a
different process, in a different language. Normal tracing tools can't
follow a request across a gap like that automatically.

So the two sides do it by hand: when the CRM writes an outbox row, it also
saves its current trace ID onto that row. When the Java service later reads
that row, it looks up the trace ID and continues the *same* trace instead of
starting a new, disconnected one. The result: opening Jaeger after creating
a deal shows one continuous timeline — the API request, then a gap, then the
Java service picking the work back up — instead of two traces that just
happen to be about the same deal.

This is opt-in and off by default, for the same reason the LLM is stubbed by
default: the test suite and CI shouldn't need a network call or an external
service to pass. `docker compose up` turns it on automatically; a plain
`pytest` run never touches it.
