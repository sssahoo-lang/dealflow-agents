"use client";

import { useEffect, useState } from "react";
import { analytics, compactMoney, money, percent } from "@/lib/api";
import { BarRow, ForecastChart, Funnel } from "./Charts";

type Leader = {
  ownerId: number; ownerName: string | null; ownerEmail: string | null;
  dealsWon: number; dealsLost: number; wonValue: string; openValue: string;
  winRate: number | null; avgDaysToClose: number | null;
};
type Conversion = { fromStage: string; toStage: string; entered: number; advanced: number; rate: number | null };
type Velocity = { stage: string; avgDays: number | null; medianDays: number | null; sampleSize: number };
type Forecast = {
  weightedTotal: string; rawPipeline: string;
  unscheduledDealCount: number; unscheduledValue: string;
  buckets: { month: string; weighted: string; raw: string; dealCount: number }[];
};

export default function Pipeline() {
  const [leaders, setLeaders] = useState<Leader[]>([]);
  const [conversion, setConversion] = useState<Conversion[]>([]);
  const [velocity, setVelocity] = useState<Velocity[]>([]);
  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // A year-long window: the demo pipeline spans about five months, and the
    // endpoint's 90-day default would hide most of the closed deals.
    const from = new Date(Date.now() - 365 * 864e5).toISOString();
    Promise.all([
      analytics.get<{ rows: Leader[] }>(`/analytics/leaderboard?from=${from}&limit=25`),
      analytics.get<{ rows: Conversion[] }>("/analytics/conversion"),
      analytics.get<{ rows: Velocity[] }>("/analytics/velocity"),
      analytics.get<Forecast>("/analytics/forecast?horizonMonths=6"),
    ])
      .then(([l, c, v, f]) => {
        setLeaders(l.rows); setConversion(c.rows); setVelocity(v.rows); setForecast(f);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="card"><div className="empty"><span className="spinner" /> Loading analytics…</div></div>;
  if (error) return <div className="error">{error}</div>;

  const totalWon = leaders.reduce((s, r) => s + Number(r.wonValue), 0);
  const totalOpen = leaders.reduce((s, r) => s + Number(r.openValue), 0);
  const won = leaders.reduce((s, r) => s + r.dealsWon, 0);
  const lost = leaders.reduce((s, r) => s + r.dealsLost, 0);
  const maxWon = Math.max(...leaders.map((r) => Number(r.wonValue)), 1);

  // The funnel needs stages, not stage-pairs: take each row's entry count, then
  // append the final stage from the last row's advanced count.
  const funnelRows = conversion.length
    ? [
        ...conversion.map((c) => ({ stage: c.fromStage, reached: c.entered, rate: c.rate })),
        {
          stage: conversion[conversion.length - 1].toStage,
          reached: conversion[conversion.length - 1].advanced,
          rate: null,
        },
      ]
    : [];

  const maxVelocity = Math.max(...velocity.map((v) => v.avgDays ?? 0), 1);

  return (
    <>
      <div className="grid grid-kpi">
        <Kpi label="Open pipeline" value={money(totalOpen)} meta={`${leaders.length} ${leaders.length === 1 ? "rep" : "reps"} active`} />
        <Kpi label="Closed won" value={money(totalWon)} meta={`${won} won · ${lost} lost`} />
        <Kpi label="Win rate" value={won + lost > 0 ? percent(won / (won + lost)) : "—"}
             meta={won + lost > 0 ? `across ${won + lost} closed ${won + lost === 1 ? "deal" : "deals"}` : "nothing closed yet"} />
        <Kpi label="Weighted forecast" value={forecast ? money(forecast.weightedTotal) : "—"}
             meta={forecast ? `of ${money(forecast.rawPipeline)} scheduled` : ""} />
      </div>

      <div className="grid grid-2">
        <section className="card">
          <div className="card-head">
            <h2>Rep leaderboard</h2>
            <span className="hint">closed-won value, last 12 months</span>
          </div>
          {leaders.length === 0 ? (
            <div className="empty">No reps with pipeline yet.</div>
          ) : (
            <>
              <div style={{ margin: "10px 0 14px" }}>
                {leaders.map((r) => (
                  <BarRow key={r.ownerId} label={r.ownerName ?? r.ownerEmail ?? `#${r.ownerId}`}
                          value={Number(r.wonValue)} max={maxWon}
                          display={compactMoney(r.wonValue)} />
                ))}
              </div>
              {/* The table is the accessible view of the same numbers. */}
              <table>
                <thead>
                  <tr>
                    <th>Rep</th><th className="num">Won</th><th className="num">Lost</th>
                    <th className="num">Win rate</th><th className="num">Avg days</th>
                    <th className="num">Open</th>
                  </tr>
                </thead>
                <tbody>
                  {leaders.map((r) => (
                    <tr key={r.ownerId}>
                      <td>{r.ownerName ?? r.ownerEmail}</td>
                      <td className="num">{r.dealsWon}</td>
                      <td className="num">{r.dealsLost}</td>
                      <td className="num">{percent(r.winRate)}</td>
                      <td className="num">{r.avgDaysToClose?.toFixed(0) ?? "—"}</td>
                      <td className="num">{compactMoney(r.openValue)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </section>

        <section className="card">
          <div className="card-head">
            <h2>Conversion funnel</h2>
            <span className="hint">deals reaching each stage</span>
          </div>
          {funnelRows.length === 0 ? <div className="empty">No stage history yet.</div> : (
            <div style={{ marginTop: 10 }}><Funnel rows={funnelRows} /></div>
          )}
        </section>

        <section className="card">
          <div className="card-head">
            <h2>Stage velocity</h2>
            <span className="hint">average days before moving on</span>
          </div>
          {velocity.length === 0 ? <div className="empty">Not enough transitions yet.</div> : (
            <div style={{ marginTop: 10 }}>
              {velocity.map((v) => (
                <BarRow key={v.stage} label={v.stage} value={v.avgDays ?? 0} max={maxVelocity}
                        display={`${(v.avgDays ?? 0).toFixed(1)}d`}
                        title={`${v.stage}: avg ${v.avgDays?.toFixed(1)}d, median ${v.medianDays?.toFixed(1)}d, n=${v.sampleSize}`} />
              ))}
              <div className="muted" style={{ fontSize: 11.5, marginTop: 9 }}>
                Sample sizes: {velocity.map((v) => `${v.stage} n=${v.sampleSize}`).join(" · ")}
              </div>
            </div>
          )}
        </section>

        <section className="card">
          <div className="card-head">
            <h2>Weighted forecast</h2>
            <span className="hint">next 6 months, by stage probability</span>
          </div>
          {!forecast || forecast.buckets.length === 0 ? (
            <div className="empty">No open deals have an expected close date.</div>
          ) : (
            <div style={{ marginTop: 10 }}><ForecastChart buckets={forecast.buckets} /></div>
          )}
          {forecast && forecast.unscheduledDealCount > 0 && (
            <div className="muted" style={{ fontSize: 12, marginTop: 12 }}>
              Excluded: {forecast.unscheduledDealCount} open{" "}
              {forecast.unscheduledDealCount === 1 ? "deal" : "deals"} worth{" "}
              {money(forecast.unscheduledValue)} with no close date — reported rather
              than dropped, so the forecast never looks smaller than the pipeline is.
            </div>
          )}
        </section>
      </div>
    </>
  );
}

function Kpi({ label, value, meta }: { label: string; value: string; meta?: string }) {
  return (
    <div className="card kpi">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {meta && <div className="meta">{meta}</div>}
    </div>
  );
}
