"use client";

import { Fragment, useState, type FormEvent } from "react";

import type { ApiError, Role, User } from "@/lib/types";

const inputClass =
  "w-full rounded-md border border-border-subtle bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent";
const labelClass = "mb-1.5 block text-sm font-medium text-ink";

const ROLE_LABELS: Record<Role, string> = {
  owner: "Owner",
  manager: "Manager",
  staff: "Staff",
  viewer: "Viewer",
};

/**
 * Staff account management (spec: JWT auth with roles, Phase 1) -- the API
 * has existed since Phase 1, but no dashboard page ever called it; adding
 * a second account meant a technician running a management command. Closed
 * in Phase 11 alongside the same gap for display messages.
 */
export function StaffPageClient({ initialStaff, currentUserId }: { initialStaff: User[]; currentUserId: string }) {
  const [staff, setStaff] = useState(initialStaff);
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("staff");
  // Shown once, right after a reset -- never re-fetchable, same reasoning as
  // `manage.py bootstrap`'s generated owner password.
  const [resetPasswords, setResetPasswords] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/staff", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, full_name: fullName, password, role }),
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as ApiError | null;
        setError(body?.error?.message ?? "Could not create the account.");
        return;
      }
      const user = (await response.json()) as User;
      setStaff((prev) => [...prev, user]);
      setEmail("");
      setFullName("");
      setPassword("");
      setRole("staff");
    } catch {
      setError("Could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  async function changeRole(id: string, newRole: Role) {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`/api/staff/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role: newRole }),
      });
      if (!response.ok) {
        setError("Could not change that account's role.");
        return;
      }
      const user = (await response.json()) as User;
      setStaff((prev) => prev.map((s) => (s.id === id ? user : s)));
    } catch {
      setError("Could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  async function toggleActive(target: User) {
    setBusy(true);
    setError(null);
    try {
      const response = target.is_active
        ? await fetch(`/api/staff/${target.id}/deactivate`, { method: "POST" })
        : await fetch(`/api/staff/${target.id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ is_active: true }),
          });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as ApiError | null;
        setError(body?.error?.message ?? "Could not update that account.");
        return;
      }
      const user = (await response.json()) as User;
      setStaff((prev) => prev.map((s) => (s.id === target.id ? user : s)));
    } catch {
      setError("Could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  async function resetPassword(id: string) {
    if (!confirm("Generate a new password for this account? Their current password stops working immediately.")) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`/api/staff/${id}/reset-password`, { method: "POST" });
      if (!response.ok) {
        setError("Could not reset that account's password.");
        return;
      }
      const body = (await response.json()) as { password: string };
      setResetPasswords((prev) => ({ ...prev, [id]: body.password }));
    } catch {
      setError("Could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <form onSubmit={onSubmit} className="space-y-4 rounded-lg border border-border-subtle bg-surface-raised p-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className={labelClass} htmlFor="staff-email">Email</label>
            <input
              id="staff-email" type="email" required
              value={email} onChange={(e) => setEmail(e.target.value)}
              className={inputClass}
            />
          </div>
          <div>
            <label className={labelClass} htmlFor="staff-name">Full name</label>
            <input
              id="staff-name" required
              value={fullName} onChange={(e) => setFullName(e.target.value)}
              className={inputClass}
            />
          </div>
          <div>
            <label className={labelClass} htmlFor="staff-password">Temporary password</label>
            <input
              id="staff-password" type="password" required autoComplete="new-password"
              value={password} onChange={(e) => setPassword(e.target.value)}
              className={inputClass}
            />
            <p className="mt-1 text-xs text-ink-muted">At least 10 characters. They can change it after signing in.</p>
          </div>
          <div>
            <label className={labelClass} htmlFor="staff-role">Role</label>
            <select
              id="staff-role" value={role} onChange={(e) => setRole(e.target.value as Role)}
              className={inputClass}
            >
              {(Object.keys(ROLE_LABELS) as Role[]).map((r) => (
                <option key={r} value={r}>{ROLE_LABELS[r]}</option>
              ))}
            </select>
          </div>
        </div>
        {error ? <p role="alert" className="text-sm text-status-down">{error}</p> : null}
        <button
          type="submit"
          disabled={busy}
          className="rounded-md bg-accent px-3 py-2 text-sm font-medium text-surface disabled:opacity-60"
        >
          {busy ? "Creating…" : "Add account"}
        </button>
      </form>

      {staff.length === 0 ? (
        <p className="rounded-lg border border-border-subtle px-4 py-6 text-center text-sm text-ink-muted">
          No staff accounts yet.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border-subtle">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs font-medium uppercase tracking-wide text-ink-muted">
                <th className="px-4 py-2.5">Name</th>
                <th className="px-4 py-2.5">Email</th>
                <th className="px-4 py-2.5">Role</th>
                <th className="px-4 py-2.5">Status</th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {staff.map((member) => {
                const isSelf = member.id === currentUserId;
                const revealedPassword = resetPasswords[member.id];
                return (
                  <Fragment key={member.id}>
                    <tr className="border-t border-border-subtle">
                      <td className="px-4 py-3 text-ink">
                        {member.display_name}
                        {isSelf ? <span className="ml-1.5 text-xs text-ink-muted">(you)</span> : null}
                      </td>
                      <td className="px-4 py-3 text-ink-muted">{member.email}</td>
                      <td className="px-4 py-3">
                        <select
                          value={member.role}
                          disabled={busy}
                          onChange={(e) => changeRole(member.id, e.target.value as Role)}
                          className="rounded-md border border-border-subtle bg-surface px-2 py-1 text-xs text-ink disabled:opacity-60"
                        >
                          {(Object.keys(ROLE_LABELS) as Role[]).map((r) => (
                            <option key={r} value={r}>{ROLE_LABELS[r]}</option>
                          ))}
                        </select>
                      </td>
                      <td className="px-4 py-3">
                        <span className={member.is_active ? "text-status-ok" : "text-ink-muted"}>
                          {member.is_active ? "Active" : "Disabled"}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end gap-2">
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => resetPassword(member.id)}
                            className="rounded-md border border-border-subtle px-2 py-1 text-xs text-ink disabled:opacity-60"
                          >
                            Reset password
                          </button>
                          <button
                            type="button"
                            disabled={busy || isSelf}
                            title={isSelf ? "You cannot deactivate your own account" : undefined}
                            onClick={() => toggleActive(member)}
                            className="rounded-md border border-border-subtle px-2 py-1 text-xs text-ink disabled:opacity-60"
                          >
                            {member.is_active ? "Deactivate" : "Reactivate"}
                          </button>
                        </div>
                      </td>
                    </tr>
                    {revealedPassword ? (
                      <tr className="border-t border-border-subtle bg-surface-raised">
                        <td colSpan={5} className="px-4 py-3">
                          <p className="text-xs text-ink-muted">
                            New password for {member.email} — shown once, share it with them directly:
                          </p>
                          <div className="mt-1 flex items-center gap-2">
                            <code className="rounded-md bg-surface px-2 py-1 text-sm text-ink">{revealedPassword}</code>
                            <button
                              type="button"
                              onClick={() =>
                                setResetPasswords((prev) => {
                                  const next = { ...prev };
                                  delete next[member.id];
                                  return next;
                                })
                              }
                              className="text-xs text-ink-muted underline"
                            >
                              Dismiss
                            </button>
                          </div>
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
