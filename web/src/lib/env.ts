/**
 * Public runtime configuration. NEXT_PUBLIC_* values are inlined into the browser bundle
 * at build time, so they must never contain secrets.
 */
const DEFAULT_API_BASE_URL = "http://localhost:8000";

export function apiBaseUrl(): string {
  const raw = process.env.NEXT_PUBLIC_API_BASE_URL?.trim() || DEFAULT_API_BASE_URL;
  return raw.replace(/\/+$/, "");
}
