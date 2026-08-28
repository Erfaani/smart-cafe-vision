import type { Camera } from "@/lib/types";

const LABELS: Record<Camera["connection_status"], string> = {
  unknown: "Never connected",
  connecting: "Connecting",
  connected: "Connected",
  disconnected: "Disconnected",
  error: "Error",
};

const STYLES: Record<Camera["connection_status"], string> = {
  unknown: "text-ink-muted",
  connecting: "text-status-degraded",
  connected: "text-status-ok",
  disconnected: "text-ink-muted",
  error: "text-status-down",
};

/**
 * Mirrors StatusBadge's visual language (a coloured dot + label, colour never
 * the only signal) but for the camera-specific status vocabulary, which is
 * not the same enum as system component health.
 */
export function CameraStatusBadge({ camera }: { camera: Camera }) {
  // A camera reporting "connected" that has gone quiet is not honestly
  // connected -- see Camera.is_stale on the backend for why this is a
  // distinct signal from connection_status itself.
  const stale = camera.connection_status === "connected" && camera.is_stale;
  const label = stale ? "Stalled" : LABELS[camera.connection_status];
  const style = stale ? "text-status-degraded" : STYLES[camera.connection_status];

  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${style}`} aria-label={`Status: ${label}`}>
      <span className="size-1.5 rounded-full bg-current" aria-hidden />
      {label}
    </span>
  );
}
