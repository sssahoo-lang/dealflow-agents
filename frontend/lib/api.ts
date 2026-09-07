"use client";

/**
 * Both services are called directly from the browser rather than proxied through
 * one of them. That keeps the service boundary visible in the network tab -- you
 * can watch the CRM and the analytics service answer separately -- and avoids
 * putting the Python app in the path of every analytics query.
 */
export const CRM_URL =
  process.env.NEXT_PUBLIC_CRM_URL ?? "http://localhost:8000";
export const ANALYTICS_URL =
  process.env.NEXT_PUBLIC_ANALYTICS_URL ?? "http://localhost:8081";

const TOKEN_KEY = "dealflow.token";
const USER_KEY = "dealflow.user";

export type User = { email: string; full_name: string; role: string };

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function getUser(): User | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as User) : null;
  } catch {
    return null;
  }
}

export function setSession(token: string, user: User) {
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
    window.localStorage.setItem(USER_KEY, JSON.stringify(user));
  } catch {
    /* private browsing: the session simply won't persist a reload */
  }
}

export function clearSession() {
  try {
    window.localStorage.removeItem(TOKEN_KEY);
    window.localStorage.removeItem(USER_KEY);
  } catch {
    /* nothing to clear */
  }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(base: string, path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const res = await fetch(`${base}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
  });

  if (res.status === 401) {
    clearSession();
    throw new ApiError(401, "Session expired. Please sign in again.");
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      detail = body.detail ?? body.error ?? body.message ?? detail;
    } catch {
      /* not JSON; keep the status line */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const crm = {
  get: <T,>(path: string) => request<T>(CRM_URL, path),
  post: <T,>(path: string, body: unknown) =>
    request<T>(CRM_URL, path, { method: "POST", body: JSON.stringify(body) }),
  patch: <T,>(path: string, body: unknown) =>
    request<T>(CRM_URL, path, { method: "PATCH", body: JSON.stringify(body) }),
};

export const analytics = {
  get: <T,>(path: string) => request<T>(ANALYTICS_URL, path),
  post: <T,>(path: string, body?: unknown) =>
    request<T>(ANALYTICS_URL, path, {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
    }),
};

export async function login(email: string, password: string) {
  const { access_token } = await request<{ access_token: string }>(
    CRM_URL,
    "/auth/login",
    { method: "POST", body: JSON.stringify({ email, password }) }
  );
  window.localStorage.setItem(TOKEN_KEY, access_token);
  const user = await request<User>(CRM_URL, "/auth/me");
  setSession(access_token, user);
  return user;
}

/** Money arrives as a string on purpose; never parse it to a float for display. */
export function money(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const n = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(n)) return String(value);
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

export function compactMoney(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const n = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(n)) return String(value);
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 1_000) return `$${Math.round(n / 1_000)}k`;
  return `$${n.toFixed(0)}`;
}

export function percent(value: number | null | undefined): string {
  return value === null || value === undefined
    ? "—"
    : `${Math.round(value * 100)}%`;
}
