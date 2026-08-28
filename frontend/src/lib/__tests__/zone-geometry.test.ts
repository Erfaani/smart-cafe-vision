import { describe, expect, it } from "vitest";

import { entryDirection, midpoint, positiveSideNormal } from "@/lib/zone-geometry";

// The exact fixture from ai_worker/tests/test_zones.py: a vertical line
// point_a=(100,0) -> point_b=(100,200), entry_is_positive_side=True means
// "walking so x decreases (ending left of the line) is an entry".
const A = { x: 100, y: 0 };
const B = { x: 100, y: 200 };

describe("midpoint", () => {
  it("averages the two endpoints", () => {
    expect(midpoint(A, B)).toEqual({ x: 100, y: 100 });
  });
});

describe("positiveSideNormal", () => {
  it("points toward decreasing x for a downward vertical line", () => {
    const normal = positiveSideNormal(A, B);
    expect(normal.x).toBeCloseTo(-1);
    expect(normal.y).toBeCloseTo(0);
  });

  it("is a unit vector regardless of the line's length", () => {
    const normal = positiveSideNormal({ x: 0, y: 0 }, { x: 0, y: 50 });
    expect(Math.hypot(normal.x, normal.y)).toBeCloseTo(1);
  });
});

describe("entryDirection", () => {
  it("points toward decreasing x when entry_is_positive_side is true", () => {
    const direction = entryDirection(A, B, true);
    expect(direction.x).toBeCloseTo(-1);
    expect(direction.y).toBeCloseTo(0);
  });

  it("points toward increasing x when entry_is_positive_side is false", () => {
    const direction = entryDirection(A, B, false);
    expect(direction.x).toBeCloseTo(1);
    expect(direction.y).toBeCloseTo(0);
  });

  it("is perpendicular to the zone line", () => {
    const dx = B.x - A.x;
    const dy = B.y - A.y;
    const direction = entryDirection(A, B, true);
    // Dot product of two perpendicular vectors is zero.
    expect(dx * direction.x + dy * direction.y).toBeCloseTo(0);
  });
});
