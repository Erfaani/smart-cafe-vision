import { DisplayEmptyState } from "@/components/display/empty-state";
import { formatDuration } from "@/lib/duration";
import type { DisplayStats } from "@/lib/types";

export function DisplayStatisticsMode({ stats }: { stats: DisplayStats | null }) {
  if (!stats) {
    return <DisplayEmptyState message="Statistics are not available yet." />;
  }

  const percentFull =
    stats.seating_capacity > 0 ? Math.round((stats.occupancy / stats.seating_capacity) * 100) : null;

  return (
    <div className="mx-auto grid max-w-4xl grid-cols-1 gap-6 sm:grid-cols-2">
      <StatTile
        label="Right now"
        value={String(stats.occupancy)}
        sub={percentFull !== null ? `${percentFull}% full` : undefined}
      />
      <StatTile label="Visitors today" value={String(stats.visitors_today)} />
      <StatTile
        label="Average stay today"
        value={stats.average_stay_seconds !== null ? formatDuration(stats.average_stay_seconds) : "—"}
      />
      <StatTile label="Seating capacity" value={String(stats.seating_capacity)} />
    </div>
  );
}

function StatTile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 p-8 text-center">
      <p className="text-lg uppercase tracking-wide text-white/50">{label}</p>
      <p className="mt-2 text-7xl font-bold tabular-nums text-white">{value}</p>
      {sub ? <p className="mt-2 text-xl text-white/60">{sub}</p> : null}
    </div>
  );
}
