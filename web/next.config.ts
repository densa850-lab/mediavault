import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV !== "production";

/** Origin of the public API (inlined at build time), allowed in connect-src. */
function apiOrigin(): string {
  const raw = process.env.NEXT_PUBLIC_API_BASE_URL?.trim() || "http://localhost:8000";
  try {
    return new URL(raw).origin;
  } catch {
    throw new Error("NEXT_PUBLIC_API_BASE_URL is not a valid absolute URL");
  }
}

// MV-005: security headers on every site response.
// script-src needs 'unsafe-inline' because the App Router streams inline bootstrap scripts and
// these pages are statically prerendered (a per-request nonce would force dynamic rendering).
// Dev additionally needs 'unsafe-eval' and websocket HMR.
const contentSecurityPolicy = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self'",
  `connect-src 'self' ${apiOrigin()}${isDev ? " ws: wss:" : ""}`,
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

export const securityHeaders = [
  { key: "Content-Security-Policy", value: contentSecurityPolicy },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
];

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  poweredByHeader: false,
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
