/**
 * Dynamic stay-time colour (Phase 6).
 *
 * Exact TypeScript mirror of backend/apps/core/color.py -- read that file's
 * module docstring for why a customer's box on the public display and their
 * row on the dashboard must always agree, and how that agreement is
 * enforced (the same hand-computed vectors asserted in both languages'
 * tests, not a shared runtime). Any change here needs the same change there.
 */

export interface ColorStop {
  seconds: number;
  color: string;
}

/** Traffic-light default: fresh (green) -> 30 minutes (amber) -> 60 minutes
 * (red). Mirrors apps.core.color.DEFAULT_STAY_COLOR_STOPS. Used only as a
 * client-side fallback if a café record is ever missing the field; the
 * backend always sends a real value. */
export const DEFAULT_STAY_COLOR_STOPS: ColorStop[] = [
  { seconds: 0, color: "#22c55e" },
  { seconds: 1800, color: "#f59e0b" },
  { seconds: 3600, color: "#ef4444" },
];

/** The colour for a stay of `seconds`, per `stops` (already validated by the
 * backend -- sorted ascending, first stop at seconds=0, at least one stop).
 * Continuous linear interpolation between consecutive stops; clamped at
 * both ends. */
export function colorForDuration(seconds: number, stops: ColorStop[]): string {
  if (stops.length === 0) {
    throw new Error("colorForDuration requires at least one stop");
  }

  let lower = stops[0]!;
  if (seconds <= lower.seconds) return lower.color;

  for (const upper of stops.slice(1)) {
    if (seconds <= upper.seconds) {
      const span = upper.seconds - lower.seconds;
      const t = span ? (seconds - lower.seconds) / span : 0;
      return mix(lower.color, upper.color, t);
    }
    lower = upper;
  }

  return lower.color;
}

function mix(colorA: string, colorB: string, t: number): string {
  const [ar, ag, ab] = hexToRgb(colorA);
  const [br, bg, bb] = hexToRgb(colorB);
  // Math.round() always rounds .5 up for a non-negative number -- matching
  // the Python side's explicit round-half-up (not its banker's-rounding
  // built-in `round()`), so the two stay bit-for-bit identical at every t.
  return rgbToHex([
    Math.round(ar + (br - ar) * t),
    Math.round(ag + (bg - ag) * t),
    Math.round(ab + (bb - ab) * t),
  ]);
}

function hexToRgb(color: string): [number, number, number] {
  return [
    parseInt(color.slice(1, 3), 16),
    parseInt(color.slice(3, 5), 16),
    parseInt(color.slice(5, 7), 16),
  ];
}

function rgbToHex(rgb: [number, number, number]): string {
  return "#" + rgb.map((channel) => channel.toString(16).padStart(2, "0")).join("");
}
