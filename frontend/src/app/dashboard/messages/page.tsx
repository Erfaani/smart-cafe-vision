import type { Metadata } from "next";

import { MessagesPageClient } from "@/components/messages-page-client";
import { apiFetch } from "@/lib/api";
import type { DisplayMessage, Paginated } from "@/lib/types";

export const metadata: Metadata = { title: "Messages" };
export const dynamic = "force-dynamic";

export default async function MessagesPage() {
  const messages = await apiFetch<Paginated<DisplayMessage>>("/api/v1/display-messages/");

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <header>
        <h1 className="text-lg font-semibold tracking-tight text-ink">Messages</h1>
        <p className="mt-1 text-sm text-ink-muted">
          The rotating line shown during the public display&apos;s entertainment mode, in English
          and Persian.
        </p>
      </header>

      <MessagesPageClient initialMessages={messages.results} />
    </div>
  );
}
