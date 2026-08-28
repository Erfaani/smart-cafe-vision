import type { Metadata } from "next";

import { AnalyticsPageClient } from "@/components/analytics/analytics-page-client";
import { apiFetch } from "@/lib/api";
import type { DailyStat } from "@/lib/types";

export const metadata: Metadata = { title: "Analytics" };
export const dynamic = "force-dynamic";

const DEFAULT_RANGE_DAYS = 30;

function isoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

export default async function AnalyticsPage() {
  const end = new Date();
  const start = new Date(end);
  start.setDate(start.getDate() - (DEFAULT_RANGE_DAYS - 1));

  let stats: DailyStat[] = [];
  try {
    stats = await apiFetch<DailyStat[]>(
      `/api/v1/analytics/daily/?start=${isoDate(start)}&end=${isoDate(end)}`,
    );
  } catch {
    // The client component re-fetches on mount and surfaces its own error
    // state; an empty initial list just means the first paint is blank
    // rather than broken.
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <header>
        <h1 className="text-lg font-semibold tracking-tight text-ink">Analytics</h1>
        <p className="mt-1 text-sm text-ink-muted">
          Occupancy and stay-time trends, computed from daily rollups rather than scanning raw
          sessions on every request.
        </p>
      </header>

      <AnalyticsPageClient initialStats={stats} initialRangeDays={DEFAULT_RANGE_DAYS} />
    </div>
  );
}
