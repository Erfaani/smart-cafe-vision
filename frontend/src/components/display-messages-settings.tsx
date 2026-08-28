"use client";

import { useState } from "react";

import type { ApiError, DisplayMessage } from "@/lib/types";

export function DisplayMessagesSettings({ initialMessages }: { initialMessages: DisplayMessage[] }) {
  const [messages, setMessages] = useState(initialMessages);
  const [draftEn, setDraftEn] = useState("");
  const [draftFa, setDraftFa] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function addMessage() {
    if (!draftEn.trim()) return;
    setPending(true);
    setError(null);
    try {
      const response = await fetch("/api/display-messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text_en: draftEn.trim(), text_fa: draftFa.trim() }),
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as ApiError | null;
        setError(body?.error?.message ?? "Could not add that message.");
        return;
      }
      const message = (await response.json()) as DisplayMessage;
      setMessages((prev) => [...prev, message]);
      setDraftEn("");
      setDraftFa("");
    } catch {
      setError("Could not reach the server.");
    } finally {
      setPending(false);
    }
  }

  async function toggleActive(message: DisplayMessage) {
    const response = await fetch(`/api/display-messages/${message.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_active: !message.is_active }),
    });
    if (response.ok) {
      const updated = (await response.json()) as DisplayMessage;
      setMessages((prev) => prev.map((m) => (m.id === message.id ? updated : m)));
    }
  }

  async function removeMessage(id: string) {
    await fetch(`/api/display-messages/${id}`, { method: "DELETE" });
    setMessages((prev) => prev.filter((m) => m.id !== id));
  }

  return (
    <div className="space-y-4 rounded-lg border border-border-subtle bg-surface-raised p-4">
      <div>
        <h2 className="text-sm font-medium text-ink">Display messages</h2>
        <p className="mt-1 text-xs text-ink-muted">
          Rotate through these during the public display&apos;s entertainment mode. Persian is
          optional -- an untranslated message falls back to English rather than showing blank.
        </p>
      </div>

      {messages.length === 0 ? (
        <p className="text-xs text-ink-muted">No messages yet.</p>
      ) : (
        <ul className="space-y-2">
          {messages.map((message) => (
            <li key={message.id} className="flex items-center gap-3 rounded-md border border-border-subtle px-3 py-2">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-ink">{message.text_en}</p>
                {message.text_fa ? (
                  <p className="truncate text-xs text-ink-muted" dir="rtl">{message.text_fa}</p>
                ) : null}
              </div>
              <button
                type="button"
                onClick={() => toggleActive(message)}
                className="rounded-md border border-border-subtle px-2 py-1 text-xs text-ink"
              >
                {message.is_active ? "Active" : "Disabled"}
              </button>
              <button
                type="button"
                onClick={() => removeMessage(message.id)}
                className="rounded-md border border-border-subtle px-2 py-1 text-xs text-status-down"
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="space-y-2 border-t border-border-subtle pt-3">
        <input
          value={draftEn}
          onChange={(e) => setDraftEn(e.target.value)}
          placeholder="English (required)"
          className="w-full rounded-md border border-border-subtle bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
        />
        <input
          value={draftFa}
          onChange={(e) => setDraftFa(e.target.value)}
          placeholder="فارسی (optional)"
          dir="rtl"
          className="w-full rounded-md border border-border-subtle bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
        />
        <button
          type="button"
          onClick={addMessage}
          disabled={pending || !draftEn.trim()}
          className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-surface disabled:opacity-60"
        >
          {pending ? "Adding…" : "Add message"}
        </button>
      </div>

      {error ? <p role="alert" className="text-sm text-status-down">{error}</p> : null}
    </div>
  );
}
