"use client";

import { useEffect, useMemo, useState } from "react";

import { SessionDuration } from "@/components/session-duration";
import { formatDuration } from "@/lib/duration";
import type { Camera, TableSession, TableUtilization } from "@/lib/types";

const POLL_INTERVAL_MS = 5000;
const RECENT_RELEASED_LIMIT = 15;

const RELEASE_REASON_LABELS: Record<string, string> = {
  cleared: "Cleared",
  stale: "Tracker lost signal",
};

type RangePreset = "today" | "7d" | "30d" | "month";

const RANGE_LABELS: Record<RangePreset, string> = {
  today: "Today",
  "7d": "Last 7 days",
  "30d": "Last 30 days",
  month: "This month",
};

function isoDateTime(date: Date): string {
  return date.toISOString();
}

function rangeFor(preset: RangePreset): { start: string; end: string } {
  const end = new Date();
  const start = new Date(end);
  if (preset === "today") {
    start.setHours(0, 0, 0, 0);
  } else if (preset === "7d") {
    start.setDate(start.getDate() - 6);
    start.setHours(0, 0, 0, 0);
  } else if (preset === "30d") {
    start.setDate(start.getDate() - 29);
    start.setHours(0, 0, 0, 0);
  } else {
    start.setDate(1);
    start.setHours(0, 0, 0, 0);
  }
  return { start: isoDateTime(start), end: isoDateTime(end) };
}

function clockTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function TablesPageClient({
  initialSessions,
  cameras,
}: {
  initialSessions: TableSession[];
  cameras: Camera[];
}) {
  const [sessions, setSessions] = useState(initialSessions);
  const [preset, setPreset] = useState<RangePreset>("today");
  const [utilization, setUtilization] = useState<TableUtilization[]>([]);
  const [loadingUtilization, setLoadingUtilization] = useState(false);
  const [utilizationError, setUtilizationError] = useState<string | null>(null);

  const cameraNames = useMemo(() => {
    const map = new Map<string, string>();
    for (const camera of cameras) map.set(camera.id, camera.name);
    return map;
  }, [cameras]);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const response = await fetch("/api/table-sessions");
        if (!cancelled && response.ok) {
          const page = (await response.json()) as { results: TableSession[] };
          setSessions(page.results);
        }
      } catch {
        // A missed poll just tries again next tick.
      }
    }

    const interval = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const { start, end } = rangeFor(preset);

    async function load() {
      setLoadingUtilization(true);
      setUtilizationError(null);
      try {
        const response = await fetch(
          `/api/tables/utilization?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
        );
        if (!response.ok) {
          if (!cancelled) setUtilizationError("Could not load utilisation for this range.");
          return;
        }
        const body = (await response.json()) as TableUtilization[];
        if (!cancelled) setUtilization(body);
      } catch {
        if (!cancelled) setUtilizationError("Could not reach the server.");
      } finally {
        if (!cancelled) setLoadingUtilization(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [preset]);

  const occupied = sessions
    .filter((s) => s.status === "active")
    .sort((a, b) => a.occupied_at.localeCompare(b.occupied_at));
  const recentReleased = sessions
    .filter((s) => s.status === "ended")
    .sort((a, b) => (b.released_at ?? "").localeCompare(a.released_at ?? ""))
    .slice(0, RECENT_RELEASED_LIMIT);

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <h2 className="text-sm font-medium text-ink">
          Occupied now <span className="text-ink-muted">({occupied.length})</span>
        </h2>
        {occupied.length === 0 ? (
          <p className="rounded-lg border border-border-subtle px-4 py-6 text-center text-sm text-ink-muted">
            No tables currently occupied.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border-subtle">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs font-medium uppercase tracking-wide text-ink-muted">
                  <th className="px-4 py-2.5">Table</th>
                  <th className="px-4 py-2.5">Camera</th>
                  <th className="px-4 py-2.5">Since</th>
                  <th className="px-4 py-2.5">Occupied for</th>
                </tr>
              </thead>
              <tbody>
                {occupied.map((session) => (
                  <tr key={session.id} className="border-t border-border-subtle">
                    <td className="px-4 py-3 text-ink">{session.table_name}</td>
                    <td className="px-4 py-3 text-ink-muted">
                      {cameraNames.get(session.camera_id) ?? "Unknown camera"}
                    </td>
                    <td className="px-4 py-3 text-ink-muted">{clockTime(session.occupied_at)}</td>
                    <td className="px-4 py-3 font-medium text-ink">
                      <SessionDuration entryAt={session.occupied_at} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-medium text-ink">Recent</h2>
        {recentReleased.length === 0 ? (
          <p className="rounded-lg border border-border-subtle px-4 py-6 text-center text-sm text-ink-muted">
            No completed table sessions yet.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border-subtle">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs font-medium uppercase tracking-wide text-ink-muted">
                  <th className="px-4 py-2.5">Table</th>
                  <th className="px-4 py-2.5">Camera</th>
                  <th className="px-4 py-2.5">Occupied</th>
                  <th className="px-4 py-2.5">Released</th>
                  <th className="px-4 py-2.5">Duration</th>
                  <th className="px-4 py-2.5">Reason</th>
                </tr>
              </thead>
              <tbody>
                {recentReleased.map((session) => (
                  <tr key={session.id} className="border-t border-border-subtle">
                    <td className="px-4 py-3 text-ink">{session.table_name}</td>
                    <td className="px-4 py-3 text-ink-muted">
                      {cameraNames.get(session.camera_id) ?? "Unknown camera"}
                    </td>
                    <td className="px-4 py-3 text-ink-muted">{clockTime(session.occupied_at)}</td>
                    <td className="px-4 py-3 text-ink-muted">
                      {session.released_at ? clockTime(session.released_at) : "—"}
                    </td>
                    <td className="px-4 py-3 font-medium text-ink">{formatDuration(session.duration_seconds)}</td>
                    <td className="px-4 py-3 text-xs text-ink-muted">
                      {RELEASE_REASON_LABELS[session.release_reason] ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-medium text-ink">Utilisation</h2>
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
          </div>
        </div>

        {loadingUtilization ? <p className="text-xs text-ink-muted">Loading…</p> : null}
        {utilizationError ? <p role="alert" className="text-sm text-status-down">{utilizationError}</p> : null}

        {utilization.length === 0 && !loadingUtilization ? (
          <p className="rounded-lg border border-border-subtle px-4 py-6 text-center text-sm text-ink-muted">
            No tables configured yet.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border-subtle">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs font-medium uppercase tracking-wide text-ink-muted">
                  <th className="px-4 py-2.5">Table</th>
                  <th className="px-4 py-2.5">Occupied time</th>
                  <th className="px-4 py-2.5">Turnover</th>
                  <th className="px-4 py-2.5">Utilisation</th>
                </tr>
              </thead>
              <tbody>
                {utilization.map((row) => (
                  <tr key={row.table_zone_id} className="border-t border-border-subtle">
                    <td className="px-4 py-3 text-ink">{row.table_name}</td>
                    <td className="px-4 py-3 text-ink-muted">{formatDuration(row.occupied_seconds)}</td>
                    <td className="px-4 py-3 text-ink-muted">{row.turnover_count}</td>
                    <td className="px-4 py-3 font-medium text-ink">{row.utilization_percent}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
