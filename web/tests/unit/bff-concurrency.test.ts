/**
 * Concurrent /api/auth/me with an expired access cookie and the same refresh cookie
 * (two tabs, or a page firing two requests). The fake API below models the real server
 * protocol: single-use refresh tokens, reuse detection that revokes the session, and the
 * bounded concurrency grace that returns the same successor for the just-rotated token.
 */
import { describe, expect, it, vi } from "vitest";

import { ACCESS_COOKIE, REFRESH_COOKIE, handleMe, inflightRefreshCount } from "@/lib/auth/bff";

const SITE = "http://localhost:3000";

function meReq(cookies: Record<string, string>) {
  const headers = new Headers({ host: "localhost:3000" });
  headers.set(
    "cookie",
    Object.entries(cookies)
      .map(([k, v]) => `${k}=${v}`)
      .join("; "),
  );
  return new Request(`${SITE}/api/auth/me`, { method: "GET", headers });
}

function cookieValue(res: Response, name: string): string | undefined {
  for (const c of res.headers.getSetCookie()) {
    if (c.startsWith(`${name}=`)) return decodeURIComponent(c.slice(name.length + 1).split(";")[0]);
  }
  return undefined;
}

/** In-memory model of the MediaVault API auth protocol, with controllable latency. */
class FakeApi {
  revoked = false;
  refreshCalls = 0;
  private gen = 0;
  private live = "ref-0"; // current unused refresh token
  private justRotated: { from: string; to: string; at: number } | null = null;
  private validAccess = new Set<string>(["acc-valid"]);
  now = 0;
  graceMs = 10_000;
  /** Resolve order control: each upstream call waits for its gate before answering. */
  gates: Array<() => void> = [];
  delay = false;

  fetch = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const path = String(url).replace(/^.*\/api\/v1/, "");
    if (this.delay) await new Promise<void>((resolve) => this.gates.push(resolve));
    if (path === "/auth/me") {
      const auth = new Headers(init?.headers).get("Authorization") ?? "";
      const token = auth.replace("Bearer ", "");
      if (!this.revoked && this.validAccess.has(token)) {
        return new Response(JSON.stringify({ id: "u1", email: "a@example.com" }), { status: 200 });
      }
      return new Response(JSON.stringify({ detail: "Not authenticated." }), { status: 401 });
    }
    if (path === "/auth/refresh") {
      this.refreshCalls += 1;
      const presented = JSON.parse(String(init?.body)).refresh_token as string;
      return this.refresh(presented);
    }
    throw new Error(`unexpected ${path}`);
  });

  private pair(refresh: string) {
    const access = `acc-${++this.gen}`;
    this.validAccess.add(access);
    return new Response(
      JSON.stringify({ access_token: access, expires_in: 900, refresh_token: refresh, refresh_expires_in: 1000 }),
      { status: 200 },
    );
  }

  private refresh(presented: string): Response {
    const reject = () => new Response(JSON.stringify({ detail: "Session expired. Sign in again." }), { status: 401 });
    if (this.revoked) return reject();
    if (presented === this.live) {
      const next = `ref-${this.gen + 1}-succ`;
      this.justRotated = { from: presented, to: next, at: this.now };
      this.live = next;
      return this.pair(next);
    }
    const jr = this.justRotated;
    if (jr && jr.from === presented && jr.to === this.live && this.now - jr.at <= this.graceMs) {
      return this.pair(jr.to); // concurrency grace: same successor
    }
    this.revoked = true; // replay outside the grace case
    return reject();
  }

  /** Release pending upstream calls in the given order (indexes into the pending list). */
  async release(order: number[]) {
    const pending = [...this.gates];
    const chosen = order.map((i) => pending[i]);
    // Calls not released stay pending (newly started calls are appended after them).
    this.gates = pending.filter((_, i) => !order.includes(i));
    for (const resolve of chosen) {
      resolve();
      await new Promise((r) => setTimeout(r, 5));
    }
  }
}

const tick = () => new Promise((r) => setTimeout(r, 5));

