"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import type { ApiError, Camera } from "@/lib/types";

const inputClass =
  "w-full rounded-md border border-border-subtle bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent";
const labelClass = "mb-1.5 block text-sm font-medium text-ink";

interface CameraFormProps {
  camera?: Camera;
  onDone: () => void;
  onCancel?: () => void;
}

/** Add/edit form. The same component for both: editing pre-fills from
 * `camera` and PATCHes; creating starts blank and POSTs. */
export function CameraForm({ camera, onDone, onCancel }: CameraFormProps) {
  const router = useRouter();
  const [name, setName] = useState(camera?.name ?? "");
  const [location, setLocation] = useState(camera?.location ?? "");
  const [rtspUrl, setRtspUrl] = useState(camera?.rtsp_url ?? "");
  const [username, setUsername] = useState(camera?.rtsp_username ?? "");
  const [password, setPassword] = useState("");
  const [transport, setTransport] = useState<Camera["transport"]>(camera?.transport ?? "tcp");
  const [mountType, setMountType] = useState<Camera["mount_type"]>(camera?.mount_type ?? "unknown");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const isEditing = Boolean(camera);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);

    const body: Record<string, unknown> = {
      name,
      location,
      rtsp_url: rtspUrl,
      rtsp_username: username,
      transport,
      mount_type: mountType,
    };
    // Blank means "leave the existing password unchanged" on the backend;
    // only send it when the admin actually typed something.
    if (password) body.rtsp_password = password;

    try {
      const response = await fetch(isEditing ? `/api/cameras/${camera!.id}` : "/api/cameras", {
        method: isEditing ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (!response.ok) {
        const errorBody = (await response.json().catch(() => null)) as ApiError | null;
        setError(errorBody?.error?.message ?? "Could not save the camera.");
        return;
      }

      router.refresh();
      onDone();
    } catch {
      setError("Could not reach the server.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4 rounded-lg border border-border-subtle bg-surface-raised p-4">
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className={labelClass} htmlFor="camera-name">Name</label>
          <input id="camera-name" required value={name} onChange={(e) => setName(e.target.value)} className={inputClass} />
        </div>
        <div>
          <label className={labelClass} htmlFor="camera-location">Location</label>
          <input id="camera-location" value={location} onChange={(e) => setLocation(e.target.value)} placeholder="e.g. Entrance" className={inputClass} />
        </div>
      </div>

      <div>
        <label className={labelClass} htmlFor="camera-url">RTSP URL</label>
        <input
          id="camera-url"
          required
          value={rtspUrl}
          onChange={(e) => setRtspUrl(e.target.value)}
          placeholder="rtsp://192.168.1.64:554/Streaming/Channels/101"
          className={`${inputClass} font-mono`}
        />
        <p className="mt-1 text-xs text-ink-muted">No username or password in the URL — use the fields below.</p>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div>
          <label className={labelClass} htmlFor="camera-username">Username</label>
          <input id="camera-username" value={username} onChange={(e) => setUsername(e.target.value)} className={inputClass} />
        </div>
        <div>
          <label className={labelClass} htmlFor="camera-password">
            Password {isEditing && camera?.has_password ? <span className="text-ink-muted">(unchanged if blank)</span> : null}
          </label>
          <input
            id="camera-password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={inputClass}
          />
        </div>
        <div>
          <label className={labelClass} htmlFor="camera-transport">Transport</label>
          <select
            id="camera-transport"
            value={transport}
            onChange={(e) => setTransport(e.target.value as Camera["transport"])}
            className={inputClass}
          >
            <option value="tcp">TCP (recommended)</option>
            <option value="udp">UDP</option>
          </select>
        </div>
      </div>

      <div>
        <label className={labelClass} htmlFor="camera-mount-type">Mount type</label>
        <select
          id="camera-mount-type"
          value={mountType}
          onChange={(e) => setMountType(e.target.value as Camera["mount_type"])}
          className={inputClass}
        >
          <option value="unknown">Unknown</option>
          <option value="overhead">Overhead</option>
          <option value="wall">Wall-mounted</option>
        </select>
        <p className="mt-1 text-xs text-ink-muted">
          Affects how confidently table occupancy is reported for this camera&apos;s tables — an
          overhead camera is reliable, a wall-mounted one only an approximation.
        </p>
      </div>

      {error ? <p role="alert" className="rounded-md bg-surface px-3 py-2 text-sm text-status-down">{error}</p> : null}

      <div className="flex gap-2">
        <button type="submit" disabled={pending} className="rounded-md bg-accent px-3 py-2 text-sm font-medium text-surface disabled:opacity-60">
          {pending ? "Saving…" : isEditing ? "Save changes" : "Add camera"}
        </button>
        {onCancel ? (
          <button type="button" onClick={onCancel} className="rounded-md border border-border-subtle px-3 py-2 text-sm text-ink">
            Cancel
          </button>
        ) : null}
      </div>
    </form>
  );
}
