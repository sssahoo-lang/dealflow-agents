"use client";

import { useEffect, useState } from "react";
import { analytics } from "@/lib/api";

type Finding = {
  id: number; dealId: number; dealName: string | null; stage: string | null;
  ruleCode: string; ruleName: string; severity: string; status: string;
  openedAt: string; detail: Record<string, string> | null;
};
type Rule = {
  id: number; code: string; name: string; description: string | null;
  severity: string; enabled: boolean; lastValidationError: string | null;
  condition: unknown;
};

export default function Rules({ isAdmin }: { isAdmin: boolean }) {
  const [findings, setFindings] = useState<Finding[]>([]);
  const [rules, setRules] = useState<Rule[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [sweeping, setSweeping] = useState(false);
  const [lastSweep, setLastSweep] = useState<string | null>(null);

  const load = () =>
    Promise.all([
      analytics.get<{ findings: Finding[] }>("/rules/findings?status=open&limit=50"),
      analytics.get<{ rules: Rule[] }>("/rules"),
    ])
      .then(([f, r]) => { setFindings(f.findings); setRules(r.rules); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));

  useEffect(() => { load(); }, []);

  async function sweep() {
    setSweeping(true); setError(null);
    try {
      const r = await analytics.post<{ totalOpened: number; totalResolved: number }>("/rules/run");
      setLastSweep(`${r.totalOpened} opened · ${r.totalResolved} resolved`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sweep failed");
    } finally {
      setSweeping(false);
    }
  }

  if (loading) return <div className="card"><div className="empty"><span className="spinner" /> Loading rules…</div></div>;

  return (
    <>
      {error && <div className="error">{error}</div>}

      <section className="card">
        <div className="card-head">
          <h2>Open findings</h2>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            {lastSweep && <span className="hint">{lastSweep}</span>}
            {isAdmin && (
              <button className="btn btn-sm" onClick={sweep} disabled={sweeping}>
                {sweeping ? <span className="spinner" /> : "Run sweep now"}
              </button>
            )}
          </div>
        </div>
        <p className="muted" style={{ fontSize: 12.5, marginTop: 0 }}>
          These come from a scheduled sweep, not from events. A rule about the{" "}
          <em>absence</em> of activity has nothing to trigger it — nothing happens when a
          deal goes quiet, which is exactly the condition worth catching.
        </p>

        {findings.length === 0 ? (
          <div className="empty">
            Nothing flagged. {isAdmin ? "Run a sweep to re-check." : "Your deals are all healthy."}
          </div>
        ) : (
          <table>
            <thead>
              <tr><th>Severity</th><th>Rule</th><th>Deal</th><th>Stage</th><th className="num">Quiet for</th></tr>
            </thead>
            <tbody>
              {findings.map((f) => (
                <tr key={f.id}>
                  <td><span className={`pill pill-${sev(f.severity)}`}>{sevGlyph(f.severity)} {f.severity}</span></td>
                  <td>{f.ruleName}<div className="muted mono" style={{ fontSize: 11 }}>{f.ruleCode}</div></td>
                  <td>{f.dealName ?? `#${f.dealId}`}</td>
                  <td style={{ textTransform: "capitalize" }}>{f.stage ?? "—"}</td>
                  <td className="num">
                    {f.detail?.daysSinceLastActivity && f.detail.daysSinceLastActivity !== "null"
                      ? `${f.detail.daysSinceLastActivity}d`
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Rule definitions</h2>
          <span className="hint">stored as data, editable without a redeploy</span>
        </div>
        {rules.map((r) => (
          <div key={r.id} style={{ padding: "11px 0", borderBottom: "1px solid var(--grid)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 9, flexWrap: "wrap" }}>
              <span className={`pill pill-${sev(r.severity)}`}>{sevGlyph(r.severity)} {r.severity}</span>
              <strong>{r.name}</strong>
              <span className="muted mono" style={{ fontSize: 11.5 }}>{r.code}</span>
              {!r.enabled && <span className="pill">⏸ disabled</span>}
            </div>
            {r.description && (
              <div className="muted" style={{ fontSize: 12.5, marginTop: 4 }}>{r.description}</div>
            )}
            {r.lastValidationError && (
              <div className="error" style={{ marginTop: 7, fontSize: 12 }}>
                Not evaluable: {r.lastValidationError}
              </div>
            )}
            <details style={{ marginTop: 7 }}>
              <summary className="muted" style={{ fontSize: 12, cursor: "pointer" }}>Condition</summary>
              <pre className="mono" style={{
                background: "var(--surface-2)", padding: 10, borderRadius: 8,
                fontSize: 11.5, overflow: "auto", marginTop: 6,
              }}>{JSON.stringify(r.condition, null, 2)}</pre>
            </details>
          </div>
        ))}
      </section>
    </>
  );
}

const sev = (s: string) => (s === "critical" ? "critical" : s === "warn" ? "warning" : "good");
const sevGlyph = (s: string) => (s === "critical" ? "●" : s === "warn" ? "▲" : "■");
