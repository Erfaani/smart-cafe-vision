import type { Metadata } from "next";
import Link from "next/link";

import { apiFetch } from "@/lib/api";
import type { User } from "@/lib/types";

export const metadata: Metadata = { title: "Public display" };
export const dynamic = "force-dynamic";

export default async function PublicDisplayPage() {
  const user = await apiFetch<User>("/api/v1/auth/me/");

  if (!user.cafe_slug) {
    return (
      <div className="mx-auto max-w-3xl">
        <p className="rounded-lg border border-border-subtle px-4 py-6 text-center text-sm text-ink-muted">
          This account has no café assigned.
        </p>
      </div>
    );
  }

  const displayPath = `/display/${user.cafe_slug}`;

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <header>
        <h1 className="text-lg font-semibold tracking-tight text-ink">Public display</h1>
        <p className="mt-1 text-sm text-ink-muted">
          What plays on the café&apos;s TV -- point its browser at this address. It needs no
          sign-in and cycles through live tracking, today&apos;s stats, the longest-stay
          leaderboard, and your display messages automatically.
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border-subtle bg-surface-raised p-4">
        <code className="flex-1 truncate rounded-md bg-surface px-3 py-2 text-sm text-ink">
          {displayPath}
        </code>
        <Link
          href={displayPath}
          target="_blank"
          rel="noopener noreferrer"
          className="rounded-md bg-accent px-3 py-2 text-sm font-medium text-surface"
        >
          Open in a new tab
        </Link>
      </div>

      <p className="text-xs text-ink-muted">
        Colours and messages are configured on{" "}
        <Link href="/dashboard/cafe" className="text-accent underline">
          Café settings
        </Link>
        .
      </p>

      <div className="overflow-hidden rounded-lg border border-border-subtle">
        <iframe
          src={displayPath}
          title="Public display preview"
          className="aspect-video w-full"
        />
      </div>
    </div>
  );
}
