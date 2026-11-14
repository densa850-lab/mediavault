import { describe, expect, it } from "vitest";

import { trustedProxyWarning } from "@/lib/auth/deployWarnings";

describe("trustedProxyWarning (MV-025)", () => {
  it("warns in production when WEB_TRUSTED_PROXY_HOPS is unset, 0 or invalid", () => {
    for (const hops of [undefined, "", "0", "abc", "11", "-1"]) {
      expect(trustedProxyWarning({ NODE_ENV: "production", WEB_TRUSTED_PROXY_HOPS: hops })).toMatch(
        /share ONE login\/register rate-limit bucket/,
      );
    }
  });

  it("is quiet when hops are configured, and outside production", () => {
    expect(trustedProxyWarning({ NODE_ENV: "production", WEB_TRUSTED_PROXY_HOPS: "1" })).toBeNull();
    expect(trustedProxyWarning({ NODE_ENV: "production", WEB_TRUSTED_PROXY_HOPS: "2" })).toBeNull();
    expect(trustedProxyWarning({ NODE_ENV: "development" })).toBeNull();
    expect(trustedProxyWarning({ NODE_ENV: "test", WEB_TRUSTED_PROXY_HOPS: "0" })).toBeNull();
  });
});
