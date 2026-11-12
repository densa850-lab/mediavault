import { z } from "zod";

import { apiBaseUrl } from "./env";

export const healthSchema = z.object({
  status: z.enum(["ok", "degraded"]),
  service: z.string(),
  version: z.string(),
  environment: z.string(),
  checks: z.object({ database: z.enum(["ok", "error"]) }),
  time: z.string(),
});

export type Health = z.infer<typeof healthSchema>;

export class BackendUnreachableError extends Error {
  constructor(message = "The MediaVault server could not be reached.") {
    super(message);
    this.name = "BackendUnreachableError";
  }
}

/**
 * Calls GET /api/v1/health. A 503 still carries a valid body (status "degraded"),
 * so it is returned rather than thrown; network failures and bad payloads throw.
 */
export async function fetchHealth(
  fetchImpl: typeof fetch = fetch,
  signal?: AbortSignal,
): Promise<Health> {
  let res: Response;
  try {
    res = await fetchImpl(`${apiBaseUrl()}/api/v1/health`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal,
    });
  } catch {
    throw new BackendUnreachableError();
  }
  if (res.status !== 200 && res.status !== 503) {
    throw new BackendUnreachableError(`Unexpected response from server (HTTP ${res.status}).`);
  }
  const parsed = healthSchema.safeParse(await res.json().catch(() => null));
  if (!parsed.success) {
    throw new BackendUnreachableError("The server sent an unexpected health response.");
  }
  return parsed.data;
}
