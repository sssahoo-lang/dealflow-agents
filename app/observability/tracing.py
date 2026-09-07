"""Distributed tracing across the language boundary -- opt-in, off by default.

The interesting trace in this system does not fit inside one process. A rep's
`POST /deals` returns in milliseconds; the deal isn't fully "processed" until the
Java service polls the outbox row it produced, applies it to the read model, and
the rules engine can see it. Those two halves run in different languages, at
different times, connected only by a row in Postgres -- there is no synchronous
call across which a tracing library can auto-propagate context.

So the propagation is explicit and asymmetric:

- **The CRM injects.** When it writes an outbox row, it also serialises the
  *current* trace context (the W3C `traceparent` produced by the span this HTTP
  request is running in) into that row's `trace_context` column.
- **The analytics service extracts.** When it later dispatches that row, it reads
  `trace_context` back and starts its span as a CHILD of the original request
  span -- so a trace viewer shows one continuous trace from `POST /deals` down
  into the projection write, with the real wall-clock gap between them rendered
  as exactly what it is: a span that took that long because a poll interval sat
  in the middle of it.

**Why this defaults to off.** Every other design decision in this repo is
justified against the same test: does it run with no API key, no network calls,
no secrets? A tracing SDK is a network client. Turning it on unconditionally
would mean the test suite either grows a real dependency on a collector being up,
or silently no-ops in a way that's easy to stop noticing. Instead:
`OTEL_EXPORTER_OTLP_ENDPOINT` unset means `setup_tracing()` does nothing and
`app/events/outbox.py` writes `trace_context = NULL` -- observably absent, not
quietly broken. Set it (docker-compose does, pointing at the bundled Jaeger) and
the whole path lights up.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from app.config import settings

log = logging.getLogger(__name__)

_enabled = False


def tracing_enabled() -> bool:
    """Whether app/events/outbox.py should bother injecting context.

    A function, not a module-level constant read at import time: settings can be
    monkeypatched in a test, and this must see that.
    """
    return bool(settings.otel_exporter_otlp_endpoint)


def setup_tracing(app: FastAPI) -> None:
    """Wire up the SDK and instrument the app. Idempotent no-op when disabled."""
    global _enabled
    if not tracing_enabled():
        log.info(
            "OTEL_EXPORTER_OTLP_ENDPOINT not set; tracing disabled. This is the "
            "default -- see app/observability/tracing.py."
        )
        return

    # Imported here, not at module scope: importing the SDK is free (it's already
    # a hard requirement, see requirements.txt), but constructing exporters and
    # instrumenting the app is the part that should only happen when enabled.
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter,
    )
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    endpoint = settings.otel_exporter_otlp_endpoint.rstrip("/") + "/v1/traces"
    provider = TracerProvider(
        resource=Resource.create({SERVICE_NAME: "dealflow-crm"})
    )
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app)
    _enabled = True
    log.info("Tracing enabled, exporting to %s", endpoint)


def inject_trace_context() -> str | None:
    """The current span's context, serialised for storage on an outbox row.

    Returns None when tracing is disabled OR when there is no current span worth
    recording (e.g. a script running outside a request, such as seed_demo.py) --
    both cases should leave `trace_context` NULL, not a context pointing at
    nothing.
    """
    if not tracing_enabled():
        return None

    from opentelemetry import propagate, trace

    if not trace.get_current_span().get_span_context().is_valid:
        return None

    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    if not carrier:
        return None
    import json

    return json.dumps(carrier)
