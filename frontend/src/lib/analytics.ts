/**
 * Client-side aggregation over a range of DailyStat rows.
 *
 * Deliberately pure and range-agnostic: the backend rollup
 * (backend/apps/analytics/rollups.py) only ever produces one row per café
 * per local day -- "this week" or "this month" is just a wider set of rows
 * fetched from the same endpoint, combined here rather than by a second
 * backend aggregation path.
 */

import type { DailyStat } from "@/lib/types";

export interface AnalyticsSummary {
  totalVisitors: number;
  // Correctly weighted: sum(total_stay_seconds) / sum(ended_session_count),
  // not an average of each day's own average -- see DailyStat's own doc for
  // why that would misweight a slow day the same as a busy one.
  averageStaySeconds: number | null;
  longestStaySeconds: number | null;
  peakOccupancy: number;
  /** Entries by local hour-of-day, index 0-23, summed across every row. */
  hourlyTotals: number[];
  /** Visitors by day-of-week, index 0 (Sunday) - 6 (Saturday), JS Date
   * convention -- summed across every row. */
  weekdayTotals: number[];
}

export function summarizeDailyStats(stats: DailyStat[]): AnalyticsSummary {
  let totalVisitors = 0;
  let totalStaySeconds = 0;
  let endedSessionCount = 0;
  let longestStaySeconds: number | null = null;
  let peakOccupancy = 0;
  const hourlyTotals = new Array<number>(24).fill(0);
  const weekdayTotals = new Array<number>(7).fill(0);

  for (const stat of stats) {
    totalVisitors += stat.visitor_count;
    totalStaySeconds += stat.total_stay_seconds;
    endedSessionCount += stat.ended_session_count;
    if (stat.longest_stay_seconds !== null) {
      longestStaySeconds =
        longestStaySeconds === null
          ? stat.longest_stay_seconds
          : Math.max(longestStaySeconds, stat.longest_stay_seconds);
    }
    peakOccupancy = Math.max(peakOccupancy, stat.peak_occupancy);

    stat.hourly_entries.forEach((count, hour) => {
      hourlyTotals[hour] = (hourlyTotals[hour] ?? 0) + count;
    });

    const weekday = localWeekday(stat.date);
    weekdayTotals[weekday] = (weekdayTotals[weekday] ?? 0) + stat.visitor_count;
  }

  return {
    totalVisitors,
    averageStaySeconds: endedSessionCount > 0 ? totalStaySeconds / endedSessionCount : null,
    longestStaySeconds,
    peakOccupancy,
    hourlyTotals,
    weekdayTotals,
  };
}

/** 0 (Sunday) - 6 (Saturday) for a plain `YYYY-MM-DD` date string.
 *
 * `new Date("2026-06-01")` parses a date-only ISO string as UTC midnight
 * per the ECMAScript spec, so `.getDay()` on it can report the *previous*
 * day in any timezone behind UTC -- a well-known footgun. Appending a
 * timeless suffix forces local-midnight parsing instead, so the weekday
 * matches the calendar date regardless of the viewer's own timezone. */
function localWeekday(isoDate: string): number {
  return new Date(`${isoDate}T00:00:00`).getDay();
}
