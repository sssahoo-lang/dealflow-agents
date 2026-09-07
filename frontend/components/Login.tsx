"use client";

import { useState } from "react";
import { login, type User } from "@/lib/api";

const DEMO = [
  { email: "admin@demo.com", label: "Ada Admin", role: "sees every rep" },
  { email: "rep@demo.com", label: "Raj Rep", role: "own deals only" },
  { email: "rep2@demo.com", label: "Nina Rep", role: "own deals only" },
];

export default function Login({ onSignedIn }: { onSignedIn: (u: User) => void }) {
  const [email, setEmail] = useState("admin@demo.com");
  const [password, setPassword] = useState("demo1234");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent, as?: string) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSignedIn(await login(as ?? email, "demo1234"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <form className="card login-card" onSubmit={submit}>
        <div className="brand" style={{ padding: "0 0 16px" }}>
          <span className="brand-mark">DF</span>
          <span>
            <div className="brand-name">DealFlow Agents</div>
            <div className="brand-sub">Pipeline · Agents · Rules</div>
          </span>
        </div>

        {error && <div className="error" style={{ marginBottom: 13 }}>{error}</div>}

        <div className="field">
          <label htmlFor="email">Email</label>
          <input id="email" type="email" value={email} autoComplete="username"
                 onChange={(e) => setEmail(e.target.value)} required />
        </div>
        <div className="field">
          <label htmlFor="password">Password</label>
          <input id="password" type="password" value={password} autoComplete="current-password"
                 onChange={(e) => setPassword(e.target.value)} required />
        </div>

        <button className="btn btn-primary" style={{ width: "100%" }} disabled={busy}>
          {busy ? <span className="spinner" /> : "Sign in"}
        </button>

        <div className="demo-logins">
          <div className="muted" style={{ fontSize: 12, marginBottom: 7 }}>
            Demo accounts — the role changes what you can see:
          </div>
          {DEMO.map((d) => (
            <div key={d.email} className="demo-login">
              <span>
                <strong>{d.label}</strong> <span className="muted">· {d.role}</span>
              </span>
              <button type="button" className="btn btn-sm" disabled={busy}
                      onClick={(e) => submit(e, d.email)}>
                Use
              </button>
            </div>
          ))}
        </div>
      </form>
    </div>
  );
}
