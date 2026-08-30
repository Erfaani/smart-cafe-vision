"use client";

import { useEffect, useState } from "react";

import { formatDuration } from "@/lib/duration";
import { colorForDuration, type ColorStop } from "@/lib/stay-color";

const TICK_MS = 1000;

/** Live-ticking stay duration for an ACTIVE session -- computed client-side
 * from `entryAt` every second, not polled from the server: the backend's
 * `duration_seconds` is only a snapshot as of the last fetch (see
 * CustomerSession's docstring), and re-fetching once a second for every
 * visible row would be wasteful. An ENDED session's duration is fixed, so it
 * renders once with no timer at all.
 *
 * When `stops` is given, the text colour rides along with it -- the same
 * green-to-red slide a box on the public display will show (Phase 7), from
 * the identical `colorForDuration` used there and on the backend. */
export function SessionDuration({
  entryAt,
  fixedSeconds,
  stops,
}: {
  entryAt: string;
  fixedSeconds?: number;
  stops?: ColorStop[];
}) {
  const [seconds, setSeconds] = useState(() =>
    fixedSeconds ?? (Date.now() - new Date(entryAt).getTime()) / 1000,
  );

  useEffect(() => {
    if (fixedSeconds !== undefined) return;
    const interval = setInterval(() => {
      setSeconds((Date.now() - new Date(entryAt).getTime()) / 1000);
    }, TICK_MS);
    return () => clearInterval(interval);
  }, [entryAt, fixedSeconds]);

  const color = stops ? colorForDuration(seconds, stops) : undefined;
  // suppressHydrationWarning: for a live-ticking session this text is a
  // clock, not fixed content -- the server and client necessarily render it
  // a moment apart, so a one-second mismatch on first paint is expected
  // (React's own documented case for this prop), not a bug to chase. An
  // ended session's fixedSeconds is identical on both sides, so there is
  // nothing to suppress in that case -- this prop is a no-op then.
  return (
    <span style={color ? { color } : undefined} suppressHydrationWarning>
      {formatDuration(seconds)}
    </span>
  );
}
