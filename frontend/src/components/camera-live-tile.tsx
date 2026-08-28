"use client";

import { useEffect, useState } from "react";

import { CameraStatusBadge } from "@/components/camera-status-badge";
import type { Camera, CameraDetections, CameraTracks } from "@/lib/types";

const DETECTIONS_POLL_INTERVAL_MS = 2000;

/**
 * One live preview tile.
 *
 * The `<img>` src points at this app's own proxy route
 * (/api/cameras/[id]/stream), never at Django directly -- the browser has no
 * token to present, and should never need one (see docs/architecture.md).
 * A key on the element forces the browser to open a fresh connection if the
 * camera is manually reloaded after an error.
 */
export function CameraLiveTile({ camera }: { camera: Camera }) {
  const [errored, setErrored] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);
  const [detections, setDetections] = useState<CameraDetections | null>(null);
  const [tracks, setTracks] = useState<CameraTracks | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const [detectionsResponse, tracksResponse] = await Promise.all([
          fetch(`/api/cameras/${camera.id}/detections`),
          fetch(`/api/cameras/${camera.id}/tracks`),
        ]);
        if (!cancelled && detectionsResponse.ok) {
          setDetections((await detectionsResponse.json()) as CameraDetections);
        }
        if (!cancelled && tracksResponse.ok) {
          setTracks((await tracksResponse.json()) as CameraTracks);
        }
      } catch {
        // A missed poll is not worth surfacing to the viewer; the next tick
        // tries again, and a genuinely dead camera is already shown by the
        // status badge above.
      }
    }

    poll();
    const interval = setInterval(poll, DETECTIONS_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [camera.id]);

  return (
    <div className="overflow-hidden rounded-lg border border-border-subtle bg-surface-raised">
      <div className="flex items-center justify-between px-3 py-2">
        <div>
          <p className="text-sm text-ink">{camera.name}</p>
          <p className="text-xs text-ink-muted">{camera.location || "—"}</p>
        </div>
        <CameraStatusBadge camera={camera} />
      </div>

      <div className="relative aspect-video bg-black">
        {errored ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-xs text-ink-muted">
            <p>No live frame available.</p>
            <button
              type="button"
              onClick={() => {
                setErrored(false);
                setReloadToken((n) => n + 1);
              }}
              className="rounded-md border border-border-subtle px-2 py-1 text-ink"
            >
              Retry
            </button>
          </div>
        ) : (
          // eslint-disable-next-line @next/next/no-img-element -- an MJPEG multipart stream is not something next/image can proxy.
          <img
            key={reloadToken}
            src={`/api/cameras/${camera.id}/stream?r=${reloadToken}`}
            alt={`Live view: ${camera.name}`}
            className="h-full w-full object-contain"
            onError={() => setErrored(true)}
          />
        )}

        {detections ? (
          <div className="absolute bottom-2 left-2 rounded-md bg-black/60 px-2 py-1 text-xs text-white">
            {detections.person_count} {detections.person_count === 1 ? "person" : "people"}
            {tracks && tracks.track_count !== detections.person_count ? (
              <span className="ml-1.5 text-white/60">({tracks.track_count} tracked)</span>
            ) : null}
            <span className="ml-1.5 text-white/60">· {detections.inference_ms.toFixed(0)}ms</span>
          </div>
        ) : null}
      </div>
    </div>
  );
}
