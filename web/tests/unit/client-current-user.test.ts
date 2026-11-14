import { describe, expect, it, vi } from "vitest";

import { fetchCurrentUser } from "@/lib/auth/client";

describe("fetchCurrentUser", () => {
  it("shares one in-flight /api/auth/me between concurrent callers", async () => {
    let resolve!: (r: Response) => void;
    const fetchImpl = vi.fn(() => new Promise<Response>((r) => (resolve = r)));
    const a = fetchCurrentUser(fetchImpl as unknown as typeof fetch);
    const b = fetchCurrentUser(fetchImpl as unknown as typeof fetch);
    resolve(new Response(JSON.stringify({ id: "u1", email: "a@example.com" }), { status: 200 }));
    expect(await a).toEqual({ id: "u1", email: "a@example.com" });
    expect(await b).toEqual({ id: "u1", email: "a@example.com" });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("starts a new request once the previous one finished, and maps 401 to null", async () => {
    const fetchImpl = vi.fn(async () => new Response("{}", { status: 401 }));
    expect(await fetchCurrentUser(fetchImpl as unknown as typeof fetch)).toBeNull();
    expect(await fetchCurrentUser(fetchImpl as unknown as typeof fetch)).toBeNull();
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });
});