describe("concurrent /api/auth/me", () => {
  it("two overlapping requests with an expired access cookie share one refresh and keep the session", async () => {
    const apiA = new FakeApi();
    const cookies = { [ACCESS_COOKIE]: "acc-expired", [REFRESH_COOKIE]: "ref-0" };
    apiA.delay = true;
    const p1 = handleMe(meReq(cookies), apiA.fetch);
    const p2 = handleMe(meReq(cookies), apiA.fetch);
    await tick();
    // Both /me calls with the expired access token are pending.
    await apiA.release([1, 0]);
    await tick();
    expect(inflightRefreshCount()).toBe(1); // one shared refresh flight
    await apiA.release([0]); // the single refresh
    await tick();
    await apiA.release([1, 0]); // both follow-up /me calls, answered in reverse order
    const [r1, r2] = await Promise.all([p1, p2]);

    expect(r1.status).toBe(200);
    expect(r2.status).toBe(200);
    expect(apiA.refreshCalls).toBe(1);
    expect(apiA.revoked).toBe(false);
    // Byte-identical cookie pairs: whichever response the browser applies last, it holds the
    // newest pair, so an older response cannot overwrite a newer one.
    expect(r1.headers.getSetCookie()).toEqual(r2.headers.getSetCookie());
    expect(cookieValue(r1, REFRESH_COOKIE)).toBe("ref-1-succ");
    expect(inflightRefreshCount()).toBe(0); // nothing retained after the flight
  });

  it("two website processes (no shared memory) still keep the session via the API grace", async () => {
    const api = new FakeApi();
    vi.resetModules();
    const instanceB = await import("@/lib/auth/bff");
    const cookies = { [ACCESS_COOKIE]: "acc-expired", [REFRESH_COOKIE]: "ref-0" };
    const [r1, r2] = await Promise.all([
      handleMe(meReq(cookies), api.fetch),
      instanceB.handleMe(meReq(cookies), api.fetch),
    ]);
    expect(r1.status).toBe(200);
    expect(r2.status).toBe(200);
    expect(api.refreshCalls).toBe(2);
    expect(api.revoked).toBe(false);
    // Same successor refresh token in both responses (access tokens may differ; both are valid).
    expect(cookieValue(r1, REFRESH_COOKIE)).toBe(cookieValue(r2, REFRESH_COOKIE));
    const later = await handleMe(
      meReq({ [ACCESS_COOKIE]: "acc-expired", [REFRESH_COOKIE]: cookieValue(r1, REFRESH_COOKIE)! }),
      api.fetch,
    );
    expect(later.status).toBe(200);
  });

  it("a slow request that did not refresh never emits Set-Cookie, so it cannot replace the newer pair", async () => {
    const api = new FakeApi();
    api.delay = true;
    const slowPlain = handleMe(meReq({ [ACCESS_COOKIE]: "acc-valid", [REFRESH_COOKIE]: "ref-0" }), api.fetch);
    const refreshing = handleMe(meReq({ [ACCESS_COOKIE]: "acc-expired", [REFRESH_COOKIE]: "ref-0" }), api.fetch);
    await tick();
    // Pending: [plain /me, refreshing /me]. The plain request stays slow at index 0 throughout.
    await api.release([1]); // refreshing request's /me -> 401
    await tick();
    await api.release([1]); // its refresh
    await tick();
    await api.release([1]); // its follow-up /me
    const fresh = await refreshing;
    expect(cookieValue(fresh, REFRESH_COOKIE)).toBe("ref-1-succ");
    await api.release([0]); // finally the slow plain request completes
    const stale = await slowPlain;
    expect(stale.status).toBe(200);
    expect(stale.headers.getSetCookie()).toEqual([]);
  });

  it("a replayed old refresh cookie outside the grace is rejected and cookies are cleared", async () => {
    const api = new FakeApi();
    const first = await handleMe(meReq({ [ACCESS_COOKIE]: "acc-expired", [REFRESH_COOKIE]: "ref-0" }), api.fetch);
    expect(first.status).toBe(200);
    api.now += 11_000; // past the grace window
    const replay = await handleMe(meReq({ [ACCESS_COOKIE]: "acc-expired", [REFRESH_COOKIE]: "ref-0" }), api.fetch);
    expect(replay.status).toBe(401);
    expect(api.revoked).toBe(true);
    expect(cookieValue(replay, ACCESS_COOKIE)).toBe("");
    expect(cookieValue(replay, REFRESH_COOKIE)).toBe("");
  });

  it("an unreachable API during a shared refresh gives 503 (temporary) to every waiter and keeps cookies", async () => {
    let calls = 0;
    const fetchImpl = vi.fn(async (url: string | URL | Request) => {
      if (String(url).endsWith("/auth/me")) return new Response("{}", { status: 401 });
      calls += 1;
      await tick();
      throw new TypeError("fetch failed");
    });
    const cookies = { [ACCESS_COOKIE]: "acc-expired", [REFRESH_COOKIE]: "ref-x" };
    const [a, b] = await Promise.all([handleMe(meReq(cookies), fetchImpl), handleMe(meReq(cookies), fetchImpl)]);
    expect([a.status, b.status]).toEqual([503, 503]);
    expect(calls).toBe(1);
    expect(a.headers.getSetCookie()).toEqual([]);
    expect(inflightRefreshCount()).toBe(0);
  });
});
