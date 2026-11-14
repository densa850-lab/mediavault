/**
 * Startup checks for the website's auth deployment (MV-025). Pure so it can be unit tested.
 *
 * With WEB_TRUSTED_PROXY_HOPS unset/0 the website can't tell its visitors apart (the browser
 * controls X-Forwarded-For), so it sends no client IP and the API rate-limits ALL website users
 * on the website server's one address: 20 login attempts per minute for the whole site.
 */
export function trustedProxyWarning(env: Record<string, string | undefined>): string | null {
  if (env.NODE_ENV !== "production") return null;
  const hops = Number(env.WEB_TRUSTED_PROXY_HOPS?.trim() || "0");
  if (Number.isInteger(hops) && hops >= 1 && hops <= 10) return null;
  return (
    "[mediavault] WEB_TRUSTED_PROXY_HOPS is not set (or invalid): all website users share ONE " +
    "login/register rate-limit bucket on the API. In production put the website behind a reverse " +
    "proxy that appends the client address to X-Forwarded-For, set WEB_TRUSTED_PROXY_HOPS to the " +
    "number of such proxies (usually 1), and set AUTH_TRUSTED_PROXIES on the API to this server's address."
  );
}
