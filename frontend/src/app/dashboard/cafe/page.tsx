import type { Metadata } from "next";
import Link from "next/link";

import { CafeColorSettings } from "@/components/cafe-color-settings";
import { DisplayMessagesSettings } from "@/components/display-messages-settings";
import { apiFetch } from "@/lib/api";
import type { Cafe, DisplayMessage, Paginated, User } from "@/lib/types";

export const metadata: Metadata = { title: "Café settings" };
export const dynamic = "force-dynamic";

export default async function CafeSettingsPage() {
  const user = await apiFetch<User>("/api/v1/auth/me/");
  const [cafe, messages] = user.cafe_slug
    ? await Promise.all([
        apiFetch<Cafe>(`/api/v1/cafes/${user.cafe_slug}/`),
        apiFetch<Paginated<DisplayMessage>>("/api/v1/display-messages/"),
      ])
    : [null, null];

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <header>
        <h1 className="text-lg font-semibold tracking-tight text-ink">Café settings</h1>
        <p className="mt-1 text-sm text-ink-muted">{cafe?.name ?? "No café assigned"}</p>
        {cafe ? (
          <Link
            href={`/display/${cafe.slug}`}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-2 inline-block text-xs text-accent underline"
          >
            Open the public display &rarr;
          </Link>
        ) : null}
      </header>

      {cafe ? (
        <>
          <CafeColorSettings initialStops={cafe.stay_color_stops} />
          <DisplayMessagesSettings initialMessages={messages?.results ?? []} />
        </>
      ) : (
        <p className="rounded-lg border border-border-subtle px-4 py-6 text-center text-sm text-ink-muted">
          This account has no café assigned.
        </p>
      )}
    </div>
  );
}
