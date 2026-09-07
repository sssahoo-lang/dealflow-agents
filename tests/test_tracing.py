"""Trace context propagation across the outbox -- the piece that lets a viewer
follow one deal from the FastAPI request that created it into the Java consumer
that later projects it.

The property under test is not "OpenTelemetry works" (that's the library's job).
It is the two decisions this codebase makes on top of it:

1. Tracing is off unless `OTEL_EXPORTER_OTLP_ENDPOINT` is set -- every other
   suite in this repo runs with no network calls, and this one must not be the
   exception.
2. When it *is* on, `outbox.record()` captures the current span's context onto
   the row, and only onto the row -- never into the payload, which is a
   versioned cross-language contract these tests must not perturb.
"""

from app.config import settings
from app.events.outbox import record
from app.events.schemas import DealCreated
from app.observability import tracing


def test_tracing_is_disabled_by_default():
    """The shipped default. A clone with no .env override gets no network calls."""
    assert settings.otel_exporter_otlp_endpoint == ""
    assert tracing.tracing_enabled() is False


def test_no_trace_context_is_recorded_when_tracing_is_disabled(db, crm_data, users):
    row = record(db, DealCreated(deal_id=crm_data["deal"].id, company_id=crm_data["company"].id, owner_id=users["rep"].id))

    assert row.trace_context is None


def test_no_trace_context_outside_any_span_even_when_enabled(monkeypatch, db, crm_data, users):
    """Enabling tracing must not manufacture a trace out of nothing -- a script
    with no active span (scripts/seed_demo.py, for instance) should still record
    NULL rather than a context pointing at an invalid, all-zero trace id."""
    monkeypatch.setattr(settings, "otel_exporter_otlp_endpoint", "http://jaeger:4318")

    row = record(db, DealCreated(deal_id=crm_data["deal"].id, company_id=crm_data["company"].id, owner_id=users["rep"].id))

    assert row.trace_context is None


def test_trace_context_is_captured_from_the_active_span(monkeypatch, db, crm_data, users):
    monkeypatch.setattr(settings, "otel_exporter_otlp_endpoint", "http://jaeger:4318")

    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    # A throwaway provider, scoped to this test: real exporter setup is
    # setup_tracing()'s job and is covered separately by not blowing up on
    # import. Here the only thing under test is that record() reaches for
    # whatever span is active and serialises it.
    tracer = TracerProvider().get_tracer("test")

    with tracer.start_as_current_span("test-request"):
        span = trace.get_current_span()
        expected_trace_id = format(span.get_span_context().trace_id, "032x")

        row = record(db, DealCreated(deal_id=crm_data["deal"].id, company_id=crm_data["company"].id, owner_id=users["rep"].id))

    assert row.trace_context is not None
    assert expected_trace_id in row.trace_context


def test_trace_context_never_lands_in_the_payload(monkeypatch, db, crm_data, users):
    """The payload is contracts/events/*.json, asserted from both languages.
    Trace plumbing riding in the payload would be a silent contract break the
    next time that fixture is regenerated."""
    monkeypatch.setattr(settings, "otel_exporter_otlp_endpoint", "http://jaeger:4318")

    from opentelemetry.sdk.trace import TracerProvider

    tracer = TracerProvider().get_tracer("test")

    with tracer.start_as_current_span("test-request"):
        row = record(db, DealCreated(deal_id=crm_data["deal"].id, company_id=crm_data["company"].id, owner_id=users["rep"].id))

    assert "trace_context" not in row.payload
    assert "traceparent" not in row.payload
