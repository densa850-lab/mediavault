import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ACCESS_COOKIE,
  CLIENT_IP_HEADER,
  REFRESH_COOKIE,
  handleLogin,
  handleLogout,
  handleMe,
  handleRegister,
  isSameOrigin,
  readCookie,
  serializeCookie,
  trustedClientIp,
} from "@/lib/auth/bff";

const SITE = "http://localhost:3000";
const tokens = {
  access_token: "acc-1",
  token_type: "bearer",
  expires_in: 900,
  refresh_token: "ref-1",
  refresh_expires_in: 2592000,
};

function req(path: string, init: { method?: string; body?: unknown; origin?: string | null; cookie?: string } = {}) {
  const headers = new Headers({ host: "localhost:3000", "content-type": "application/json" });
  if (init.origin !== null) headers.set("origin", init.origin ?? SITE);
  if (init.cookie) headers.set("cookie", init.cookie);
  return new Request(`${SITE}${path}`, {
    method: init.method ?? "POST",
    headers,
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  });
}

const api = (status: number, body: unknown) =>
  new Response(body === null ? null : JSON.stringify(body), { status });

function setCookies(res: Response): string[] {
  return res.headers.getSetCookie();
}

afterEach(() => vi.unstubAllEnvs());

describe("cookies", () => {
  it("are httpOnly and SameSite=Strict, and Secure in production", () => {
    vi.stubEnv("NODE_ENV", "development");
    const dev = serializeCookie("a", "b", { maxAge: 60, path: "/" });
    expect(dev).toContain("HttpOnly");
    expect(dev).toContain("SameSite=Strict");
    expect(dev).not.toContain("Secure");
    vi.stubEnv("NODE_ENV", "production");
    expect(serializeCookie("a", "b", { maxAge: 60, path: "/" })).toContain("Secure");
  });

  it("reads a cookie from the request", () => {
    const r = req("/x", { cookie: `${ACCESS_COOKIE}=abc; other=1` });
    expect(readCookie(r, ACCESS_COOKIE)).toBe("abc");
    expect(readCookie(r, REFRESH_COOKIE)).toBeUndefined();
  });
});

describe("CSRF origin check", () => {
  it("accepts same origin and rejects others or missing", () => {
    expect(isSameOrigin(req("/x"))).toBe(true);
    expect(isSameOrigin(req("/x", { origin: "https://evil.example" }))).toBe(false);
    expect(isSameOrigin(req("/x", { origin: null }))).toBe(false);
  });

  it("blocks cross-site login, register and logout before calling the API", async () => {
    const fetchImpl = vi.fn();
    for (const h of [handleLogin, handleRegister, handleLogout]) {
      const res = await h(req("/api/auth/x", { origin: "https://evil.example", body: {} }), fetchImpl);
      expect(res.status).toBe(403);
    }
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});

describe("login", () => {
  it("puts tokens in httpOnly cookies and never in the response body", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(api(200, tokens));
    const res = await handleLogin(
      req("/api/auth/login", { body: { email: "a@example.com", password: "long-enough-pw" } }),
      fetchImpl,
    );
    expect(res.status).toBe(200);
    const text = await res.text();
    expect(text).not.toContain("acc-1");
    expect(text).not.toContain("ref-1");
    const cookies = setCookies(res);
    expect(cookies.find((c) => c.startsWith(`${ACCESS_COOKIE}=acc-1`))).toMatch(/HttpOnly.*SameSite=Strict/);
    const refresh = cookies.find((c) => c.startsWith(`${REFRESH_COOKIE}=ref-1`));
    expect(refresh).toContain("Path=/api/auth");
    expect(refresh).toContain("Max-Age=2592000");
    expect(fetchImpl.mock.calls[0][0]).toBe("http://localhost:8000/api/v1/auth/login");
  });

  it("passes the generic error through and sets no cookies", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(api(401, { detail: "Invalid email or password." }));
    const res = await handleLogin(
      req("/api/auth/login", { body: { email: "a@example.com", password: "x" } }),
      fetchImpl,
    );
    expect(res.status).toBe(401);
    expect(await res.json()).toEqual({ detail: "Invalid email or password." });
    expect(setCookies(res)).toEqual([]);
  });

  it("reports an unreachable API as 502", async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new TypeError("fetch failed"));
    const res = await handleLogin(
      req("/api/auth/login", { body: { email: "a@example.com", password: "long-enough-pw" } }),
      fetchImpl,
    );
    expect(res.status).toBe(502);
  });

  it("rejects a malformed body", async () => {
    const res = await handleLogin(req("/api/auth/login", { body: { email: 1 } }), vi.fn());
    expect(res.status).toBe(400);
  });
});

