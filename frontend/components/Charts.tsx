"use client";

import { useState } from "react";

/* Bars carry their value as a direct label, so identity never rests on colour
 * alone and the reader does not have to trace back to an axis. */

export function BarRow({
  label,
  value,
  max,
  display,
  color = "var(--series-1)",
  title,
}: {
  label: string;
  value: number;
  max: number;
  display: string;
  color?: string;
  title?: string;
}) {
  const pct = max > 0 ? Math.max(value > 0 ? 2 : 0, (value / max) * 100) : 0;
  return (
    <div className="bar-row" title={title ?? `${label}: ${display}`}>
      <span className="bar-label">{label}</span>
      <div className="bar-track">
        <div className="bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="bar-value">{display}</span>
    </div>
  );
}

/**
 * Funnel as an ordinal ramp: one hue, light to dark, each step a validated
 * lightness apart. Width encodes how many deals reached that stage, and every
 * bar is directly labelled with its count and drop-off.
 */
export function Funnel({
  rows,
}: {
  rows: { stage: string; reached: number; rate: number | null }[];
}) {
  const ramp = ["var(--ramp-1)", "var(--ramp-2)", "var(--ramp-3)", "var(--ramp-4)", "var(--ramp-5)"];
  const max = Math.max(...rows.map((r) => r.reached), 1);

  return (
    <div>
      {rows.map((row, i) => {
        const pct = (row.reached / max) * 100;
        const dropped = i > 0 ? rows[i - 1].reached - row.reached : 0;
        return (
          <div key={row.stage} style={{ marginBottom: 9 }}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                fontSize: 12.5,
                marginBottom: 4,
              }}
            >
              <span style={{ textTransform: "capitalize" }}>{row.stage}</span>
              <span className="muted" style={{ fontVariantNumeric: "tabular-nums" }}>
                {row.reached} {row.reached === 1 ? "deal" : "deals"}
                {i > 0 && dropped > 0 && (
                  <span style={{ marginLeft: 8 }}>−{dropped} dropped</span>
                )}
              </span>
            </div>
            {/* 2px gap between adjacent fills keeps segments legible. */}
            <div className="bar-track" style={{ height: 24 }}>
              <div
                className="bar-fill"
                style={{ width: `${Math.max(pct, 2)}%`, background: ramp[Math.min(i, 4)] }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

/**
 * Grouped columns for the forecast. Weighted and raw are both money on the same
 * scale, so they share one axis -- a second y-axis would be the single most
 * common way to make this chart lie.
 */
export function ForecastChart({
  buckets,
}: {
  buckets: { month: string; weighted: string; raw: string; dealCount: number }[];
}) {
  const [hover, setHover] = useState<number | null>(null);
  if (!buckets.length) return null;

  const values = buckets.flatMap((b) => [Number(b.raw), Number(b.weighted)]);
  const max = Math.max(...values, 1);
  const H = 150;

  return (
    <div>
      <div className="legend" style={{ marginBottom: 12 }}>
        <span>
          <i className="swatch" style={{ background: "var(--series-1)" }} /> Weighted
        </span>
        <span>
          <i className="swatch" style={{ background: "var(--series-2)" }} /> Unweighted
        </span>
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          gap: 18,
          height: H,
          borderBottom: "1px solid var(--border)",
          padding: "0 4px",
        }}
      >
        {buckets.map((b, i) => {
          const w = (Number(b.weighted) / max) * (H - 24);
          const r = (Number(b.raw) / max) * (H - 24);
          return (
            <div
              key={b.month}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
              style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "flex-end", position: "relative" }}
            >
              {hover === i && (
                <div
                  role="tooltip"
                  style={{
                    position: "absolute", bottom: "100%", left: "50%",
                    transform: "translateX(-50%)", marginBottom: 6,
                    background: "var(--surface-1)", border: "1px solid var(--border-strong)",
                    borderRadius: 8, padding: "7px 9px", fontSize: 12,
                    boxShadow: "var(--shadow)", whiteSpace: "nowrap", zIndex: 5,
                  }}
                >
                  <strong>{b.month}</strong>
                  <div>Weighted {fmt(b.weighted)}</div>
                  <div>Unweighted {fmt(b.raw)}</div>
                  <div className="muted">{b.dealCount} open</div>
                </div>
              )}
              {/* 2px gap between the paired bars, per the mark spec. */}
              <div style={{ display: "flex", gap: 2, alignItems: "flex-end", height: H - 22 }}>
                <div style={{ flex: 1, height: Math.max(w, 2), background: "var(--series-1)", borderRadius: "4px 4px 0 0" }} />
                <div style={{ flex: 1, height: Math.max(r, 2), background: "var(--series-2)", borderRadius: "4px 4px 0 0" }} />
              </div>
              <div style={{ fontSize: 11, color: "var(--text-muted)", textAlign: "center", marginTop: 6 }}>
                {b.month.slice(5)}/{b.month.slice(2, 4)}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function fmt(v: string) {
  const n = Number(v);
  if (!Number.isFinite(n)) return v;
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 1_000) return `$${Math.round(n / 1_000)}k`;
  return `$${n.toFixed(0)}`;
}
