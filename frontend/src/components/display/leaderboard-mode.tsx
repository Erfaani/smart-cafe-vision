import { DisplayEmptyState } from "@/components/display/empty-state";
import { formatDuration } from "@/lib/duration";
import type { DisplayStats } from "@/lib/types";

/** Durations only, by design -- see apps/display/live.py::get_public_stats's
 * docstring for why this never names a track id, camera, or anything that
 * could let the room single someone out. "Longest visit today: 1h 42m" is a
 * fun, anonymous number on its own. */
export function DisplayLeaderboardMode({ stats }: { stats: DisplayStats | null }) {
  if (!stats || stats.leaderboard_seconds.length === 0) {
    return <DisplayEmptyState message="No visits recorded yet today." />;
  }

  return (
    <div className="mx-auto max-w-2xl">
      <h2 className="text-center text-2xl uppercase tracking-wide text-white/50">Longest stays today</h2>
      <ol className="mt-8 space-y-4">
        {stats.leaderboard_seconds.map((seconds, index) => (
          <li
            key={index}
            className="flex items-center justify-between rounded-xl border border-white/10 bg-white/5 px-6 py-4"
          >
            <span className="text-3xl font-bold text-white/30">#{index + 1}</span>
            <span className="text-4xl font-bold tabular-nums text-white">{formatDuration(seconds)}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}
