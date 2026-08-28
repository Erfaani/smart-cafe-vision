"use client";

import { useState, type FormEvent } from "react";

import type { ApiError } from "@/lib/types";

const inputClass =
  "w-full rounded-md border border-border-subtle bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent";
const labelClass = "mb-1.5 block text-sm font-medium text-ink";

/** Self-service password change -- the backend (/api/v1/auth/password/) has
 * existed since Phase 1, but no dashboard page ever called it; closed in
 * Phase 11 alongside the same gap for staff management and display
 * messages. */
export function AccountPageClient() {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setSuccess(false);
    try {
      const response = await fetch("/api/auth/password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as ApiError | null;
        setError(body?.error?.message ?? "Could not change your password.");
        return;
      }
      setCurrentPassword("");
      setNewPassword("");
      setSuccess(true);
    } catch {
      setError("Could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="max-w-sm space-y-4 rounded-lg border border-border-subtle bg-surface-raised p-4">
      <div>
        <label className={labelClass} htmlFor="current-password">Current password</label>
        <input
          id="current-password" type="password" required autoComplete="current-password"
          value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)}
          className={inputClass}
        />
      </div>
      <div>
        <label className={labelClass} htmlFor="new-password">New password</label>
        <input
          id="new-password" type="password" required autoComplete="new-password"
          value={newPassword} onChange={(e) => setNewPassword(e.target.value)}
          className={inputClass}
        />
        <p className="mt-1 text-xs text-ink-muted">At least 10 characters.</p>
      </div>
      {error ? <p role="alert" className="text-sm text-status-down">{error}</p> : null}
      {success ? <p className="text-sm text-status-ok">Password changed.</p> : null}
      <button
        type="submit"
        disabled={busy}
        className="rounded-md bg-accent px-3 py-2 text-sm font-medium text-surface disabled:opacity-60"
      >
        {busy ? "Saving…" : "Change password"}
      </button>
    </form>
  );
}
