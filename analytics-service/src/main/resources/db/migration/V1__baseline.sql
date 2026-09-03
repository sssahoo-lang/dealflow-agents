-- The analytics read model.
--
-- Design rule that everything else follows from: there are NO counter columns.
-- Nothing is ever incremented. Facts are immutable rows carrying the id of the
-- outbox event that produced them, and every aggregate (leaderboard, conversion,
-- velocity, forecast) is computed by SQL at read time.
--
-- That is what makes redelivery provably harmless: there is nothing to double
-- count. It also means the whole read model can be dropped and rebuilt by
-- replaying the outbox, which is a documented operation rather than a theory.

CREATE TABLE deal_projection (
    deal_id             BIGINT PRIMARY KEY,
    company_id          BIGINT,
    company_name        TEXT,
    owner_id            BIGINT NOT NULL,
    owner_email         TEXT,
    owner_name          TEXT,
    name                TEXT NOT NULL,
    -- TEXT, not an enum: the CRM can add a stage without this service needing a
    -- migration, and an unknown value must not dead-letter the whole stream.
    stage               TEXT NOT NULL,
    value               NUMERIC(12,2) NOT NULL DEFAULT 0,
    priority            TEXT,
    score               DOUBLE PRECISION,
    expected_close_date DATE,
    created_at          TIMESTAMPTZ NOT NULL,
    stage_changed_at    TIMESTAMPTZ NOT NULL,
    last_activity_at    TIMESTAMPTZ,
    -- Guards both replay and out-of-order arrival: an older event can never
    -- clobber a newer projection.
    last_event_id       BIGINT NOT NULL,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_deal_projection_owner ON deal_projection (owner_id);
CREATE INDEX ix_deal_projection_stage ON deal_projection (stage);

CREATE TABLE deal_stage_transition (
    id          BIGSERIAL PRIMARY KEY,
    deal_id     BIGINT NOT NULL,
    from_stage  TEXT,
    to_stage    TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    -- Idempotency: replaying an event cannot insert a second transition.
    event_id    BIGINT NOT NULL UNIQUE
);

CREATE INDEX ix_transition_deal ON deal_stage_transition (deal_id, occurred_at);

CREATE TABLE activity_fact (
    activity_id BIGINT PRIMARY KEY,
    deal_id     BIGINT,
    type        TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    event_id    BIGINT NOT NULL UNIQUE
);

CREATE INDEX ix_activity_fact_deal ON activity_fact (deal_id, occurred_at DESC);

-- Weights for the forecast. A table rather than constants so the assumption is
-- visible and adjustable without a redeploy.
CREATE TABLE stage_probability (
    stage       TEXT PRIMARY KEY,
    probability NUMERIC(4,3) NOT NULL
);

INSERT INTO stage_probability (stage, probability) VALUES
    ('new',         0.100),
    ('qualified',   0.250),
    ('proposal',    0.500),
    ('negotiation', 0.750),
    ('won',         1.000),
    ('lost',        0.000);

-- Consumer progress. Deliberately lives HERE, in the consumer's own schema,
-- rather than as a status column on public.outbox_events -- that is what lets
-- this service hold SELECT-only access to the CRM's log.
CREATE TABLE processed_event (
    event_id     BIGINT PRIMARY KEY,
    status       TEXT NOT NULL CHECK (status IN ('done', 'dead')),
    attempts     SMALLINT NOT NULL DEFAULT 1,
    last_error   TEXT,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE failed_event (
    event_id        BIGINT PRIMARY KEY,
    attempts        SMALLINT NOT NULL,
    last_error      TEXT,
    next_attempt_at TIMESTAMPTZ NOT NULL
);

-- floor_event_id is a pure optimisation that keeps the anti-join bounded.
-- Correctness never depends on it: an event is unprocessed iff it has no
-- processed_event row, not because its id exceeds a watermark.
CREATE TABLE consumer_offset (
    consumer       TEXT PRIMARY KEY,
    floor_event_id BIGINT NOT NULL DEFAULT 0,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO consumer_offset (consumer, floor_event_id) VALUES ('analytics', 0);
