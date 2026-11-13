import { describe, expect, it } from "vitest";

import nextConfig, { securityHeaders } from "../../next.config";

function header(name: string): string | undefined {
  return securityHeaders.find((h) => h.key.toLowerCase() === name.toLowerCase())?.value;
}

describe("site security headers (MV-005)", () => {
  it("sets a CSP that blocks framing, plugins and foreign scripts", () => {
    const csp = header("Content-Security-Policy");
    expect(csp).toBeDefined();
    expect(csp).toContain("default-src 'self'");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("object-src 'none'");
    expect(csp).toContain("base-uri 'self'");
    expect(csp).toMatch(/connect-src 'self' https?:\/\/[^\s;]+/);
  });

  it("sets nosniff, frame denial and a referrer policy", () => {
    expect(header("X-Content-Type-Options")).toBe("nosniff");
    expect(header("X-Frame-Options")).toBe("DENY");
    expect(header("Referrer-Policy")).toBe("strict-origin-when-cross-origin");
  });

  it("applies the headers to every route", async () => {
    const rules = await nextConfig.headers!();
    expect(rules).toEqual([{ source: "/:path*", headers: securityHeaders }]);
  });
});
