"use client";

import { useEffect, useState } from "react";

import { BarChart } from "@/components/analytics/bar-chart";
import { summarizeDailyStats } from "@/lib/analytics";
import { formatDuration } from "@/lib/duration";
import type { DailyStat } from "@/lib/types";

const WEEKDAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

type RangePreset = "today" | "7d" | "30d" | "month";

const RANGE_LABELS: Record<RangePreset, string> = {
  today: "Today",
  "7d": "Last 7 days",
  "30d": "Last 30 days",
  month: "This month",
};

function isoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function rangeFor(preset: RangePreset): { start: string; end: string } {
  const end = new Date();
  const start = new Date(end);
  if (preset === "today") {
    // start === end
  } else if (preset === "7d") {
    start.setDate(start.getDate() - 6);
  } else if (preset === "30d") {
    start.setDate(start.getDate() - 29);
  } else {
    start.setDate(1);
  }
  return { start: isoDate(start), end: isoDate(end) };
}

export function AnalyticsPageClient({
  initialStats,
  initialRangeDays,
}: {
  initialStats: DailyStat[];
  initialRangeDays: number;
}) {
  const [preset, setPreset] = useState<RangePreset>(initialRangeDays >= 30 ? "30d" : "7d");
  const [stats, setStats] = useState(initialStats);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const { start, end } = rangeFor(preset);

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const response = await fetch(`/api/analytics/daily?start=${start}&end=${end}`);
        if (!response.ok) {
          if (!cancelled) setError("Could not load analytics for this range.");
          return;
        }
        const body = (await response.json()) as DailyStat[];
        if (!cancelled) setStats(body);
      } catch {
        if (!cancelled) setError("Could not reach the server.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [preset]);

  const summary = summarizeDailyStats(stats);
  const sortedStats = [...stats].sort((a, b) => a.date.localeCompare(b.date));

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap gap-2">
        {(Object.keys(RANGE_LABELS) as RangePreset[]).map((key) => (
          <button
            key={key}
            type="button"
            onClick={() => setPreset(key)}
            className={`rounded-md border px-3 py-1.5 text-sm ${
              preset === key
                ? "border-accent bg-accent text-surface"
                : "border-border-subtle text-ink hover:bg-surface-raised"
            }`}
          >
            {RANGE_LABELS[key]}
          </button>
        ))}
        {loading ? <span className="self-center text-xs text-ink-muted">Loading…</span> : null}
      </div>

      {error ? <p role="alert" className="text-sm text-status-down">{error}</p> : null}

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatTile label="Visitors" value={String(summary.totalVisitors)} />
        <StatTile
          label="Average stay"
          value={summary.averageStaySeconds !== null ? formatDuration(summary.averageStaySeconds) : "—"}
        />
        <StatTile
          label="Longest stay"
          value={summary.longestStaySeconds !== null ? formatDuration(summary.longestStaySeconds) : "—"}
        />
        <StatTile label="Peak occupancy" value={String(summary.peakOccupancy)} />
      </div>

      <section>
        <h2 className="mb-3 text-sm font-medium text-ink">Daily visitors</h2>
        <div className="rounded-lg border border-border-subtle p-4">
          <BarChart
            data={sortedStats.map((stat) => ({
              label: stat.date.slice(5), // MM-DD
              value: stat.visitor_count,
              title: `${stat.date}: ${stat.visitor_count} visitor${stat.visitor_count === 1 ? "" : "s"}${
                stat.is_final ? "" : " (in progress)"
              }`,
            }))}
          />
        </div>
      </section>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <section>
          <h2 className="mb-3 text-sm font-medium text-ink">Busiest hours</h2>
          <div className="rounded-lg border border-border-subtle p-4">
            <BarChart
              data={summary.hourlyTotals.map((value, hour) => ({
                label: String(hour),
                value,
                title: `${hour}:00–${hour + 1}:00: ${value} arrival${value === 1 ? "" : "s"}`,
              }))}
            />
          </div>
        </section>

        <section>
          <h2 className="mb-3 text-sm font-medium text-ink">Busiest days</h2>
          <div className="rounded-lg border border-border-subtle p-4">
            <BarChart
              data={summary.weekdayTotals.map((value, day) => ({
                label: WEEKDAY_LABELS[day] ?? "",
                value,
                title: `${WEEKDAY_LABELS[day]}: ${value} visitor${value === 1 ? "" : "s"}`,
              }))}
            />
          </div>
        </section>
      </div>
    </div>
  );
}

function StatTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border-subtle bg-surface-raised p-4 text-center">
      <p className="text-xs uppercase tracking-wide text-ink-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-ink">{value}</p>
    </div>
  );
}
