import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HealthStatus } from "@/components/HealthStatus";

const body = (database: "ok" | "error") => ({
  status: database === "ok" ? "ok" : "degraded",
  service: "mediavault-api",
  version: "0.1.0",
  environment: "test",
  checks: { database },
  time: "2026-11-12T16:00:00Z",
});

function wrap(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

afterEach(() => vi.unstubAllGlobals());

describe("HealthStatus", () => {
  it("shows a loading state first, then connected", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(body("ok")))));
    wrap(<HealthStatus />);
    expect(screen.getByText(/Checking the MediaVault server/)).toBeInTheDocument();
    expect(await screen.findByText("Backend connected")).toBeInTheDocument();
    expect(screen.getByText("mediavault-api")).toBeInTheDocument();
  });

  it("shows the degraded state when the database is down", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(body("error")), { status: 503 })),
    );
    wrap(<HealthStatus />);
    expect(await screen.findByText(/database unavailable/)).toBeInTheDocument();
  });

  it("shows an error with a working retry button when unreachable", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(new Response(JSON.stringify(body("ok"))));
    vi.stubGlobal("fetch", fetchMock);
    wrap(<HealthStatus />);
    expect(await screen.findByText("Backend unreachable")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Check again" }));
    expect(await screen.findByText("Backend connected")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
