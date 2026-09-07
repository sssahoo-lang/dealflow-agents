"use client";

import { useEffect, useState } from "react";
import { analytics } from "@/lib/api";

type Status = {
  floor_event_id: number; processed_count: number; dead_count: number;
  retrying_count: number; pending_count: number; lag_seconds: number | string;
};

/** The event pipeline itself: how far the Java consumer has got, and how fresh. */
export default function EventPipeline() {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const tick = () =>
      analytics.get<Status>("/admin/outbox/status").then(setStatus).catch((e) => setError(e.message));
    tick();
    const id = setInterval(tick, 5000);
    return () => clearInterval(id);
  }, []);

  if (error) return <div className="error">{error}<div className="muted" style={{ fontSize: 12, marginTop: 6 }}>This view is admin-only.</div></div>;
  if (!status) return <div className="card"><div className="empty"><span className="spinner" /> Reading consumer status…</div></div>;

  const lag = Number(status.lag_seconds);
  const healthy = status.pending_count === 0 && status.dead_count === 0;

  return (
    <>
      <div className="grid grid-kpi">
        <Tile label="Pending" value={String(status.pending_count)}
              meta={status.pending_count === 0 ? "consumer is caught up" : "waiting to be processed"} />
        <Tile label="Processed" value={String(status.processed_count)} meta="events applied" />
        <Tile label="Consumer lag" value={lag > 0 ? `${lag.toFixed(1)}s` : "0s"}
              meta="age of the oldest unprocessed event" />
        <Tile label="Dead letters" value={String(status.dead_count)}
              meta={status.dead_count === 0 ? "none" : "permanently skipped"} />
      </div>

      <section className="card">
        <div className="card-head">
          <h2>How an event travels</h2>
          <span className={`pill pill-${healthy ? "good" : "warning"}`}>
            {healthy ? "■ healthy" : "▲ backlog"}
          </span>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10, margin: "14px 0", fontSize: 12.5 }}>
          <Node title="Python CRM" sub="writes the deal" />
          <Arrow label="same transaction" />
          <Node title="outbox_events" sub="durable log" accent />
          <Arrow label={`polls every 2s`} />
          <Node title="Java consumer" sub={`${status.processed_count} processed`} />
          <Arrow label="upsert" />
          <Node title="Read model" sub="projections" />
        </div>
        <p className="muted" style={{ fontSize: 12.5, margin: 0 }}>
          The deal and its event commit together — neither can exist without the other.
          Progress is tracked by a ledger of processed ids rather than a high-water
          mark, because serial ids are assigned at insert but only become visible at
          commit: a consumer storing “last seen” would skip events that committed out
          of order, silently.
        </p>
        {status.retrying_count > 0 && (
          <div className="muted" style={{ fontSize: 12.5, marginTop: 9 }}>
            {status.retrying_count} event(s) in backoff and will be retried.
          </div>
        )}
      </section>
    </>
  );
}

function Tile({ label, value, meta }: { label: string; value: string; meta: string }) {
  return (
    <div className="card kpi">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      <div className="meta">{meta}</div>
    </div>
  );
}

function Node({ title, sub, accent }: { title: string; sub: string; accent?: boolean }) {
  return (
    <div style={{
      border: `1px solid ${accent ? "var(--series-1)" : "var(--border-strong)"}`,
      borderRadius: 8, padding: "9px 12px", background: "var(--surface-1)", minWidth: 118,
    }}>
      <div style={{ fontWeight: 600 }}>{title}</div>
      <div className="muted" style={{ fontSize: 11.5 }}>{sub}</div>
    </div>
  );
}

function Arrow({ label }: { label: string }) {
  return (
    <div style={{ textAlign: "center", color: "var(--text-muted)", fontSize: 11 }}>
      <div style={{ fontSize: 15, lineHeight: 1 }}>→</div>
      <div>{label}</div>
    </div>
  );
}
