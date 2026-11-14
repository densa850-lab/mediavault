/**
 * MV-023 / MV-024 (Tester's re-gate of PR #4): a temporary API answer (429, 5xx, network) while
 * refreshing must never sign the user out, and a sign-out the server didn't confirm is reported.
 */
import { describe, expect, it, vi } from "vitest";

import { ACCESS_COOKIE, REFRESH_COOKIE, handleLogout, handleMe } from "@/lib/auth/bff";
import { fetchCurrentUser, signOut } from "@/lib/auth/client";

const SITE = "http://localhost:3000";
const user = { id: "u1", email: "a@example.com" };
const pair = (n: number) => ({
  access_token: `acc-${n}`,
  token_type: "bearer",
  expires_in: 900,
  refresh_token: `ref-${n}`,
  refresh_expires_in: 2592000,
});

function meReq(cookie: string) {
  return new Request(`${SITE}/api/auth/me`, { method: "GET", headers: { host: "localhost:3000", cookie } });
}
function logoutReq(cookie: string) {
  return new Request(`${SITE}/api/auth/logout`, {
    method: "POST",
    headers: { host: "localhost:3000", origin: SITE, cookie, "content-type": "application/json" },
  });
}
const api = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(body === null ? null : JSON.stringify(body), { status, headers });
const cleared = (res: Response) => res.headers.getSetCookie().filter((c) => c.includes("Max-Age=0"));

describe("refresh answers that are temporary keep the session (MV-023)", () => {
  for (const [label, refreshAnswer] of [
    ["429", () => api(429, { detail: "Too many attempts. Try again later." }, { "Retry-After": "42" })],
    ["500", () => api(500, { detail: "boom" })],
    ["503", () => api(503, null)],
    ["network error", () => Promise.reject(new TypeError("fetch failed"))],
  ] as const) {
    it(`${label} on refresh -> 503, cookies kept`, async () => {
      const fetchImpl = vi
        .fn()
        .mockResolvedValueOnce(api(401, {}))
        .mockImplementationOnce(refreshAnswer as () => Promise<Response>);
      const res = await handleMe(meReq(`${ACCESS_COOKIE}=expired; ${REFRESH_COOKIE}=ref-1`), fetchImpl);
      expect(res.status).toBe(503);
      expect(res.headers.getSetCookie()).toEqual([]); // nothing cleared, nothing replaced
      expect((await res.json()).detail).toMatch(/still signed in/);
      if (label === "429") expect(res.headers.get("retry-after")).toBe("42");
    });
  }

  for (const status of [401, 422]) {
    it(`a definitive ${status} on refresh clears the cookies`, async () => {
      const fetchImpl = vi.fn().mockResolvedValueOnce(api(401, {})).mockResolvedValueOnce(api(status, {}));
      const res = await handleMe(meReq(`${ACCESS_COOKIE}=expired; ${REFRESH_COOKIE}=ref-1`), fetchImpl);
      expect(res.status).toBe(401);
      expect(cleared(res)).toHaveLength(2);
    });
  }

  it("a 5xx from /me with a valid access cookie neither refreshes nor clears", async () => {
    const fetchImpl = vi.fn().mockResolvedValueOnce(api(500, {}));
    const res = await handleMe(meReq(`${ACCESS_COOKIE}=acc-1; ${REFRESH_COOKIE}=ref-1`), fetchImpl);
    expect(res.status).toBe(503);
    expect(fetchImpl).toHaveBeenCalledTimes(1); // the refresh token was not spent
    expect(res.headers.getSetCookie()).toEqual([]);
  });

  it("stores the rotated pair even when /me fails temporarily right after the refresh", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(api(401, {}))
      .mockResolvedValueOnce(api(200, pair(2)))
      .mockResolvedValueOnce(api(502, null));
    const res = await handleMe(meReq(`${ACCESS_COOKIE}=expired; ${REFRESH_COOKIE}=ref-1`), fetchImpl);
    expect(res.status).toBe(503);
    const set = res.headers.getSetCookie();
    expect(set.some((c) => c.startsWith(`${REFRESH_COOKIE}=ref-2`))).toBe(true);
    expect(cleared(res)).toEqual([]);
  });
});

/**
 * Tester's attack end to end through the website handler: an anonymous attacker sends 31 junk
 * refresh cookies to /api/auth/me (all from the website server's one IP), then a real user whose
 * access cookie expired loads the page. Modelled against both server behaviours.
 */