describe("register", () => {
  it("forwards to the API and returns its generic message", async () => {
    const detail = "If this email can be used, the account is ready. Sign in to continue.";
    const fetchImpl = vi.fn().mockResolvedValue(api(202, { detail }));
    const res = await handleRegister(
      req("/api/auth/register", { body: { email: "a@example.com", password: "long-enough-pw" } }),
      fetchImpl,
    );
    expect(res.status).toBe(202);
    expect(await res.json()).toEqual({ detail });
  });
});

describe("me", () => {
  it("returns the user with a valid access cookie", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(api(200, { id: "u1", email: "a@example.com" }));
    const res = await handleMe(req("/api/auth/me", { method: "GET", cookie: `${ACCESS_COOKIE}=acc-1` }), fetchImpl);
    expect(res.status).toBe(200);
    expect(fetchImpl.mock.calls[0][1].headers.get("Authorization")).toBe("Bearer acc-1");
  });

  it("rotates the refresh token when the access token has expired", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(api(401, { detail: "Not authenticated." }))
      .mockResolvedValueOnce(api(200, { ...tokens, access_token: "acc-2", refresh_token: "ref-2" }))
      .mockResolvedValueOnce(api(200, { id: "u1", email: "a@example.com" }));
    const res = await handleMe(
      req("/api/auth/me", { method: "GET", cookie: `${ACCESS_COOKIE}=old; ${REFRESH_COOKIE}=ref-1` }),
      fetchImpl,
    );
    expect(res.status).toBe(200);
    expect(JSON.parse(fetchImpl.mock.calls[1][1].body)).toEqual({ refresh_token: "ref-1" });
    const cookies = setCookies(res);
    expect(cookies.some((c) => c.startsWith(`${ACCESS_COOKIE}=acc-2`))).toBe(true);
    expect(cookies.some((c) => c.startsWith(`${REFRESH_COOKIE}=ref-2`))).toBe(true);
  });

  it("clears cookies when the refresh is rejected (revoked or reused)", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(api(401, {}))
      .mockResolvedValueOnce(api(401, { detail: "Session expired. Sign in again." }));
    const res = await handleMe(
      req("/api/auth/me", { method: "GET", cookie: `${ACCESS_COOKIE}=old; ${REFRESH_COOKIE}=ref-1` }),
      fetchImpl,
    );
    expect(res.status).toBe(401);
    expect(setCookies(res).every((c) => c.includes("Max-Age=0"))).toBe(true);
  });

  it("is 401 without any cookie and does not call the API", async () => {
    const fetchImpl = vi.fn();
    const res = await handleMe(req("/api/auth/me", { method: "GET" }), fetchImpl);
    expect(res.status).toBe(401);
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});

describe("logout", () => {
  it("revokes on the API with both tokens and clears cookies", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(api(204, null));
    const res = await handleLogout(
      req("/api/auth/logout", { cookie: `${ACCESS_COOKIE}=acc-1; ${REFRESH_COOKIE}=ref-1` }),
      fetchImpl,
    );
    expect(res.status).toBe(204);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("http://localhost:8000/api/v1/auth/logout");
    expect(init.headers.get("Authorization")).toBe("Bearer acc-1");
    expect(JSON.parse(init.body)).toEqual({ refresh_token: "ref-1" });
    expect(setCookies(res)).toHaveLength(2);
    expect(setCookies(res).every((c) => c.includes("Max-Age=0"))).toBe(true);
  });

  it("still clears cookies when the API is down", async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new TypeError("down"));
    const res = await handleLogout(req("/api/auth/logout", { cookie: `${REFRESH_COOKIE}=ref-1` }), fetchImpl);
    expect(res.status).toBe(204);
    expect(setCookies(res)).toHaveLength(2);
  });
});

