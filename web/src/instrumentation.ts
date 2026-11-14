/** Runs once when a Next.js server process starts. */
export async function register(): Promise<void> {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;
  const { trustedProxyWarning } = await import("@/lib/auth/deployWarnings");
  const warning = trustedProxyWarning(process.env);
  if (warning) console.warn(warning);
}
