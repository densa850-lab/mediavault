import { afterEach, describe, expect, it, vi } from "vitest";

import { apiBaseUrl } from "@/lib/env";
import { BackendUnreachableError, fetchHealth } from "@/lib/health";

const okBody = {
  status: "ok",
  service: "mediavault-api",
  version: "0.1.0",
  environment: "test",
  checks: { database: "ok" },
  time: "2026-11-12T16:00:00Z",
};

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => vi.unstubAllEnvs());

describe("apiBaseUrl", () => {
  it("defaults to localhost:8000", () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "");
    expect(apiBaseUrl()).toBe("http://localhost:8000");
  });
  it("strips trailing slashes", () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example.test/");
    expect(apiBaseUrl()).toBe("https://api.example.test");
  });
});

describe("fetchHealth", () => {
  it("calls /api/v1/health and parses a healthy response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json(okBody));
    const health = await fetchHealth(fetchMock as unknown as typeof fetch);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/health",
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(health.status).toBe("ok");
  });

  it("returns a degraded body on 503 instead of throwing", async () => {
    const body = { ...okBody, status: "degraded", checks: { database: "error" } };
    const health = await fetchHealth(vi.fn().mockResolvedValue(json(body, 503)) as never);
    expect(health.checks.database).toBe("error");
  });

  it("throws BackendUnreachableError on network failure", async () => {
    const failing = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(fetchHealth(failing as never)).rejects.toBeInstanceOf(BackendUnreachableError);
  });

  it("throws on an unexpected payload", async () => {
    await expect(fetchHealth(vi.fn().mockResolvedValue(json({ hello: 1 })) as never)).rejects.toThrow(
      /unexpected health response/,
    );
  });

  it("throws on other HTTP statuses", async () => {
    await expect(fetchHealth(vi.fn().mockResolvedValue(json({}, 500)) as never)).rejects.toThrow(
      /HTTP 500/,
    );
  });
});
