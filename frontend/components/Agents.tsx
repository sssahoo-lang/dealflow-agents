"use client";

import { useEffect, useRef, useState } from "react";
import { crm, money } from "@/lib/api";

type Deal = {
  id: number; name: string; stage: string; value: string;
  score: number | null; priority: string | null; company_id: number;
};
type Activity = { id: number; type: string; subject: string | null; body: string; is_draft: boolean };

export default function Agents() {
  const [deals, setDeals] = useState<Deal[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [name, setName] = useState("");
  const [value, setValue] = useState("75000");
  const [creating, setCreating] = useState(false);
  const [justScored, setJustScored] = useState<number | null>(null);

  const [draft, setDraft] = useState<{ subject: string; body: string } | null>(null);
  const [drafting, setDrafting] = useState<number | null>(null);
  // Clicking a row far down the table scrolls the draft card back into view.
  const draftRef = useRef<HTMLElement | null>(null);

  const [question, setQuestion] = useState("Which of my deals are worth the most?");
  const [answer, setAnswer] = useState<{ answer: string; tool_calls: string[] } | null>(null);
  const [asking, setAsking] = useState(false);

  const load = () =>
    crm.get<Deal[]>("/deals").then(setDeals).catch((e) => setError(e.message)).finally(() => setLoading(false));

  useEffect(() => { load(); }, []);

  useEffect(() => {
    if (draft) draftRef.current?.scrollIntoView({ block: "nearest" });
  }, [draft]);

  async function createDeal(e: React.FormEvent) {
    e.preventDefault();
    setCreating(true); setError(null);
    try {
      const company = deals[0]?.company_id ?? 1;
      const deal = await crm.post<Deal>("/deals", {
        name: name || "New opportunity", company_id: company, value: Number(value),
      });
      // Scoring runs in a background task after the response, so give the agent
      // a moment before re-reading rather than showing an unscored row.
      setJustScored(deal.id);
      setName("");
      setTimeout(() => load().then(() => setTimeout(() => setJustScored(null), 4000)), 2500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create deal");
    } finally {
      setCreating(false);
    }
  }

  async function writeDraft(dealId: number) {
    setDrafting(dealId); setDraft(null); setError(null);
    try {
      setDraft(await crm.post<{ subject: string; body: string }>("/agents/follow-up", { deal_id: dealId }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Draft failed");
    } finally {
      setDrafting(null);
    }
  }

  async function ask(e: React.FormEvent) {
    e.preventDefault();
    setAsking(true); setAnswer(null); setError(null);
    try {
      setAnswer(await crm.post<{ answer: string; tool_calls: string[] }>("/agents/query", { question }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Query failed");
    } finally {
      setAsking(false);
    }
  }

  return (
    <>
      {error && <div className="error">{error}</div>}

      <div className="grid grid-2">
        <section className="card">
          <div className="card-head">
            <h2>Lead scoring</h2>
            <span className="hint">event-triggered</span>
          </div>
          <p className="muted" style={{ fontSize: 12.5, marginTop: 0 }}>
            Creating a deal emits an event; the scoring agent picks it up in the
            background and writes back a score and reasoning.
          </p>
          <form onSubmit={createDeal} style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
            <div className="field" style={{ flex: 2, marginBottom: 0 }}>
              <label htmlFor="dn">Deal name</label>
              <input id="dn" value={name} placeholder="Acme expansion"
                     onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="field" style={{ flex: 1, marginBottom: 0 }}>
              <label htmlFor="dv">Value</label>
              <input id="dv" type="number" value={value} onChange={(e) => setValue(e.target.value)} />
            </div>
            <button className="btn btn-primary" disabled={creating}>
              {creating ? <span className="spinner" /> : "Create"}
            </button>
          </form>
          {justScored && (
            <div className="muted" style={{ fontSize: 12.5, marginTop: 10 }}>
              <span className="spinner" style={{ marginRight: 7 }} />
              Deal #{justScored} created — waiting for the scoring agent…
            </div>
          )}
        </section>

        <section className="card">
          <div className="card-head">
            <h2>Ask the pipeline</h2>
            <span className="hint">tool-calling agent</span>
          </div>
          <p className="muted" style={{ fontSize: 12.5, marginTop: 0 }}>
            The agent never writes SQL. It calls read-only tools that are scoped to
            your role server-side, so it cannot widen its own access.
          </p>
          <form onSubmit={ask} style={{ display: "flex", gap: 8 }}>
            <input value={question} onChange={(e) => setQuestion(e.target.value)}
                   placeholder="How many deals by stage?" />
            <button className="btn btn-primary" disabled={asking}>
              {asking ? <span className="spinner" /> : "Ask"}
            </button>
          </form>
          {answer && (
            <div style={{ marginTop: 12 }}>
              {answer.tool_calls.length > 0 && (
                <div className="muted" style={{ fontSize: 11.5, marginBottom: 6 }}>
                  Tools called: {answer.tool_calls.map((t) => <code key={t} className="mono">{t} </code>)}
                </div>
              )}
              <pre style={{
                whiteSpace: "pre-wrap", margin: 0, fontSize: 12.5,
                background: "var(--surface-2)", padding: 11, borderRadius: 8,
                maxHeight: 230, overflow: "auto",
              }}>{answer.answer}</pre>
            </div>
          )}
        </section>
      </div>

      {/* Above the deals table, not below it: the table is long enough that a
          draft appended at the end would arrive off screen and the click would
          look like it did nothing. */}
      {draft && (
        <section className="card" ref={draftRef}>
          <div className="card-head">
            <h2>Follow-up draft</h2>
            <span className="pill pill-warning">✎ draft — never sent</span>
          </div>
          <div style={{ fontWeight: 600, marginBottom: 7 }}>{draft.subject}</div>
          <pre style={{
            whiteSpace: "pre-wrap", margin: 0, fontSize: 13,
            background: "var(--surface-2)", padding: 13, borderRadius: 8,
          }}>{draft.body}</pre>
        </section>
      )}

      <section className="card">
        <div className="card-head">
          <h2>Deals</h2>
          <span className="hint">score and priority are written by the agent, not by you</span>
        </div>
        {loading ? (
          <div className="empty"><span className="spinner" /> Loading…</div>
        ) : deals.length === 0 ? (
          <div className="empty">No deals yet.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Deal</th><th>Stage</th><th className="num">Value</th>
                <th className="num">Score</th><th>Priority</th><th></th>
              </tr>
            </thead>
            <tbody>
              {deals.slice(0, 12).map((d) => (
                <tr key={d.id} style={justScored === d.id ? { background: "var(--surface-2)" } : undefined}>
                  <td>{d.name}</td>
                  <td style={{ textTransform: "capitalize" }}>{d.stage}</td>
                  <td className="num">{money(d.value)}</td>
                  <td className="num">{d.score !== null ? d.score.toFixed(0) : <span className="muted">pending</span>}</td>
                  <td>{d.priority ? <span className={`pill pill-${prio(d.priority)}`}>{glyph(d.priority)} {d.priority}</span> : <span className="muted">—</span>}</td>
                  <td className="num">
                    <button className="btn btn-sm" onClick={() => writeDraft(d.id)} disabled={drafting === d.id}>
                      {drafting === d.id ? <span className="spinner" /> : "Draft follow-up"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

    </>
  );
}

const prio = (p: string) => (p === "high" ? "critical" : p === "medium" ? "warning" : "good");
const glyph = (p: string) => (p === "high" ? "▲" : p === "medium" ? "◆" : "▼");
