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

export async function fetchCurrentUser(fetchImpl: typeof fetch = fetch): Promise<CurrentUser | null> {
  const res = await fetchImpl("/api/auth/me", { credentials: "same-origin", cache: "no-store" });
  if (res.status === 401) return null;
  if (!res.ok) throw new Error("The MediaVault server could not be reached.");
  const body = (await res.json()) as CurrentUser;
  return { id: body.id, email: body.email };
}

export async function signOut(fetchImpl: typeof fetch = fetch): Promise<void> {
  await post("/api/auth/logout", undefined, fetchImpl);
}
