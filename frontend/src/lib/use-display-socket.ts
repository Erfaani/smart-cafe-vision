"use client";

import { useEffect, useState } from "react";

import type { CameraLiveTracks, DisplayStats, PublicDisplayMessage } from "@/lib/types";

const RECONNECT_DELAY_MS = 2000;

interface DisplaySocketState {
  connected: boolean;
  tracks: CameraLiveTracks[];
  // True once at least one display.tracks push has actually arrived --
  // distinct from `tracks.length > 0`, which a genuinely empty café (no one
  // in frame) would also produce. Lets a consumer prefer the SSR snapshot
  // for the brief window after `connected` flips true but before the first
  // push lands, rather than flashing to an empty overlay for that instant.
  tracksReceived: boolean;
  stats: DisplayStats | null;
  messages: PublicDisplayMessage[];
}

const INITIAL_STATE: DisplaySocketState = {
  connected: false,
  tracks: [],
  tracksReceived: false,
  stats: null,
  messages: [],
};

/**
 * Connects directly to the backend's WebSocket for live tracking positions,
 * occupancy stats, and the message rotation (apps/display/consumers.py).
 *
 * Straight to Django, not proxied through a Next.js route: the browser
 * already does this for the staff dashboard's live camera preview (see
 * `NEXT_PUBLIC_WS_URL` in docker-compose.yml), and this socket is
 * unauthenticated on both ends, so there is no token to protect by adding a
 * proxy hop.
 *
 * Reconnects on drop with a fixed short delay -- a browser tab reconnecting
 * is cheap, unlike the AI worker's RTSP backoff
 * (ai_worker/worker/capture.py), which exists to avoid hammering a camera.
 */
export function useDisplaySocket(slug: string, lang?: string): DisplaySocketState {
  const [state, setState] = useState<DisplaySocketState>(INITIAL_STATE);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;

    function connect() {
      const base = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000";
      const query = lang ? `?lang=${encodeURIComponent(lang)}` : "";
      const ws = new WebSocket(`${base}/ws/display/${slug}/${query}`);
      socket = ws;

      ws.onopen = () => {
        if (!cancelled) setState((prev) => ({ ...prev, connected: true }));
      };

      ws.onmessage = (event) => {
        if (cancelled) return;
        let message: { type?: string; payload?: unknown };
        try {
          message = JSON.parse(event.data as string);
        } catch {
          return;
        }
        if (message.type === "display.tracks") {
          setState((prev) => ({
            ...prev,
            tracks: message.payload as CameraLiveTracks[],
            tracksReceived: true,
          }));
        } else if (message.type === "display.stats") {
          setState((prev) => ({ ...prev, stats: message.payload as DisplayStats }));
        } else if (message.type === "display.messages") {
          setState((prev) => ({ ...prev, messages: message.payload as PublicDisplayMessage[] }));
        }
      };

      ws.onclose = () => {
        if (cancelled) return;
        setState((prev) => ({ ...prev, connected: false }));
        reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS);
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, [slug, lang]);

  return state;
}
