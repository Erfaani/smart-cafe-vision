import type { Metadata } from "next";

import { AccountPageClient } from "@/components/account-page-client";
import { apiFetch } from "@/lib/api";
import type { User } from "@/lib/types";

export const metadata: Metadata = { title: "Your account" };
export const dynamic = "force-dynamic";

export default async function AccountPage() {
  const me = await apiFetch<User>("/api/v1/auth/me/");

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <header>
        <h1 className="text-lg font-semibold tracking-tight text-ink">Your account</h1>
        <p className="mt-1 text-sm text-ink-muted">
          {me.display_name} · {me.email} · <span className="capitalize">{me.role}</span>
        </p>
      </header>

      <AccountPageClient />
    </div>
  );
}
