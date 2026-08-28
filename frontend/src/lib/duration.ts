/**
 * Formats a duration in seconds for a customer-facing "how long has this
 * person been here" display -- short units, and seconds drop off once a stay
 * reaches an hour (nobody needs second-level precision for spec §5's stay
 * time at that point).
 */
export function formatDuration(totalSeconds: number): string {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;

  if (hours > 0) return `${hours}h ${String(minutes).padStart(2, "0")}m`;
  if (minutes > 0) return `${minutes}m ${String(secs).padStart(2, "0")}s`;
  return `${secs}s`;
}
