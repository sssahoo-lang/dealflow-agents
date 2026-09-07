"use client";

import { useEffect, useState } from "react";
import { clearSession, getUser, type User } from "@/lib/api";
import Login from "@/components/Login";
import Pipeline from "@/components/Pipeline";
import Agents from "@/components/Agents";
import RulesView from "@/components/Rules";
import EventPipeline from "@/components/EventPipeline";

type Tab = "pipeline" | "agents" | "rules" | "events";

const TABS: { id: Tab; label: string; blurb: string; adminOnly?: boolean }[] = [
  { id: "pipeline", label: "Pipeline", blurb: "Analytics built by the Java service from the event stream" },
  { id: "agents", label: "Agents", blurb: "Lead scoring, follow-up drafting, and natural-language query" },
  { id: "rules", label: "Rules", blurb: "Deterministic findings from a scheduled sweep" },
  { id: "events", label: "Event pipeline", blurb: "How events travel from the CRM to the analytics service", adminOnly: true },
];

export default function Home() {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [tab, setTab] = useState<Tab>("pipeline");
  const [theme, setTheme] = useState<"light" | "dark">("light");

  useEffect(() => {
    setUser(getUser());
    setReady(true);
    // With no data-theme attribute the stylesheet follows prefers-color-scheme,
    // so the button has to start from the *resolved* theme -- otherwise it can
    // read "Dark" on a page that is already dark and the first click does
    // nothing visible. Resolved on mount, not in useState, to keep SSR and the
    // first client render identical.
    let resolved: "light" | "dark" =
      window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    try {
      const saved = window.localStorage.getItem("dealflow.theme");
      if (saved === "dark" || saved === "light") resolved = saved;
    } catch { /* storage blocked; fall back to the system preference */ }
    setTheme(resolved);
    // Pin the attribute so the stylesheet and the button agree from here on --
    // deliberately without writing to storage, since nothing was chosen yet.
    document.documentElement.setAttribute("data-theme", resolved);
  }, []);

  function applyTheme(next: "light" | "dark") {
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
    try { window.localStorage.setItem("dealflow.theme", next); } catch { /* ignore */ }
  }

  if (!ready) return null;
  if (!user) return <Login onSignedIn={setUser} />;

  const isAdmin = user.role === "admin";
  const visible = TABS.filter((t) => !t.adminOnly || isAdmin);
  const active = visible.find((t) => t.id === tab) ?? visible[0];

  return (
    <div className="shell">
      <nav className="sidebar">
        <div className="brand">
          <span className="brand-mark">DF</span>
          <span>
            <div className="brand-name">DealFlow</div>
            <div className="brand-sub">Agents</div>
          </span>
        </div>
        {visible.map((t) => (
          <button key={t.id} className="nav-item" onClick={() => setTab(t.id)}
                  aria-current={active.id === t.id ? "page" : undefined}>
            <span className="dot" /> {t.label}
          </button>
        ))}
        <div style={{ marginTop: "auto", paddingTop: 16 }}>
          <div className="muted" style={{ fontSize: 11.5, padding: "0 10px 8px" }}>
            {user.full_name}
            <div>{isAdmin ? "Admin — sees every rep" : "Rep — own deals only"}</div>
          </div>
        </div>
      </nav>

      <div className="main">
        <header className="topbar">
          <div>
            <h1>{active.label}</h1>
            <div className="sub">{active.blurb}</div>
          </div>
          <div className="topbar-actions">
            <button className="btn btn-sm" onClick={() => applyTheme(theme === "dark" ? "light" : "dark")}
                    aria-label="Toggle colour theme">
              {theme === "dark" ? "☀ Light" : "☾ Dark"}
            </button>
            <button className="btn btn-sm" onClick={() => { clearSession(); setUser(null); }}>
              Sign out
            </button>
          </div>
        </header>

        <main className="content">
          {active.id === "pipeline" && <Pipeline />}
          {active.id === "agents" && <Agents />}
          {active.id === "rules" && <RulesView isAdmin={isAdmin} />}
          {active.id === "events" && <EventPipeline />}
        </main>
      </div>
    </div>
  );
}
