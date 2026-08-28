import { describe, expect, it } from "vitest";

import { formatDuration } from "@/lib/duration";

describe("formatDuration", () => {
  it("renders sub-minute durations as seconds only", () => {
    expect(formatDuration(0)).toBe("0s");
    expect(formatDuration(42)).toBe("42s");
  });

  it("renders sub-hour durations as minutes and seconds", () => {
    expect(formatDuration(65)).toBe("1m 05s");
    expect(formatDuration(600)).toBe("10m 00s");
  });

  it("drops seconds once a stay reaches an hour", () => {
    expect(formatDuration(3600)).toBe("1h 00m");
    expect(formatDuration(3660 + 42)).toBe("1h 01m");
  });

  it("floors fractional seconds", () => {
    expect(formatDuration(41.9)).toBe("41s");
  });

  it("clamps a negative duration to zero instead of going negative", () => {
    expect(formatDuration(-5)).toBe("0s");
  });
});
