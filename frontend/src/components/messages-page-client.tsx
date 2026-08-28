"use client";

import { useState, type FormEvent } from "react";

import type { DisplayMessage } from "@/lib/types";

const inputClass =
  "w-full rounded-md border border-border-subtle bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent";
const labelClass = "mb-1.5 block text-sm font-medium text-ink";

/**
 * Manages the public display's entertainment-mode message rotation
 * (Phase 7's backend, finished off in Phase 11 -- the API and BFF routes
 * existed already, but no dashboard page had ever called them). A message
 * is always generic, never composed to reference a specific tracked
 * person's stay -- see backend/apps/display/models.py's docstring.
 */
export function MessagesPageClient({ initialMessages }: { initialMessages: DisplayMessage[] }) {
  const [messages, setMessages] = useState(initialMessages);
  const [textEn, setTextEn] = useState("");
  const [textFa, setTextFa] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/display-messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text_en: textEn, text_fa: textFa }),
      });
      if (!response.ok) {
        setError("Could not save the new message.");
        return;
      }
      const message = (await response.json()) as DisplayMessage;
      setMessages((prev) => [...prev, message]);
      setTextEn("");
      setTextFa("");
    } catch {
      setError("Could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  async function updateMessage(id: string, patch: Partial<DisplayMessage>) {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`/api/display-messages/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      if (!response.ok) {
        setError("Could not save that change.");
        return;
      }
      const updated = (await response.json()) as DisplayMessage;
      setMessages((prev) => prev.map((m) => (m.id === id ? updated : m)));
    } catch {
      setError("Could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  async function deleteMessage(id: string) {
    if (!confirm("Remove this message from the rotation? This cannot be undone.")) return;
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`/api/display-messages/${id}`, { method: "DELETE" });
      if (!response.ok && response.status !== 204) {
        setError("Could not remove that message.");
        return;
      }
      setMessages((prev) => prev.filter((m) => m.id !== id));
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
            <label className={labelClass} htmlFor="message-en">English</label>
            <input
              id="message-en"
              required
              maxLength={200}
              value={textEn}
              onChange={(e) => setTextEn(e.target.value)}
              placeholder="Did you know our beans are roasted locally?"
              className={inputClass}
            />
          </div>
          <div>
            <label className={labelClass} htmlFor="message-fa">
              Persian <span className="text-ink-muted">(optional)</span>
            </label>
            <input
              id="message-fa"
              maxLength={200}
              value={textFa}
              onChange={(e) => setTextFa(e.target.value)}
              dir="rtl"
              className={inputClass}
            />
          </div>
        </div>
        <p className="text-xs text-ink-muted">
          Shown during the public display&apos;s entertainment mode. Keep it generic — never
          composed to reference a specific person or how long they&apos;ve been here.
        </p>
        {error ? <p role="alert" className="text-sm text-status-down">{error}</p> : null}
        <button
          type="submit"
          disabled={busy || !textEn.trim()}
          className="rounded-md bg-accent px-3 py-2 text-sm font-medium text-surface disabled:opacity-60"
        >
          {busy ? "Saving…" : "Add message"}
        </button>
      </form>

      {messages.length === 0 ? (
        <p className="rounded-lg border border-border-subtle px-4 py-6 text-center text-sm text-ink-muted">
          No messages yet. Add one above to start the rotation.
        </p>
      ) : (
        <ul className="space-y-2">
          {messages.map((message) => (
            <MessageRow key={message.id} message={message} busy={busy} onUpdate={updateMessage} onDelete={deleteMessage} />
          ))}
        </ul>
      )}
    </div>
  );
}

function MessageRow({
  message,
  busy,
  onUpdate,
  onDelete,
}: {
  message: DisplayMessage;
  busy: boolean;
  onUpdate: (id: string, patch: Partial<DisplayMessage>) => void;
  onDelete: (id: string) => void;
}) {
  const [textEn, setTextEn] = useState(message.text_en);
  const [textFa, setTextFa] = useState(message.text_fa);

  return (
    <li className="flex flex-wrap items-center gap-3 rounded-lg border border-border-subtle px-4 py-3">
      <span
        className={`size-2.5 shrink-0 rounded-full ${message.is_active ? "bg-accent" : "bg-ink-muted"}`}
        aria-hidden
      />
      <input
        value={textEn}
        onChange={(e) => setTextEn(e.target.value)}
        onBlur={() => {
          if (textEn.trim() && textEn !== message.text_en) onUpdate(message.id, { text_en: textEn.trim() });
        }}
        disabled={busy}
        className="min-w-0 flex-1 rounded-md border border-border-subtle bg-surface px-2 py-1 text-sm text-ink outline-none focus:border-accent"
      />
      <input
        value={textFa}
        onChange={(e) => setTextFa(e.target.value)}
        onBlur={() => {
          if (textFa !== message.text_fa) onUpdate(message.id, { text_fa: textFa });
        }}
        dir="rtl"
        placeholder="—"
        disabled={busy}
        className="min-w-0 flex-1 rounded-md border border-border-subtle bg-surface px-2 py-1 text-sm text-ink outline-none focus:border-accent"
      />
      <button
        type="button"
        disabled={busy}
        onClick={() => onUpdate(message.id, { is_active: !message.is_active })}
        className="rounded-md border border-border-subtle px-2 py-1 text-xs text-ink disabled:opacity-60"
      >
        {message.is_active ? "Active" : "Disabled"}
      </button>
      <button
        type="button"
        disabled={busy}
        onClick={() => onDelete(message.id)}
        className="rounded-md border border-border-subtle px-2 py-1 text-xs text-status-down disabled:opacity-60"
      >
        Delete
      </button>
    </li>
  );
}
