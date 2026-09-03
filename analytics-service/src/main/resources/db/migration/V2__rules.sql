-- The deterministic rules engine.
--
-- Rules are DATA, not code: a rule is a JSON condition tree evaluated against
-- facts drawn from deal_projection. That means a rule can be enabled, disabled,
-- or retuned through the API without a redeploy, and the evaluator can be unit
-- tested as a pure function.
--
-- The contrast with the LLM agents is the point of this whole service: a rule
-- about the ABSENCE of activity has no triggering event, so it cannot be
-- event-driven. It needs a scheduled sweep.

CREATE TABLE rule_definition (
    id          BIGSERIAL PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    description TEXT,
    severity    TEXT NOT NULL CHECK (severity IN ('info', 'warn', 'critical')),
    condition   JSONB NOT NULL,
    enabled     BOOLEAN NOT NULL DEFAULT true,
    -- Surfaced through the API so "why didn't my rule fire?" is answerable
    -- without log archaeology.
    last_validation_error TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE rule_finding (
    id          BIGSERIAL PRIMARY KEY,
    rule_id     BIGINT NOT NULL REFERENCES rule_definition(id),
    deal_id     BIGINT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('open', 'resolved')),
    opened_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ,
    detail      JSONB
);

-- The engine RECONCILES rather than appends: without this partial unique index
-- an hourly sweep would create 24 findings a day for the same stuck deal.
CREATE UNIQUE INDEX uq_open_finding
    ON rule_finding (rule_id, deal_id)
    WHERE status = 'open';

CREATE INDEX ix_finding_deal ON rule_finding (deal_id);

-- Answers "did the sweep actually run?" without reading logs.
CREATE TABLE rule_run (
    id              BIGSERIAL PRIMARY KEY,
    rule_id         BIGINT REFERENCES rule_definition(id),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    evaluated_count INT NOT NULL DEFAULT 0,
    opened_count    INT NOT NULL DEFAULT 0,
    resolved_count  INT NOT NULL DEFAULT 0,
    error           TEXT
);

CREATE INDEX ix_rule_run_started ON rule_run (started_at DESC);

-- Seeded as migrations so a fresh `docker compose up` is immediately demonstrable.
INSERT INTO rule_definition (code, name, description, severity, condition) VALUES
(
    'stale_negotiation',
    'Stale negotiation',
    'A deal in negotiation with no touchpoint for two weeks is going cold.',
    'warn',
    '{"all": [
        {"field": "stage", "op": "eq", "value": "negotiation"},
        {"field": "days_since_last_activity", "op": "gte", "value": 14}
     ]}'::jsonb
),
(
    'high_value_needs_attention',
    'High-value deal needs attention',
    'Large open deals should not go a week without contact.',
    'critical',
    '{"all": [
        {"field": "value", "op": "gte", "value": 100000},
        {"field": "days_since_last_activity", "op": "gte", "value": 7},
        {"field": "stage", "op": "in", "value": ["qualified", "proposal", "negotiation"]}
     ]}'::jsonb
),
(
    'close_date_slipped',
    'Close date slipped',
    'The expected close date has passed but the deal is still open.',
    'warn',
    '{"all": [
        {"field": "expected_close_date_days_remaining", "op": "lt", "value": 0},
        {"field": "stage", "op": "not_in", "value": ["won", "lost"]}
     ]}'::jsonb
);
