"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { CameraForm } from "@/components/camera-form";
import { CameraStatusBadge } from "@/components/camera-status-badge";
import type { Camera, CameraTestConnectionResult } from "@/lib/types";

function relativeTime(iso: string | null): string {
  if (!iso) return "never";
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return `${Math.floor(seconds)}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function CameraRow({ camera }: { camera: Camera }) {
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<CameraTestConnectionResult | null>(null);
  const [busy, setBusy] = useState(false);

  async function toggleEnabled() {
    setBusy(true);
    try {
      await fetch(`/api/cameras/${camera.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_enabled: !camera.is_enabled }),
      });
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  async function testConnection() {
    setTesting(true);
    setTestResult(null);
    try {
      const response = await fetch(`/api/cameras/${camera.id}/test-connection`, { method: "POST" });
      setTestResult((await response.json()) as CameraTestConnectionResult);
    } catch {
      setTestResult({ status: "error", ok: false, message: "Could not reach the server." });
    } finally {
      setTesting(false);
    }
  }

  async function deleteCamera() {
    if (!confirm(`Remove "${camera.name}"? This cannot be undone.`)) return;
    setBusy(true);
    try {
      await fetch(`/api/cameras/${camera.id}`, { method: "DELETE" });
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  if (editing) {
    return (
      <tr>
        <td colSpan={6} className="px-4 py-4">
          <CameraForm camera={camera} onDone={() => setEditing(false)} onCancel={() => setEditing(false)} />
        </td>
      </tr>
    );
  }

  return (
    <>
      <tr className="border-t border-border-subtle">
        <td className="px-4 py-3">
          <p className="text-sm text-ink">{camera.name}</p>
          <p className="text-xs text-ink-muted">{camera.location || "—"}</p>
        </td>
        <td className="px-4 py-3 font-mono text-xs text-ink-muted">{camera.rtsp_url}</td>
        <td className="px-4 py-3">
          <CameraStatusBadge camera={camera} />
          {camera.last_error ? <p className="mt-0.5 text-xs text-status-down">{camera.last_error}</p> : null}
        </td>
        <td className="px-4 py-3 text-xs text-ink-muted">
          {relativeTime(camera.last_frame_at)}
          {camera.resolution_width ? (
            <span className="block">{camera.resolution_width}×{camera.resolution_height} · {camera.last_fps?.toFixed(1)} fps</span>
          ) : null}
          {camera.last_person_count !== null ? (
            <span className="block">
              {camera.last_person_count} {camera.last_person_count === 1 ? "person" : "people"}
              {camera.last_track_count !== null && camera.last_track_count !== camera.last_person_count
                ? ` (${camera.last_track_count} tracked)`
                : null}
              {" · "}
              {camera.last_inference_ms?.toFixed(0)}ms
            </span>
          ) : null}
        </td>
        <td className="px-4 py-3">
          <button
            type="button"
            onClick={toggleEnabled}
            disabled={busy}
            className="rounded-md border border-border-subtle px-2 py-1 text-xs text-ink disabled:opacity-60"
          >
            {camera.is_enabled ? "Enabled" : "Disabled"}
          </button>
        </td>
        <td className="px-4 py-3 text-right">
          <div className="flex justify-end gap-2">
            <button type="button" onClick={testConnection} disabled={testing} className="rounded-md border border-border-subtle px-2 py-1 text-xs text-ink disabled:opacity-60">
              {testing ? "Testing…" : "Test"}
            </button>
            <Link href={`/dashboard/cameras/${camera.id}/zones`} className="rounded-md border border-border-subtle px-2 py-1 text-xs text-ink">
              Zones
            </Link>
            <Link href={`/dashboard/cameras/${camera.id}/tables`} className="rounded-md border border-border-subtle px-2 py-1 text-xs text-ink">
              Tables
            </Link>
            <button type="button" onClick={() => setEditing(true)} className="rounded-md border border-border-subtle px-2 py-1 text-xs text-ink">
              Edit
            </button>
            <button type="button" onClick={deleteCamera} disabled={busy} className="rounded-md border border-border-subtle px-2 py-1 text-xs text-status-down disabled:opacity-60">
              Delete
            </button>
          </div>
        </td>
      </tr>
      {testResult ? (
        <tr>
          <td colSpan={6} className="px-4 pb-3">
            <p className={`text-xs ${testResult.ok ? "text-status-ok" : "text-status-down"}`}>
              {testResult.message}
            </p>
          </td>
        </tr>
      ) : null}
    </>
  );
}

export function CameraTable({ cameras }: { cameras: Camera[] }) {
  if (cameras.length === 0) {
    return (
      <p className="rounded-lg border border-border-subtle px-4 py-6 text-center text-sm text-ink-muted">
        No cameras yet. Add one above to get started.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border-subtle">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs font-medium uppercase tracking-wide text-ink-muted">
            <th className="px-4 py-2.5">Camera</th>
            <th className="px-4 py-2.5">RTSP URL</th>
            <th className="px-4 py-2.5">Status</th>
            <th className="px-4 py-2.5">Last frame</th>
            <th className="px-4 py-2.5">Enabled</th>
            <th className="px-4 py-2.5" />
          </tr>
        </thead>
        <tbody>
          {cameras.map((camera) => (
            <CameraRow key={camera.id} camera={camera} />
          ))}
        </tbody>
      </table>
    </div>
  );
}
