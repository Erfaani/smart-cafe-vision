import type { ComponentStatus } from "@/lib/types";

const LABELS: Record<ComponentStatus, string> = {
  ok: "OK",
  degraded: "Degraded",
  down: "Down",
};

const STYLES: Record<ComponentStatus, string> = {
  ok: "text-status-ok",
  degraded: "text-status-degraded",
  down: "text-status-down",
};

export function StatusBadge({ status }: { status: ComponentStatus }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 text-xs font-medium ${STYLES[status]}`}
      // Colour alone must not carry the meaning: café staff read this at a
      // glance, sometimes on a washed-out screen, sometimes colour-blind.
      aria-label={`Status: ${LABELS[status]}`}
    >
      <span className="size-1.5 rounded-full bg-current" aria-hidden />
      {LABELS[status]}
    </span>
  );
}
