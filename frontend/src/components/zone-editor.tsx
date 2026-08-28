"use client";

import { useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

import { entryDirection, midpoint, type Point } from "@/lib/zone-geometry";
import type { Camera, Zone } from "@/lib/types";

const MIN_DRAG_DISTANCE = 10;
const ARROW_LENGTH = 28;

/**
 * Draws entrance/exit lines on top of the camera's last snapshot.
 *
 * The SVG's viewBox is set to the camera's actual reported resolution, not
 * its on-screen pixel size, so every point captured here is already in the
 * same pixel space the AI worker's crossing detector uses (see
 * ai_worker/worker/zones.py) -- no separate scale factor to get wrong.
 */
export function ZoneEditor({ camera, initialZones }: { camera: Camera; initialZones: Zone[] }) {
  const [zones, setZones] = useState(initialZones);
  const [drawing, setDrawing] = useState<{ start: Point; current: Point } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const svgRef = useRef<SVGSVGElement>(null);

  const width = camera.resolution_width;
  const height = camera.resolution_height;
  const hasResolution = Boolean(width && height);

  function svgPoint(event: ReactPointerEvent<SVGSVGElement>): Point | null {
    const svg = svgRef.current;
    const ctm = svg?.getScreenCTM();
    if (!svg || !ctm) return null;
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    const transformed = point.matrixTransform(ctm.inverse());
    return { x: transformed.x, y: transformed.y };
  }

  function onPointerDown(event: ReactPointerEvent<SVGSVGElement>) {
    if (!hasResolution || busy) return;
    const point = svgPoint(event);
    if (point) setDrawing({ start: point, current: point });
  }

  function onPointerMove(event: ReactPointerEvent<SVGSVGElement>) {
    if (!drawing) return;
    const point = svgPoint(event);
    if (point) setDrawing((prev) => (prev ? { ...prev, current: point } : prev));
  }

  async function onPointerUp() {
    if (!drawing) return;
    const { start, current } = drawing;
    setDrawing(null);

    if (Math.hypot(current.x - start.x, current.y - start.y) < MIN_DRAG_DISTANCE) {
      return; // an accidental click/tap, not an intentional line
    }

    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`/api/cameras/${camera.id}/zones`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: `Zone ${zones.length + 1}`,
          point_a_x: Math.round(start.x),
          point_a_y: Math.round(start.y),
          point_b_x: Math.round(current.x),
          point_b_y: Math.round(current.y),
        }),
      });
      if (!response.ok) {
        setError("Could not save the new line.");
        return;
      }
      const zone = (await response.json()) as Zone;
      setZones((prev) => [...prev, zone]);
    } catch {
      setError("Could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  async function updateZone(id: string, patch: Partial<Zone>) {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`/api/cameras/${camera.id}/zones/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      if (!response.ok) {
        setError("Could not save that change.");
        return;
      }
      const updated = (await response.json()) as Zone;
      setZones((prev) => prev.map((zone) => (zone.id === id ? updated : zone)));
    } catch {
      setError("Could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  async function deleteZone(id: string) {
    if (!confirm("Remove this line? Entry/exit detection for it stops immediately.")) return;
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`/api/cameras/${camera.id}/zones/${id}`, { method: "DELETE" });
      if (!response.ok && response.status !== 204) {
        setError("Could not remove that line.");
        return;
      }
      setZones((prev) => prev.filter((zone) => zone.id !== id));
    } catch {
      setError("Could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="overflow-hidden rounded-lg border border-border-subtle bg-black">
        {!hasResolution || !width || !height ? (
          <div className="flex aspect-video items-center justify-center px-6 text-center text-sm text-ink-muted">
            Waiting for this camera&apos;s first frame — lines can be drawn once its resolution is
            known.
          </div>
        ) : (
          <div className="relative" style={{ aspectRatio: `${width} / ${height}` }}>
            {/* eslint-disable-next-line @next/next/no-img-element -- a backend-proxied snapshot, not something next/image can fetch. */}
            <img
              src={`/api/cameras/${camera.id}/snapshot`}
              alt={`Snapshot: ${camera.name}`}
              className="absolute inset-0 h-full w-full object-contain"
            />
            <svg
              ref={svgRef}
              viewBox={`0 0 ${width} ${height}`}
              className="absolute inset-0 h-full w-full cursor-crosshair touch-none"
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
            >
              {zones.map((zone) => (
                <ZoneShape key={zone.id} zone={zone} />
              ))}
              {drawing ? (
                <line
                  x1={drawing.start.x}
                  y1={drawing.start.y}
                  x2={drawing.current.x}
                  y2={drawing.current.y}
                  stroke="white"
                  strokeWidth={3}
                  strokeDasharray="6 4"
                />
              ) : null}
            </svg>
          </div>
        )}
      </div>

      <p className="text-xs text-ink-muted">
        Click and drag across the frame to draw a new line. The short arrow on each line marks the
        direction counted as an entry — use &ldquo;Flip direction&rdquo; below to reverse it.
      </p>

      {error ? <p role="alert" className="text-sm text-status-down">{error}</p> : null}

      <ZoneList zones={zones} busy={busy} onUpdate={updateZone} onDelete={deleteZone} />
    </div>
  );
}

