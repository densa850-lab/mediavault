/**
 * Website auth "backend for frontend" (server-side only).
 *
 * The browser never sees access or refresh tokens. Next.js route handlers under /api/auth call
 * the MediaVault API and keep the tokens in httpOnly, SameSite=Strict cookies on the website's own
 * origin (Secure in production). Every state-changing request must come from our own origin
 * (Origin header check), which together with SameSite=Strict blocks CSRF.
 */
import { createHash } from "node:crypto";

import { apiBaseUrl } from "@/lib/env";

export const ACCESS_COOKIE = "mv_access";
export const REFRESH_COOKIE = "mv_refresh";
/** The refresh cookie is only ever sent to the auth route handlers. */
export const REFRESH_COOKIE_PATH = "/api/auth";

type Fetch = typeof fetch;

export interface TokenResponse {
  access_token: string;
  expires_in: number;
  refresh_token: string;
  refresh_expires_in: number;
}

export function serverApiBaseUrl(): string {
  const internal = process.env.API_INTERNAL_BASE_URL?.trim();
  return (internal || apiBaseUrl()).replace(/\/+$/, "");
}

const isProduction = () => process.env.NODE_ENV === "production";

export function serializeCookie(
  name: string,
  value: string,
  opts: { maxAge: number; path: string },
): string {
  const parts = [
    `${name}=${encodeURIComponent(value)}`,
    `Path=${opts.path}`,
    `Max-Age=${Math.max(0, Math.floor(opts.maxAge))}`,
    "HttpOnly",
    "SameSite=Strict",
  ];
  if (isProduction()) parts.push("Secure");
  return parts.join("; ");
}

export function readCookie(req: Request, name: string): string | undefined {
  const header = req.headers.get("cookie");
  if (!header) return undefined;
  for (const part of header.split(";")) {
    const idx = part.indexOf("=");
    if (idx === -1) continue;
    if (part.slice(0, idx).trim() === name) {
      try {
        return decodeURIComponent(part.slice(idx + 1).trim());
      } catch {
        return undefined;
      }
    }
  }
  return undefined;
}

/** True only when the request's Origin is this website (blocks cross-site form posts). */
export function isSameOrigin(req: Request): boolean {
  const origin = req.headers.get("origin");
  if (!origin) return false;
  let originHost: string;
  try {
    originHost = new URL(origin).host;
  } catch {
    return false;
  }
  const host = req.headers.get("x-forwarded-host") ?? req.headers.get("host") ?? new URL(req.url).host;
  return originHost === host;
}

function json(body: unknown, status: number, cookies: string[] = []): Response {
  const headers = new Headers({ "Content-Type": "application/json", "Cache-Control": "no-store" });
  for (const c of cookies) headers.append("Set-Cookie", c);
  return new Response(body === null ? null : JSON.stringify(body), { status, headers });
}

function tokenCookies(t: TokenResponse): string[] {
  return [
    serializeCookie(ACCESS_COOKIE, t.access_token, { maxAge: t.expires_in, path: "/" }),
    serializeCookie(REFRESH_COOKIE, t.refresh_token, {
      maxAge: t.refresh_expires_in,
      path: REFRESH_COOKIE_PATH,
    }),
  ];
}

export function clearCookies(): string[] {
  return [
    serializeCookie(ACCESS_COOKIE, "", { maxAge: 0, path: "/" }),
    serializeCookie(REFRESH_COOKIE, "", { maxAge: 0, path: REFRESH_COOKIE_PATH }),
  ];
}

function forwardHeaders(req: Request, extra: Record<string, string> = {}): Headers {
  const h = new Headers({ "Content-Type": "application/json", Accept: "application/json", ...extra });
  const xff = req.headers.get("x-forwarded-for");
  if (xff) h.set("X-Forwarded-For", xff);
  return h;
}

async function callApi(
  fetchImpl: Fetch,
  path: string,
  init: RequestInit,
): Promise<{ status: number; body: unknown } | null> {
  try {
    const res = await fetchImpl(`${serverApiBaseUrl()}/api/v1${path}`, { ...init, cache: "no-store" });
    const text = await res.text();
    let body: unknown = null;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      body = null;
    }
    return { status: res.status, body };
  } catch {
    return null;
  }
}

const UNREACHABLE = { detail: "The MediaVault server could not be reached." };
const FORBIDDEN = { detail: "Cross-site request blocked." };

function detailOf(body: unknown, fallback: string): { detail: unknown } {
  if (body && typeof body === "object" && "detail" in body) {
    return { detail: (body as { detail: unknown }).detail };
  }
  return { detail: fallback };
}

