import { DisplayEmptyState } from "@/components/display/empty-state";
import type { CameraLiveTracks } from "@/lib/types";

/**
 * The live tracking overlay -- synthetic dots at each tracked person's real
 * position, coloured by stay time, never actual video (see
 * docs/architecture.md for why: a public, unauthenticated route showing raw
 * camera footage would be a new and meaningfully larger privacy exposure
 * than this project otherwise accepts).
 *
 * Each camera's SVG viewBox is set to its own reported resolution, so a
 * dot's (x, y) -- already in that same pixel space, computed server-side in
 * apps/display/live.py -- places correctly with no client-side scaling math,
 * the same technique the Phase 5 zone editor uses.
 */
export function DisplayNormalMode({ tracks }: { tracks: CameraLiveTracks[] }) {
  if (tracks.length === 0) {
    return <DisplayEmptyState message="No cameras are live right now." />;
  }

  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-3">
      {tracks.map((camera) => (
        <CameraOverlayCard key={camera.camera_id} camera={camera} />
      ))}
    </div>
  );
}

function CameraOverlayCard({ camera }: { camera: CameraLiveTracks }) {
  // A dot sized relative to the camera's own coordinate space, not a fixed
  // pixel radius -- so it reads consistently whether the camera is 720p or
  // 4K, and scales correctly with the SVG's own viewBox-to-card scaling.
  const dotRadius = camera.resolution_width * 0.018;

  return (
    <div className="overflow-hidden rounded-2xl border border-white/10 bg-white/5">
      <div className="px-5 py-3 text-lg font-medium text-white/90">{camera.camera_name}</div>
      <div className="relative aspect-video bg-zinc-900">
        <svg
          viewBox={`0 0 ${camera.resolution_width} ${camera.resolution_height}`}
          className="absolute inset-0 h-full w-full"
        >
          {camera.people.map((person) => (
            <circle
              key={person.track_id}
              cx={person.x}
              cy={person.y}
              r={dotRadius}
              fill={person.color}
              opacity={0.9}
            />
          ))}
        </svg>
        {camera.people.length === 0 ? (
          <div className="absolute inset-0 flex items-center justify-center text-white/30">
            Nobody here right now
          </div>
        ) : null}
      </div>
      <div className="px-5 py-3 text-sm text-white/50">
        {camera.people.length} {camera.people.length === 1 ? "person" : "people"}
      </div>
    </div>
  );
}