function ZoneShape({ zone }: { zone: Zone }) {
  const a: Point = { x: zone.point_a_x, y: zone.point_a_y };
  const b: Point = { x: zone.point_b_x, y: zone.point_b_y };
  const mid = midpoint(a, b);
  const direction = entryDirection(a, b, zone.entry_is_positive_side);
  const tip: Point = {
    x: mid.x + direction.x * ARROW_LENGTH,
    y: mid.y + direction.y * ARROW_LENGTH,
  };

  return (
    <g className={zone.is_active ? "text-accent" : "text-ink-muted"} opacity={zone.is_active ? 1 : 0.6}>
      <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="currentColor" strokeWidth={3} />
      <circle cx={a.x} cy={a.y} r={4} fill="currentColor" />
      <circle cx={b.x} cy={b.y} r={4} fill="currentColor" />
      <line x1={mid.x} y1={mid.y} x2={tip.x} y2={tip.y} stroke="currentColor" strokeWidth={2} />
      <ArrowHead at={tip} direction={direction} />
      <text x={mid.x + 6} y={mid.y - 8} fontSize={13} fill="currentColor" className="select-none">
        {zone.name}
      </text>
    </g>
  );
}

function ArrowHead({ at, direction }: { at: Point; direction: Point }) {
  const size = 7;
  // Perpendicular to `direction`, to build a simple triangular arrowhead.
  const perp: Point = { x: -direction.y, y: direction.x };
  const back: Point = { x: at.x - direction.x * size, y: at.y - direction.y * size };
  const left: Point = { x: back.x + perp.x * (size / 2), y: back.y + perp.y * (size / 2) };
  const right: Point = { x: back.x - perp.x * (size / 2), y: back.y - perp.y * (size / 2) };

  return <polygon points={`${at.x},${at.y} ${left.x},${left.y} ${right.x},${right.y}`} fill="currentColor" />;
}

function ZoneList({
  zones,
  busy,
  onUpdate,
  onDelete,
}: {
  zones: Zone[];
  busy: boolean;
  onUpdate: (id: string, patch: Partial<Zone>) => void;
  onDelete: (id: string) => void;
}) {
  if (zones.length === 0) {
    return (
      <p className="rounded-lg border border-border-subtle px-4 py-6 text-center text-sm text-ink-muted">
        No lines yet. Draw one on the frame above to start detecting entries and exits.
      </p>
    );
  }

  return (
    <ul className="space-y-2">
      {zones.map((zone) => (
        <ZoneListRow key={zone.id} zone={zone} busy={busy} onUpdate={onUpdate} onDelete={onDelete} />
      ))}
    </ul>
  );
}

function ZoneListRow({
  zone,
  busy,
  onUpdate,
  onDelete,
}: {
  zone: Zone;
  busy: boolean;
  onUpdate: (id: string, patch: Partial<Zone>) => void;
  onDelete: (id: string) => void;
}) {
  const [name, setName] = useState(zone.name);

  return (
    <li className="flex flex-wrap items-center gap-3 rounded-lg border border-border-subtle px-4 py-3">
      <span
        className={`size-2.5 shrink-0 rounded-full ${zone.is_active ? "bg-accent" : "bg-ink-muted"}`}
        aria-hidden
      />
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        onBlur={() => {
          if (name.trim() && name !== zone.name) onUpdate(zone.id, { name: name.trim() });
        }}
        disabled={busy}
        className="min-w-0 flex-1 rounded-md border border-border-subtle bg-surface px-2 py-1 text-sm text-ink outline-none focus:border-accent"
      />
      <button
        type="button"
        disabled={busy}
        onClick={() => onUpdate(zone.id, { entry_is_positive_side: !zone.entry_is_positive_side })}
        className="rounded-md border border-border-subtle px-2 py-1 text-xs text-ink disabled:opacity-60"
      >
        Flip direction
      </button>
      <button
        type="button"
        disabled={busy}
        onClick={() => onUpdate(zone.id, { is_active: !zone.is_active })}
        className="rounded-md border border-border-subtle px-2 py-1 text-xs text-ink disabled:opacity-60"
      >
        {zone.is_active ? "Active" : "Disabled"}
      </button>
      <button
        type="button"
        disabled={busy}
        onClick={() => onDelete(zone.id)}
        className="rounded-md border border-border-subtle px-2 py-1 text-xs text-status-down disabled:opacity-60"
      >
        Delete
      </button>
    </li>
  );
}
