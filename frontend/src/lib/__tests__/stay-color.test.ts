import { describe, expect, it } from "vitest";

import { colorForDuration, DEFAULT_STAY_COLOR_STOPS, type ColorStop } from "@/lib/stay-color";

// Cross-checked with backend/apps/core/tests/test_color.py: every vector
// below appears verbatim in that file too, hand-computed once and pasted
// into both suites -- see src/lib/stay-color.ts's module docstring.
const STOPS: ColorStop[] = [
  { seconds: 0, color: "#22c55e" },
  { seconds: 1800, color: "#f59e0b" },
  { seconds: 3600, color: "#ef4444" },
];

const VECTORS: Array<[number, string]> = [
  [0, "#22c55e"],
  [900, "#8cb235"], // halfway through the first segment
  [1800, "#f59e0b"], // exactly on the middle stop
  [2700, "#f27128"], // halfway through the second segment
  [3600, "#ef4444"], // exactly on the last stop
  [7200, "#ef4444"], // beyond the last stop: clamped, not extrapolated
  [-10, "#22c55e"], // defensively clamped before the first stop too
];

describe("colorForDuration", () => {
  it.each(VECTORS)("returns %s for %i seconds (matches the Python vectors)", (seconds, expected) => {
    expect(colorForDuration(seconds, STOPS)).toBe(expected);
  });

  it("is exact at every configured stop, not just interpolated near it", () => {
    for (const stop of STOPS) {
      expect(colorForDuration(stop.seconds, STOPS)).toBe(stop.color);
    }
  });
});

describe("DEFAULT_STAY_COLOR_STOPS", () => {
  it("starts green and ends red", () => {
    expect(DEFAULT_STAY_COLOR_STOPS.at(0)?.color).toBe("#22c55e");
    expect(DEFAULT_STAY_COLOR_STOPS.at(-1)?.color).toBe("#ef4444");
  });

  it("starts at zero seconds", () => {
    expect(DEFAULT_STAY_COLOR_STOPS.at(0)?.seconds).toBe(0);
  });
});
