import { describe, expect, it } from "vitest";

import { summarizeDailyStats } from "@/lib/analytics";
import type { DailyStat } from "@/lib/types";

function makeStat(overrides: Partial<DailyStat>): DailyStat {
  return {
    date: "2026-06-01",
    visitor_count: 0,
    ended_session_count: 0,
    total_stay_seconds: 0,
    average_stay_seconds: null,
    longest_stay_seconds: null,
    hourly_entries: new Array(24).fill(0),
    peak_occupancy: 0,
    peak_occupancy_at: null,
    is_final: true,
    ...overrides,
  };
}

describe("summarizeDailyStats", () => {
  it("returns zeroed values for an empty range", () => {
    const summary = summarizeDailyStats([]);
    expect(summary.totalVisitors).toBe(0);
    expect(summary.averageStaySeconds).toBeNull();
    expect(summary.longestStaySeconds).toBeNull();
    expect(summary.peakOccupancy).toBe(0);
  });

  it("sums visitor counts across days", () => {
    const summary = summarizeDailyStats([
      makeStat({ date: "2026-06-01", visitor_count: 10 }),
      makeStat({ date: "2026-06-02", visitor_count: 15 }),
    ]);
    expect(summary.totalVisitors).toBe(25);
  });

  it("computes a weighted average, not an average of averages", () => {
    // Day A: 1 ended session, 100s. Day B: 3 ended sessions, 900s total
    // (avg 300s). Naive average-of-averages would give (100+300)/2 = 200s;
    // the correct weighted average is (100+900)/4 = 250s.
    const summary = summarizeDailyStats([
      makeStat({
        date: "2026-06-01",
        ended_session_count: 1,
        total_stay_seconds: 100,
        average_stay_seconds: 100,
      }),
      makeStat({
        date: "2026-06-02",
        ended_session_count: 3,
        total_stay_seconds: 900,
        average_stay_seconds: 300,
      }),
    ]);
    expect(summary.averageStaySeconds).toBe(250);
  });

  it("is null when no session ended across the whole range", () => {
    const summary = summarizeDailyStats([makeStat({ visitor_count: 5, ended_session_count: 0 })]);
    expect(summary.averageStaySeconds).toBeNull();
  });

  it("takes the max longest_stay_seconds across days, ignoring nulls", () => {
    const summary = summarizeDailyStats([
      makeStat({ date: "2026-06-01", longest_stay_seconds: 500 }),
      makeStat({ date: "2026-06-02", longest_stay_seconds: null }),
      makeStat({ date: "2026-06-03", longest_stay_seconds: 1200 }),
    ]);
    expect(summary.longestStaySeconds).toBe(1200);
  });

  it("takes the max peak_occupancy across days", () => {
    const summary = summarizeDailyStats([
      makeStat({ date: "2026-06-01", peak_occupancy: 3 }),
      makeStat({ date: "2026-06-02", peak_occupancy: 7 }),
      makeStat({ date: "2026-06-03", peak_occupancy: 2 }),
    ]);
    expect(summary.peakOccupancy).toBe(7);
  });

  it("sums hourly_entries element-wise across days", () => {
    const dayA = new Array(24).fill(0);
    dayA[9] = 2;
    const dayB = new Array(24).fill(0);
    dayB[9] = 3;
    dayB[17] = 1;

    const summary = summarizeDailyStats([
      makeStat({ date: "2026-06-01", hourly_entries: dayA }),
      makeStat({ date: "2026-06-02", hourly_entries: dayB }),
    ]);
    expect(summary.hourlyTotals[9]).toBe(5);
    expect(summary.hourlyTotals[17]).toBe(1);
    expect(summary.hourlyTotals[0]).toBe(0);
  });

  it("buckets visitors by the calendar weekday of each date, not UTC-shifted", () => {
    // 2026-06-01 is a Monday.
    const summary = summarizeDailyStats([
      makeStat({ date: "2026-06-01", visitor_count: 4 }),
      makeStat({ date: "2026-06-07", visitor_count: 6 }), // the following Sunday
    ]);
    expect(summary.weekdayTotals[1]).toBe(4); // Monday
    expect(summary.weekdayTotals[0]).toBe(6); // Sunday
  });
});
