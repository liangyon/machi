/**
 * Auth utility functions.
 *
 * Handles communication with the backend auth endpoints.
 * All requests include credentials so the HttpOnly session cookie is sent.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

// ── Types ───────────────────────────────────────────

export interface User {
  id: string;
  email: string;
  name: string | null;
  avatar_url: string | null;
  provider: string;
  created_at: string;
}

// ── OAuth helpers ───────────────────────────────────

export type OAuthProvider = "google" | "discord";

/** Returns the backend URL that kicks off the OAuth flow for *provider*. */
export function oauthLoginUrl(provider: OAuthProvider): string {
  return `${API_BASE}/api/auth/${provider}/login`;
}

// ── Email / password ────────────────────────────────

export async function register(
  email: string,
  password: string,
  name?: string
): Promise<User> {
  const res = await fetch(`${API_BASE}/api/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ email, password, name: name || null }),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail ?? `Registration failed: ${res.status}`);
  }

  return res.json();
}

export async function loginWithEmail(
  email: string,
  password: string
): Promise<User> {
  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ email, password }),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail ?? `Login failed: ${res.status}`);
  }

  return res.json();
}

// ── Session ─────────────────────────────────────────

export async function fetchMe(): Promise<User | null> {
  const res = await fetch(`${API_BASE}/api/auth/me`, {
    credentials: "include",
  });

  if (res.status === 401) return null;

  if (!res.ok) {
    throw new Error(`Failed to fetch user: ${res.status}`);
  }

  return res.json();
}

export async function logout(): Promise<void> {
  await fetch(`${API_BASE}/api/auth/logout`, {
    method: "POST",
    credentials: "include",
  });
}
