/**
 * Pure geometry for the zone editor's direction arrow.
 *
 * Mirrors ai_worker/worker/zones.py::side_of_line exactly, so the arrow drawn
 * in the browser always agrees with what the AI worker will actually treat
 * as an entry. That function's sign convention: side_of_line(point, a, b) is
 * positive when `point` is on the side reached by rotating the vector a->b
 * 90 degrees counter-clockwise (in this pixel coordinate system, where y
 * increases downward) -- see that module's docstring and tests/test_zones.py
 * for the worked example this file's own tests are built from.
 */

export interface Point {
  x: number;
  y: number;
}

export function midpoint(a: Point, b: Point): Point {
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
}

/** Unit normal of the directed line a->b that always points to the
 * "positive" side of worker/zones.py's side_of_line. */
export function positiveSideNormal(a: Point, b: Point): Point {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const length = Math.hypot(dx, dy) || 1;
  return { x: -dy / length, y: dx / length };
}

/** The direction a person must move to register as an ENTRY through this
 * zone, as a unit vector -- used to draw the editor's direction arrow. */
export function entryDirection(a: Point, b: Point, entryIsPositiveSide: boolean): Point {
  const normal = positiveSideNormal(a, b);
  return entryIsPositiveSide ? normal : { x: -normal.x, y: -normal.y };
}
