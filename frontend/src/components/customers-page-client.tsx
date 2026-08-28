"use client";

import { useEffect, useMemo, useState } from "react";

import { SessionDuration } from "@/components/session-duration";
import type { ColorStop } from "@/lib/stay-color";
import type { Camera, CustomerSession } from "@/lib/types";

const POLL_INTERVAL_MS = 5000;
const RECENT_ENDED_LIMIT = 15;

const EXIT_REASON_LABELS: Record<string, string> = {
  line_crossing: "Left via exit line",
  track_lost: "Tracker lost signal",
};

function clockTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function CustomersPageClient({
  initialSessions,
  cameras,
  colorStops,
}: {
  initialSessions: CustomerSession[];
  cameras: Camera[];
  colorStops: ColorStop[];
}) {
  const [sessions, setSessions] = useState(initialSessions);

  const cameraNames = useMemo(() => {
    const map = new Map<string, string>();
    for (const camera of cameras) map.set(camera.id, camera.name);
    return map;
  }, [cameras]);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const response = await fetch("/api/sessions");
        if (!cancelled && response.ok) {
          const page = (await response.json()) as { results: CustomerSession[] };
          setSessions(page.results);
        }
      } catch {
        // A missed poll just tries again next tick; nothing worth surfacing.
      }
    }

    const interval = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  const active = sessions
    .filter((s) => s.status === "active")
    .sort((a, b) => a.entry_at.localeCompare(b.entry_at));
  const recentEnded = sessions
    .filter((s) => s.status === "ended")
    .sort((a, b) => (b.exit_at ?? "").localeCompare(a.exit_at ?? ""))
    .slice(0, RECENT_ENDED_LIMIT);

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <h2 className="text-sm font-medium text-ink">
          Active now <span className="text-ink-muted">({active.length})</span>
        </h2>
        {active.length === 0 ? (
          <p className="rounded-lg border border-border-subtle px-4 py-6 text-center text-sm text-ink-muted">
            No one currently tracked as present.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border-subtle">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs font-medium uppercase tracking-wide text-ink-muted">
                  <th className="px-4 py-2.5">Camera</th>
                  <th className="px-4 py-2.5">Entered</th>
                  <th className="px-4 py-2.5">Via</th>
                  <th className="px-4 py-2.5">Stay time</th>
                </tr>
              </thead>
              <tbody>
                {active.map((session) => (
                  <tr key={session.id} className="border-t border-border-subtle">
                    <td className="px-4 py-3 text-ink">
                      {cameraNames.get(session.camera_id) ?? "Unknown camera"}
                    </td>
                    <td className="px-4 py-3 text-ink-muted">{clockTime(session.entry_at)}</td>
                    <td className="px-4 py-3 text-ink-muted">{session.entry_zone_name || "—"}</td>
                    <td className="px-4 py-3 font-medium">
                      <SessionDuration entryAt={session.entry_at} stops={colorStops} />
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
        {recentEnded.length === 0 ? (
          <p className="rounded-lg border border-border-subtle px-4 py-6 text-center text-sm text-ink-muted">
            No completed visits yet.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border-subtle">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs font-medium uppercase tracking-wide text-ink-muted">
                  <th className="px-4 py-2.5">Camera</th>
                  <th className="px-4 py-2.5">Entered</th>
                  <th className="px-4 py-2.5">Left</th>
                  <th className="px-4 py-2.5">Stay time</th>
                  <th className="px-4 py-2.5">How it ended</th>
                </tr>
              </thead>
              <tbody>
                {recentEnded.map((session) => (
                  <tr key={session.id} className="border-t border-border-subtle">
                    <td className="px-4 py-3 text-ink">
                      {cameraNames.get(session.camera_id) ?? "Unknown camera"}
                    </td>
                    <td className="px-4 py-3 text-ink-muted">{clockTime(session.entry_at)}</td>
                    <td className="px-4 py-3 text-ink-muted">
                      {session.exit_at ? clockTime(session.exit_at) : "—"}
                    </td>
                    <td className="px-4 py-3 font-medium">
                      <SessionDuration
                        entryAt={session.entry_at}
                        fixedSeconds={session.duration_seconds}
                        stops={colorStops}
                      />
                    </td>
                    <td className="px-4 py-3 text-xs text-ink-muted">
                      {EXIT_REASON_LABELS[session.exit_reason] ?? "—"}
                    </td>
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