describe("client IP forwarding (MV-016)", () => {
  const body = { email: "a@example.com", password: "long-enough-pw" };
  function withHeaders(extra: Record<string, string>) {
    const r = req("/api/auth/login", { body });
    const headers = new Headers(r.headers);
    for (const [k, v] of Object.entries(extra)) headers.set(k, v);
    return new Request(r.url, { method: "POST", headers, body: JSON.stringify(body) });
  }
  async function sentHeaders(extra: Record<string, string>): Promise<Headers> {
    const fetchImpl = vi.fn().mockResolvedValue(api(200, tokens));
    await handleLogin(withHeaders(extra), fetchImpl);
    return fetchImpl.mock.calls[0][1].headers as Headers;
  }

  it("never forwards the browser's X-Forwarded-For or client-IP header", async () => {
    const sent = await sentHeaders({ "x-forwarded-for": "6.6.6.6", "x-mediavault-client-ip": "7.7.7.7" });
    expect(sent.get("x-forwarded-for")).toBeNull();
    expect(sent.get("x-mediavault-client-ip")).toBeNull();
  });

  it("by default sends no client IP, so rotating X-Forwarded-For changes nothing", async () => {
    const seen = new Set<string | null>();
    for (let i = 0; i < 5; i++) {
      const sent = await sentHeaders({ "x-forwarded-for": `198.51.100.${i}` });
      seen.add(sent.get(CLIENT_IP_HEADER));
      expect(sent.get("x-forwarded-for")).toBeNull();
    }
    expect([...seen]).toEqual([null]);
  });

  it("with WEB_TRUSTED_PROXY_HOPS=1 sends only the proxy-appended (right-most) address", async () => {
    vi.stubEnv("WEB_TRUSTED_PROXY_HOPS", "1");
    const sent = await sentHeaders({
      "x-forwarded-for": "6.6.6.6, 198.51.100.7",
      "x-mediavault-client-ip": "7.7.7.7",
    });
    expect(sent.get(CLIENT_IP_HEADER)).toBe("198.51.100.7");
    expect(sent.get("x-forwarded-for")).toBeNull();
  });

  it("with two trusted hops takes the second address from the right", () => {
    vi.stubEnv("WEB_TRUSTED_PROXY_HOPS", "2");
    const r = withHeaders({ "x-forwarded-for": "6.6.6.6, 198.51.100.7, 10.0.0.2" });
    expect(trustedClientIp(r)).toBe("198.51.100.7");
    expect(trustedClientIp(withHeaders({ "x-forwarded-for": "10.0.0.2" }))).toBeUndefined();
  });

  it("ignores malformed values and bad configuration", () => {
    vi.stubEnv("WEB_TRUSTED_PROXY_HOPS", "1");
    expect(trustedClientIp(withHeaders({ "x-forwarded-for": "not-an-ip" }))).toBeUndefined();
    expect(trustedClientIp(withHeaders({ "x-forwarded-for": "2001:db8::1" }))).toBe("2001:db8::1");
    expect(trustedClientIp(withHeaders({}))).toBeUndefined();
    vi.stubEnv("WEB_TRUSTED_PROXY_HOPS", "abc");
    expect(trustedClientIp(withHeaders({ "x-forwarded-for": "198.51.100.7" }))).toBeUndefined();
    vi.stubEnv("WEB_TRUSTED_PROXY_HOPS", "0");
    expect(trustedClientIp(withHeaders({ "x-forwarded-for": "198.51.100.7" }))).toBeUndefined();
  });
});