async function readJson(req: Request): Promise<Record<string, unknown> | null> {
  try {
    const body = await req.json();
    return body && typeof body === "object" ? (body as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function credentials(body: Record<string, unknown> | null): { email: string; password: string } | null {
  if (!body || typeof body.email !== "string" || typeof body.password !== "string") return null;
  return { email: body.email, password: body.password };
}

export async function handleRegister(req: Request, fetchImpl: Fetch = fetch): Promise<Response> {
  if (!isSameOrigin(req)) return json(FORBIDDEN, 403);
  const creds = credentials(await readJson(req));
  if (!creds) return json({ detail: "Email and password are required." }, 400);
  const res = await callApi(fetchImpl, "/auth/register", {
    method: "POST",
    headers: forwardHeaders(req),
    body: JSON.stringify(creds),
  });
  if (!res) return json(UNREACHABLE, 502);
  return json(detailOf(res.body, "Registration failed."), res.status);
}

export async function handleLogin(req: Request, fetchImpl: Fetch = fetch): Promise<Response> {
  if (!isSameOrigin(req)) return json(FORBIDDEN, 403);
  const creds = credentials(await readJson(req));
  if (!creds) return json({ detail: "Email and password are required." }, 400);
  const res = await callApi(fetchImpl, "/auth/login", {
    method: "POST",
    headers: forwardHeaders(req),
    body: JSON.stringify(creds),
  });
  if (!res) return json(UNREACHABLE, 502);
  if (res.status !== 200) return json(detailOf(res.body, "Sign-in failed."), res.status);
  // Tokens go into httpOnly cookies only; the browser receives no token in the body.
  return json({ ok: true }, 200, tokenCookies(res.body as TokenResponse));
}

export async function handleLogout(req: Request, fetchImpl: Fetch = fetch): Promise<Response> {
  if (!isSameOrigin(req)) return json(FORBIDDEN, 403);
  const access = readCookie(req, ACCESS_COOKIE);
  const refresh = readCookie(req, REFRESH_COOKIE);
  if (access || refresh) {
    // Best effort: cookies are cleared even if the API is unreachable.
    await callApi(fetchImpl, "/auth/logout", {
      method: "POST",
      headers: forwardHeaders(req, access ? { Authorization: `Bearer ${access}` } : {}),
      body: JSON.stringify({ refresh_token: refresh ?? null }),
    });
  }
  return json(null, 204, clearCookies());
}

type RefreshResult =
  | { kind: "ok"; tokens: TokenResponse }
  | { kind: "rejected" }
  | { kind: "unreachable" };

/**
 * Single-flight refresh, per server process: overlapping requests that carry the SAME refresh
 * cookie share one upstream /auth/refresh call and therefore receive byte-identical Set-Cookie
 * headers, so neither response can overwrite the other with an older pair. Entries live only while
 * the call is in flight (no tokens are retained afterwards). Across several website processes the
 * API's bounded concurrency grace returns the same successor refresh token instead.
 */
const inflightRefresh = new Map<string, Promise<RefreshResult>>();

function refreshKey(refresh: string): string {
  return createHash("sha256").update(refresh).digest("hex");
}

/** Visible for tests: how many refreshes are currently in flight. */
export function inflightRefreshCount(): number {
  return inflightRefresh.size;
}

function refreshOnce(req: Request, refresh: string, fetchImpl: Fetch): Promise<RefreshResult> {
  const key = refreshKey(refresh);
  const existing = inflightRefresh.get(key);
  if (existing) return existing;
  const flight = (async (): Promise<RefreshResult> => {
    const rotated = await callApi(fetchImpl, "/auth/refresh", {
      method: "POST",
      headers: forwardHeaders(req),
      body: JSON.stringify({ refresh_token: refresh }),
    });
    if (!rotated) return { kind: "unreachable" };
    if (rotated.status !== 200) return { kind: "rejected" };
    return { kind: "ok", tokens: rotated.body as TokenResponse };
  })().finally(() => inflightRefresh.delete(key));
  inflightRefresh.set(key, flight);
  return flight;
}

/**
 * Current user. Transparently rotates the refresh token when the access token has expired.
 * Cookies are only written when a refresh actually happened; a request whose access cookie is
 * still valid never emits Set-Cookie, so a slow plain request cannot replace a newer pair.
 */
export async function handleMe(req: Request, fetchImpl: Fetch = fetch): Promise<Response> {
  const access = readCookie(req, ACCESS_COOKIE);
  const refresh = readCookie(req, REFRESH_COOKIE);
  if (access) {
    const me = await callApi(fetchImpl, "/auth/me", {
      method: "GET",
      headers: forwardHeaders(req, { Authorization: `Bearer ${access}` }),
    });
    if (!me) return json(UNREACHABLE, 502);
    if (me.status === 200) return json(me.body, 200);
  }
  if (!refresh) return json({ detail: "Not signed in." }, 401, access ? clearCookies() : []);
  const result = await refreshOnce(req, refresh, fetchImpl);
  if (result.kind === "unreachable") return json(UNREACHABLE, 502);
  // Rejected = expired, logged out, or replayed outside the API's concurrency grace (which
  // revokes the session server-side), so there is no newer valid pair left to protect.
  if (result.kind === "rejected") return json({ detail: "Not signed in." }, 401, clearCookies());
  const tokens = result.tokens;
  const me = await callApi(fetchImpl, "/auth/me", {
    method: "GET",
    headers: forwardHeaders(req, { Authorization: `Bearer ${tokens.access_token}` }),
  });
  if (!me) return json(UNREACHABLE, 502);
  if (me.status !== 200) return json({ detail: "Not signed in." }, 401, clearCookies());
  return json(me.body, 200, tokenCookies(tokens));
}