class LimitedApi {
  failures = 0;
  live = "ref-1";
  gen = 1;
  constructor(
    private limit: number,
    private blockValidToo: boolean, // true = the d68cc5a server bug, false = the fixed server
  ) {}
  fetch = async (url: string | URL | Request, init?: RequestInit): Promise<Response> => {
    const path = String(url);
    if (path.endsWith("/auth/me")) {
      const auth = new Headers(init?.headers).get("Authorization");
      return auth === `Bearer acc-${this.gen}` && this.gen > 1 ? api(200, user) : api(401, {});
    }
    const token = JSON.parse(String(init?.body)).refresh_token as string;
    const valid = token === this.live;
    if (valid && !(this.blockValidToo && this.failures >= this.limit)) {
      this.gen += 1;
      this.live = `ref-${this.gen}`;
      return api(200, pair(this.gen));
    }
    if (!valid) this.failures += 1;
    if (this.failures > this.limit) return api(429, { detail: "Too many attempts." }, { "Retry-After": "60" });
    return api(401, { detail: "Session expired. Sign in again." });
  };
}

async function attack(apiModel: LimitedApi) {
  const junk = [];
  for (let i = 0; i < 31; i++) {
    junk.push(await handleMe(meReq(`${REFRESH_COOKIE}=garbage-${i}`), apiModel.fetch as typeof fetch));
  }
  const victim = await handleMe(meReq(`${ACCESS_COOKIE}=expired; ${REFRESH_COOKIE}=ref-1`), apiModel.fetch as typeof fetch);
  return { junk, victim };
}

describe("Tester's MV-023 attack: 31 junk refresh cookies, then a real user", () => {
  it("against the fixed API the real user stays signed in and gets a new pair", async () => {
    const { junk, victim } = await attack(new LimitedApi(30, false));
    expect(junk.at(-1)!.status).toBe(503); // junk is throttled (429 upstream)...
    expect(victim.status).toBe(200); // ...but the valid refresh is not
    expect(victim.headers.getSetCookie().some((c) => c.startsWith(`${REFRESH_COOKIE}=ref-2`))).toBe(true);
  });

  it("even against an API that wrongly 429s valid tokens, the website no longer signs the user out", async () => {
    const { victim } = await attack(new LimitedApi(30, true));
    expect(victim.status).toBe(503);
    expect(cleared(victim)).toEqual([]); // cookies kept: the next try can still succeed
  });
});

describe("sign-out the server did not confirm (MV-024)", () => {
  it("retries once on 429 and succeeds", async () => {
    const fetchImpl = vi.fn().mockResolvedValueOnce(api(429, {})).mockResolvedValueOnce(api(204, null));
    const res = await handleLogout(logoutReq(`${ACCESS_COOKIE}=acc-1; ${REFRESH_COOKIE}=ref-1`), fetchImpl);
    expect(res.status).toBe(204);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(cleared(res)).toHaveLength(2);
  });

  it("reports an unconfirmed revoke (but still clears cookies) after two 429s", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(api(429, {}));
    const res = await handleLogout(logoutReq(`${ACCESS_COOKIE}=acc-1; ${REFRESH_COOKIE}=ref-1`), fetchImpl);
    expect(res.status).toBe(502);
    expect(cleared(res)).toHaveLength(2);
  });
});

describe("browser client", () => {
  it("fetchCurrentUser treats 503 as a retryable error, not as signed out", async () => {
    const fetchImpl = vi.fn(async () => api(503, { detail: "The MediaVault server is busy. You are still signed in; try again in a moment." }));
    await expect(fetchCurrentUser(fetchImpl as unknown as typeof fetch)).rejects.toThrow(/still signed in/);
  });

  it("signOut reports whether the server confirmed", async () => {
    const ok = vi.fn(async () => api(204, null));
    expect(await signOut(ok as unknown as typeof fetch)).toEqual({ confirmed: true });
    const unconfirmed = vi.fn(async () => api(502, { detail: "Signed out on this device, but the server did not confirm." }));
    const r = await signOut(unconfirmed as unknown as typeof fetch);
    expect(r.confirmed).toBe(false);
    const down = vi.fn(async () => {
      throw new TypeError("offline");
    });
    expect((await signOut(down as unknown as typeof fetch)).confirmed).toBe(false);
  });
});
