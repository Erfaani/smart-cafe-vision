"use client";

import { useEffect, useState } from "react";

import { DisplayEntertainmentMode } from "@/components/display/entertainment-mode";
import { DisplayLeaderboardMode } from "@/components/display/leaderboard-mode";
import { DisplayNormalMode } from "@/components/display/normal-mode";
import { DisplayStatisticsMode } from "@/components/display/statistics-mode";
import { useDisplaySocket } from "@/lib/use-display-socket";
import type { CameraLiveTracks, DisplayStats, PublicCafe, PublicDisplayMessage } from "@/lib/types";

const MODES = ["normal", "statistics", "leaderboard", "entertainment"] as const;
type Mode = (typeof MODES)[number];
const MODE_LABELS: Record<Mode, string> = {
  normal: "Live",
  statistics: "Today",
  leaderboard: "Longest stays",
  entertainment: "",
};
const MODE_DURATION_MS = 20000;

export function DisplayClient({
  slug,
  initialCafe,
  initialTracks,
  initialStats,
  initialMessages,
}: {
  slug: string;
  initialCafe: PublicCafe;
  initialTracks: CameraLiveTracks[];
  initialStats: DisplayStats | null;
  initialMessages: PublicDisplayMessage[];
}) {
  const socket = useDisplaySocket(slug, initialCafe.default_language);
  // Once the socket has delivered its own first payload, it is always more
  // current than the SSR snapshot; before that, the snapshot avoids a blank
  // overlay during the handshake. See useDisplaySocket's tracksReceived doc.
  const tracks = socket.tracksReceived ? socket.tracks : initialTracks;
  const stats = socket.stats ?? initialStats;
  const messages = socket.messages.length > 0 ? socket.messages : initialMessages;

  const [modeIndex, setModeIndex] = useState(0);
  useEffect(() => {
    const interval = setInterval(() => setModeIndex((i) => (i + 1) % MODES.length), MODE_DURATION_MS);
    return () => clearInterval(interval);
  }, []);
  const mode = MODES[modeIndex % MODES.length] ?? MODES[0];

  return (
    <div className="flex min-h-dvh flex-col bg-zinc-950" lang={initialCafe.default_language}>
      <DisplayHeader cafe={initialCafe} slug={slug} connected={socket.connected} mode={mode} />
      <main className="flex-1 px-8 py-10">
        {mode === "normal" ? <DisplayNormalMode tracks={tracks} /> : null}
        {mode === "statistics" ? <DisplayStatisticsMode stats={stats} /> : null}
        {mode === "leaderboard" ? <DisplayLeaderboardMode stats={stats} /> : null}
        {mode === "entertainment" ? (
          <DisplayEntertainmentMode messages={messages} />
        ) : null}
      </main>
    </div>
  );
}

function DisplayHeader({
  cafe,
  slug,
  connected,
  mode,
}: {
  cafe: PublicCafe;
  slug: string;
  connected: boolean;
  mode: Mode;
}) {
  return (
    <header className="flex items-center justify-between border-b border-white/10 px-8 py-5">
      <div className="flex items-center gap-4">
        {cafe.logo ? (
          // eslint-disable-next-line @next/next/no-img-element -- proxied through our own origin; see api/public/[slug]/logo.
          <img src={`/api/public/${slug}/logo`} alt="" className="h-12 w-12 rounded-full object-cover" />
        ) : null}
        <p className="text-2xl font-semibold tracking-tight text-white">{cafe.name}</p>
      </div>
      <div className="flex items-center gap-4 text-sm text-white/50">
        {MODE_LABELS[mode] ? <span className="uppercase tracking-wide">{MODE_LABELS[mode]}</span> : null}
        <span
          className={`size-2 rounded-full ${connected ? "bg-emerald-400" : "bg-white/20"}`}
          aria-label={connected ? "Live" : "Reconnecting"}
          title={connected ? "Live" : "Reconnecting…"}
        />
      </div>
    </header>
  );
}
