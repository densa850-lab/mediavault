/** Browser-side calls to the website's own /api/auth route handlers (same origin, cookies). */

export const MIN_PASSWORD_LENGTH = 12;

export interface CurrentUser {
  id: string;
  email: string;
}

export type AuthResult = { ok: true } | { ok: false; message: string };

function messageFrom(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail[0] && typeof detail[0].msg === "string") {
      return String(detail[0].msg).replace(/^Value error, /, "");
    }
  }
  return fallback;
}

async function post(path: string, body?: unknown, fetchImpl: typeof fetch = fetch): Promise<Response> {
  return fetchImpl(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export async function submitAuth(
  mode: "login" | "register",
  email: string,
  password: string,
  fetchImpl: typeof fetch = fetch,
): Promise<AuthResult> {
  if (mode === "register" && password.length < MIN_PASSWORD_LENGTH) {
    return { ok: false, message: `Password must be at least ${MIN_PASSWORD_LENGTH} characters.` };
  }
  let res: Response;
  try {
    res = await post(`/api/auth/${mode}`, { email, password }, fetchImpl);
  } catch {
    return { ok: false, message: "The MediaVault server could not be reached." };
  }
  if (res.ok) return { ok: true };
  const body = await res.json().catch(() => null);
  if (res.status === 429) return { ok: false, message: "Too many attempts. Try again later." };
  return { ok: false, message: messageFrom(body, mode === "login" ? "Sign-in failed." : "Registration failed.") };
}

let currentUserFlight: Promise<CurrentUser | null> | null = null;

/**
 * Who is signed in. Concurrent callers in the same page share one request, so the browser never
 * sends two overlapping /api/auth/me calls that could both refresh.
 */
export function fetchCurrentUser(fetchImpl: typeof fetch = fetch): Promise<CurrentUser | null> {
  if (currentUserFlight) return currentUserFlight;
  const flight = (async () => {
    const res = await fetchImpl("/api/auth/me", { credentials: "same-origin", cache: "no-store" });
    if (res.status === 401) return null;
    if (!res.ok) {
      // Anything but 401 is temporary (busy, unreachable): the session is kept, so let the caller
      // offer a retry instead of treating the user as signed out (MV-023).
      const body = await res.json().catch(() => null);
      throw new Error(messageFrom(body, "The MediaVault server could not be reached."));
    }
    const body = (await res.json()) as CurrentUser;
    return { id: body.id, email: body.email };
  })().finally(() => {
    currentUserFlight = null;
  });
  currentUserFlight = flight;
  return flight;
}

export type SignOutResult = { confirmed: true } | { confirmed: false; message: string };

/** Signs out. The website always clears its cookies; `confirmed` says whether the server revoked. */
export async function signOut(fetchImpl: typeof fetch = fetch): Promise<SignOutResult> {
  const fallback = "Signed out on this device, but the server could not be reached to end the session.";
  try {
    const res = await post("/api/auth/logout", undefined, fetchImpl);
    if (res.ok) return { confirmed: true };
    return { confirmed: false, message: messageFrom(await res.json().catch(() => null), fallback) };
  } catch {
    return { confirmed: false, message: fallback };
  }
}
