import { describe, expect, it } from "vitest";

import { safeRedirectTarget } from "@/lib/redirect";

// Built from char codes so the intended backslash cannot be lost to source
// escaping — the exact mistake this test caught the first time it ran.
const BACKSLASH_PATH = "/" + String.fromCharCode(92) + "evil.example";

describe("safeRedirectTarget", () => {
  it("keeps an ordinary in-app path", () => {
    expect(safeRedirectTarget("/dashboard/cameras")).toBe("/dashboard/cameras");
  });

  it("keeps a path with a query string", () => {
    expect(safeRedirectTarget("/dashboard?tab=live")).toBe("/dashboard?tab=live");
  });

  it("falls back when nothing was requested", () => {
    expect(safeRedirectTarget(null)).toBe("/dashboard");
  });

  it.each([
    "https://evil.example",
    "//evil.example",
    BACKSLASH_PATH,
    "/javascript:alert(1)",
    "javascript:alert(1)",
    "http://evil.example/dashboard",
  ])("refuses to leave the site for %s", (hostile) => {
    expect(safeRedirectTarget(hostile)).toBe("/dashboard");
  });

  it("honours a caller-supplied fallback", () => {
    expect(safeRedirectTarget("https://evil.example", "/login")).toBe("/login");
  });
});
