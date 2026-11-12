"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchHealth, type Health } from "@/lib/health";

type View =
  | { kind: "loading" }
  | { kind: "connected"; health: Health }
  | { kind: "degraded"; health: Health }
  | { kind: "error"; message: string };

function toView(
  isPending: boolean,
  data: Health | undefined,
  error: Error | null,
): View {
  if (isPending) return { kind: "loading" };
  if (error || !data) return { kind: "error", message: error?.message ?? "Unknown error" };
  return data.status === "ok" ? { kind: "connected", health: data } : { kind: "degraded", health: data };
}

const DOT: Record<View["kind"], string> = {
  loading: "bg-slate-300 animate-pulse",
  connected: "bg-emerald-500",
  degraded: "bg-amber-500",
  error: "bg-red-500",
};

const TITLE: Record<View["kind"], string> = {
  loading: "Checking the MediaVault server…",
  connected: "Backend connected",
  degraded: "Backend reachable, database unavailable",
  error: "Backend unreachable",
};

export function HealthStatus() {
  const { isPending, data, error, refetch, isFetching } = useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) => fetchHealth(fetch, signal),
    retry: false,
  });
  const view = toView(isPending, data, error);

  return (
    <section
      aria-labelledby="health-title"
      aria-live="polite"
      className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-900"
    >
      <div className="flex items-center gap-3">
        <span aria-hidden className={`h-3 w-3 rounded-full ${DOT[view.kind]}`} />
        <h2 id="health-title" className="text-lg font-semibold">
          {TITLE[view.kind]}
        </h2>
      </div>

      {view.kind === "connected" || view.kind === "degraded" ? (
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-sm text-slate-600 dark:text-slate-300">
          <dt>Service</dt>
          <dd>{view.health.service}</dd>
          <dt>Version</dt>
          <dd>{view.health.version}</dd>
          <dt>Environment</dt>
          <dd>{view.health.environment}</dd>
          <dt>Database</dt>
          <dd>{view.health.checks.database === "ok" ? "OK" : "Error"}</dd>
        </dl>
      ) : null}

      {view.kind === "error" ? (
        <p className="mt-3 text-sm text-slate-600 dark:text-slate-300">
          {view.message} Make sure the backend is running on port 8000.
        </p>
      ) : null}

      {view.kind !== "loading" ? (
        <button
          type="button"
          onClick={() => void refetch()}
          disabled={isFetching}
          className="mt-4 rounded-xl bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:opacity-60"
        >
          {isFetching ? "Checking…" : "Check again"}
        </button>
      ) : null}
    </section>
  );
}
