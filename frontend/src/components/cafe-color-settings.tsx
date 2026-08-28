"use client";

import { useMemo, useState } from "react";

import { colorForDuration, type ColorStop } from "@/lib/stay-color";
import type { ApiError } from "@/lib/types";

const MIN_STOPS = 2;
const PREVIEW_SAMPLE_COUNT = 40;

function secondsToMinutesLabel(seconds: number): string {
  return String(Math.round(seconds / 60));
}

/** Ordered, so a gap in `seconds` never silently breaks interpolation --
 * the same strictly-increasing, first-stop-at-zero rule the backend
 * enforces in apps/core/color.py::validate_color_stops. */
function isValidOrder(stops: ColorStop[]): boolean {
  if (stops.length < MIN_STOPS) return false;
  const first = stops[0];
  if (!first || first.seconds !== 0) return false;
  return stops.every((stop, i) => {
    if (i === 0) return true;
    const previous = stops[i - 1];
    return previous !== undefined && stop.seconds > previous.seconds;
  });
}

export function CafeColorSettings({ initialStops }: { initialStops: ColorStop[] }) {
  const [stops, setStops] = useState(initialStops);
  const [saved, setSaved] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const valid = isValidOrder(stops);

  const previewStops = useMemo(() => {
    const last = stops.at(-1);
    if (!valid || !last) return [];
    const maxSeconds = last.seconds;
    return Array.from({ length: PREVIEW_SAMPLE_COUNT + 1 }, (_, i) => {
      const seconds = (maxSeconds * i) / PREVIEW_SAMPLE_COUNT;
      return colorForDuration(seconds, stops);
    });
  }, [stops, valid]);

  function updateStop(index: number, patch: Partial<ColorStop>) {
    setStops((prev) => prev.map((stop, i) => (i === index ? { ...stop, ...patch } : stop)));
    setSaved(false);
  }

  function addStop() {
    const last = stops.at(-1);
    if (!last) return;
    setStops((prev) => [...prev, { seconds: last.seconds + 600, color: last.color }]);
    setSaved(false);
  }

  function removeStop(index: number) {
    setStops((prev) => prev.filter((_, i) => i !== index));
    setSaved(false);
  }

  async function save() {
    setPending(true);
    setError(null);
    try {
      const response = await fetch("/api/cafe", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stay_color_stops: stops }),
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as ApiError | null;
        setError(body?.error?.message ?? "Could not save these colours.");
        return;
      }
      setSaved(true);
    } catch {
      setError("Could not reach the server.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="space-y-4 rounded-lg border border-border-subtle bg-surface-raised p-4">
      <div>
        <h2 className="text-sm font-medium text-ink">Stay-time colour</h2>
        <p className="mt-1 text-xs text-ink-muted">
          How a customer&apos;s box on the public display and their row on the Customers page
          change colour the longer they stay. The first stop always starts at 0 minutes; add more
          stops for a smoother slide, or fewer for a sharper one.
        </p>
      </div>

      {valid ? (
        <div
          className="h-3 w-full rounded-full"
          style={{ background: `linear-gradient(to right, ${previewStops.join(", ")})` }}
          aria-hidden
        />
      ) : (
        <p className="text-xs text-status-down">
          Stops must start at 0 minutes and each one must be later than the last.
        </p>
      )}

      <ul className="space-y-2">
        {stops.map((stop, index) => (
          <li key={index} className="flex items-center gap-3">
            <input
              type="color"
              value={stop.color}
              onChange={(e) => updateStop(index, { color: e.target.value })}
              className="h-8 w-10 shrink-0 cursor-pointer rounded border border-border-subtle bg-transparent"
              aria-label={`Colour for stop ${index + 1}`}
            />
            <div className="flex items-center gap-1.5 text-sm text-ink">
              <input
                type="number"
                min={0}
                value={secondsToMinutesLabel(stop.seconds)}
                disabled={index === 0}
                onChange={(e) => updateStop(index, { seconds: Math.max(0, Number(e.target.value)) * 60 })}
                className="w-16 rounded-md border border-border-subtle bg-surface px-2 py-1 text-sm text-ink outline-none focus:border-accent disabled:opacity-60"
              />
              <span className="text-ink-muted">min</span>
            </div>
            <button
              type="button"
              onClick={() => removeStop(index)}
              disabled={stops.length <= MIN_STOPS}
              className="ml-auto rounded-md border border-border-subtle px-2 py-1 text-xs text-status-down disabled:opacity-40"
            >
              Remove
            </button>
          </li>
        ))}
      </ul>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={addStop}
          className="rounded-md border border-border-subtle px-3 py-1.5 text-xs text-ink"
        >
          Add stop
        </button>
        <button
          type="button"
          onClick={save}
          disabled={!valid || pending || saved}
          className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-surface disabled:opacity-60"
        >
          {pending ? "Saving…" : saved ? "Saved" : "Save changes"}
        </button>
      </div>

      {error ? <p role="alert" className="text-sm text-status-down">{error}</p> : null}
    </div>
  );
}
