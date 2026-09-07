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
  // Bars scale to the rounded-up axis maximum, not to the tallest bar, so every
  // gridline lands on a whole number and the tallest bar stops short of the top
  // instead of touching the frame.
  const { max, ticks } = axisScale(Math.max(...values, 1));
  const H = 150;
  const AXIS_W = 44;

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

      <div style={{ display: "flex" }}>
        {/* The value axis: labels sit on the gridlines they name, so each one is
            read at the height it applies to rather than looked up in a legend. */}
        <div style={{ width: AXIS_W, height: H, position: "relative", flexShrink: 0 }}>
          {ticks.map((t) => (
            <div
              key={t}
              style={{
                position: "absolute", right: 8, bottom: (t / max) * H,
                transform: "translateY(50%)",
                fontSize: 11, color: "var(--text-muted)", whiteSpace: "nowrap",
              }}
            >
              {t === 0 ? "0" : tickLabel(t)}
            </div>
          ))}
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ position: "relative", height: H }}>
            {/* Gridlines are recessive: hairlines behind the marks, never
                competing with them. The baseline is solid, the rest dashed. */}
            {ticks.map((t) => (
              <div
                key={t}
                aria-hidden="true"
                style={{
                  position: "absolute", left: 0, right: 0, bottom: (t / max) * H,
                  borderTop: t === 0
                    ? "1px solid var(--border-strong)"
                    : "1px dashed var(--border)",
                }}
              />
            ))}

            <div
              style={{
                position: "absolute", inset: 0,
                display: "flex", alignItems: "flex-end", gap: 18, padding: "0 4px",
              }}
            >
              {buckets.map((b, i) => {
                const w = (Number(b.weighted) / max) * H;
                const r = (Number(b.raw) / max) * H;
                return (
                  <div
                    key={b.month}
                    onMouseEnter={() => setHover(i)}
                    onMouseLeave={() => setHover(null)}
                    style={{ flex: 1, position: "relative", height: "100%", display: "flex", alignItems: "flex-end" }}
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
                    <div style={{ display: "flex", gap: 2, alignItems: "flex-end", width: "100%", height: "100%" }}>
                      <div style={{ flex: 1, height: Math.max(w, 2), background: "var(--series-1)", borderRadius: "4px 4px 0 0" }} />
                      <div style={{ flex: 1, height: Math.max(r, 2), background: "var(--series-2)", borderRadius: "4px 4px 0 0" }} />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div style={{ display: "flex", gap: 18, padding: "6px 4px 0" }}>
            {buckets.map((b) => (
              <div
                key={b.month}
                style={{ flex: 1, fontSize: 11, color: "var(--text-muted)", textAlign: "center" }}
              >
                {b.month.slice(5)}/{b.month.slice(2, 4)}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

/* Round the axis up to a maximum divisible into readable steps, so ticks read
 * $200k / $400k rather than $198.75k. Two details matter:
 *
 * Picking the *step* first and multiplying back is what keeps every tick round --
 * rounding the maximum first and dividing does not (2.5M / 4 = 625k).
 *
 * And the interval count is chosen, not fixed. A 1/2/2.5/5/10 ladder jumps hard
 * from 5 to 10, so a $240k peak on four intervals rounds to a $400k axis and the
 * tallest bar reaches 60% of the frame. Five intervals give $250k instead. Try
 * both and keep the tighter axis, preferring fewer ticks on a tie.
 */
export function axisScale(peak: number) {
  const candidates = [4, 5].map((intervals) => {
    const raw = peak / intervals;
    const mag = 10 ** Math.floor(Math.log10(raw));
    const n = raw / mag;
    const step = (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * mag;
    return {
      max: step * intervals,
      step,
      ticks: Array.from({ length: intervals + 1 }, (_, i) => i * step),
    };
  });
  return candidates.reduce((best, c) => (c.max < best.max ? c : best));
}

/* Ticks need a rounding that never lies: fmt() rounds $2,500 to "$3k", which is
 * fine on a bar's own label but wrong on a gridline the bars are measured
 * against. Keep a decimal when the step is not a whole unit. */
function tickLabel(n: number) {
  if (Math.abs(n) < 1_000) return `$${Number.isInteger(n) ? n : n.toFixed(2)}`;
  const [div, suffix] = Math.abs(n) >= 1_000_000 ? [1_000_000, "M"] : [1_000, "k"];
  // Two decimals, then dropped if they are zeros: a $1.25M gridline must not
  // print as "$1.3M" when it is the number the bars are measured against.
  const scaled = Number((n / div).toFixed(2));
  return `$${scaled}${suffix}`;
}

function fmt(v: string) {
  const n = Number(v);
  if (!Number.isFinite(n)) return v;
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 1_000) return `$${Math.round(n / 1_000)}k`;
  return `$${n.toFixed(0)}`;
}
