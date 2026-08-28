"use client";

import { useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

import type { Point } from "@/lib/zone-geometry";
import type { Camera, TableZone } from "@/lib/types";

const MIN_DRAG_DISTANCE = 10;

interface Rect {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

function normalize(start: Point, current: Point): Rect {
  return {
    x1: Math.min(start.x, current.x),
    y1: Math.min(start.y, current.y),
    x2: Math.max(start.x, current.x),
    y2: Math.max(start.y, current.y),
  };
}

/**
 * Draws table rectangles on top of the camera's last snapshot -- the same
 * click-and-drag-on-an-SVG-overlay technique as ZoneEditor (Phase 5), but a
 * rectangle instead of a line: a table is an area to be covered, not a
 * threshold to be crossed. See backend/apps/cameras/models.py's TableZone
 * docstring for why that is a genuinely different shape, not a variant of
 * the same one.
 */
export function TableEditor({ camera, initialTables }: { camera: Camera; initialTables: TableZone[] }) {
  const [tables, setTables] = useState(initialTables);
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
      return; // an accidental click/tap, not an intentional rectangle
    }

    const rect = normalize(start, current);
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`/api/cameras/${camera.id}/tables`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: `Table ${tables.length + 1}`,
          x1: Math.round(rect.x1), y1: Math.round(rect.y1),
          x2: Math.round(rect.x2), y2: Math.round(rect.y2),
        }),
      });
      if (!response.ok) {
        setError("Could not save the new table.");
        return;
      }
      const table = (await response.json()) as TableZone;
      setTables((prev) => [...prev, table]);
    } catch {
      setError("Could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  async function updateTable(id: string, patch: Partial<TableZone>) {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`/api/cameras/${camera.id}/tables/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      if (!response.ok) {
        setError("Could not save that change.");
        return;
      }
      const updated = (await response.json()) as TableZone;
      setTables((prev) => prev.map((table) => (table.id === id ? updated : table)));
    } catch {
      setError("Could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  async function deleteTable(id: string) {
    if (!confirm("Remove this table? Occupancy detection for it stops immediately.")) return;
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`/api/cameras/${camera.id}/tables/${id}`, { method: "DELETE" });
      if (!response.ok && response.status !== 204) {
        setError("Could not remove that table.");
        return;
      }
      setTables((prev) => prev.filter((table) => table.id !== id));
    } catch {
      setError("Could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      {camera.mount_type !== "overhead" ? (
        <p className="rounded-lg border border-border-subtle bg-surface-raised px-4 py-3 text-xs text-ink-muted">
          {camera.mount_type === "wall"
            ? "This camera is wall-mounted, so table occupancy here is an approximation -- a person standing near a table can register the same as one seated at it."
            : "This camera's mount type isn't set. An overhead camera gives reliable table occupancy; a wall-mounted one only an approximation -- set it on the camera list for an honest reading here."}
        </p>
      ) : null}

      <div className="overflow-hidden rounded-lg border border-border-subtle bg-black">
        {!hasResolution || !width || !height ? (
          <div className="flex aspect-video items-center justify-center px-6 text-center text-sm text-ink-muted">
            Waiting for this camera&apos;s first frame — tables can be drawn once its resolution is
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
              {tables.map((table) => (
                <TableShape key={table.id} table={table} />
              ))}
              {drawing
                ? (() => {
                    const rect = normalize(drawing.start, drawing.current);
                    return (
                      <rect
                        x={rect.x1} y={rect.y1}
                        width={rect.x2 - rect.x1} height={rect.y2 - rect.y1}
                        fill="none" stroke="white" strokeWidth={3} strokeDasharray="6 4"
                      />
                    );
                  })()
                : null}
            </svg>
          </div>
        )}
      </div>

      <p className="text-xs text-ink-muted">
        Click and drag across the frame to draw a new table.
      </p>

      {error ? <p role="alert" className="text-sm text-status-down">{error}</p> : null}

      <TableList tables={tables} busy={busy} onUpdate={updateTable} onDelete={deleteTable} />
    </div>
  );
}

function TableShape({ table }: { table: TableZone }) {
  return (
    <g className={table.is_active ? "text-accent" : "text-ink-muted"} opacity={table.is_active ? 1 : 0.6}>
      <rect
        x={table.x1} y={table.y1}
        width={table.x2 - table.x1} height={table.y2 - table.y1}
        fill="currentColor" fillOpacity={0.15} stroke="currentColor" strokeWidth={2}
      />
      <text
        x={(table.x1 + table.x2) / 2}
        y={(table.y1 + table.y2) / 2}
        textAnchor="middle"
        dominantBaseline="middle"
        fontSize={13}
        fill="currentColor"
        className="select-none"
      >
        {table.name}
      </text>
    </g>
  );
}

function TableList({
  tables,
  busy,
  onUpdate,
  onDelete,
}: {
  tables: TableZone[];
  busy: boolean;
  onUpdate: (id: string, patch: Partial<TableZone>) => void;
  onDelete: (id: string) => void;
}) {
  if (tables.length === 0) {
    return (
      <p className="rounded-lg border border-border-subtle px-4 py-6 text-center text-sm text-ink-muted">
        No tables yet. Draw one on the frame above to start detecting occupancy.
      </p>
    );
  }

  return (
    <ul className="space-y-2">
      {tables.map((table) => (
        <TableListRow key={table.id} table={table} busy={busy} onUpdate={onUpdate} onDelete={onDelete} />
      ))}
    </ul>
  );
}

function TableListRow({
  table,
  busy,
  onUpdate,
  onDelete,
}: {
  table: TableZone;
  busy: boolean;
  onUpdate: (id: string, patch: Partial<TableZone>) => void;
  onDelete: (id: string) => void;
}) {
  const [name, setName] = useState(table.name);

  return (
    <li className="flex flex-wrap items-center gap-3 rounded-lg border border-border-subtle px-4 py-3">
      <span
        className={`size-2.5 shrink-0 rounded-full ${table.is_active ? "bg-accent" : "bg-ink-muted"}`}
        aria-hidden
      />
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        onBlur={() => {
          if (name.trim() && name !== table.name) onUpdate(table.id, { name: name.trim() });
        }}
        disabled={busy}
        className="min-w-0 flex-1 rounded-md border border-border-subtle bg-surface px-2 py-1 text-sm text-ink outline-none focus:border-accent"
      />
      <button
        type="button"
        disabled={busy}
        onClick={() => onUpdate(table.id, { is_active: !table.is_active })}
        className="rounded-md border border-border-subtle px-2 py-1 text-xs text-ink disabled:opacity-60"
      >
        {table.is_active ? "Active" : "Disabled"}
      </button>
      <button
        type="button"
        disabled={busy}
        onClick={() => onDelete(table.id)}
        className="rounded-md border border-border-subtle px-2 py-1 text-xs text-status-down disabled:opacity-60"
      >
        Delete
      </button>
    </li>
  );
}
