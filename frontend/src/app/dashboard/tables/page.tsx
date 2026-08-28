import type { Metadata } from "next";

import { TablesPageClient } from "@/components/tables-page-client";
import { apiFetch } from "@/lib/api";
import type { Camera, Paginated, TableSession } from "@/lib/types";

export const metadata: Metadata = { title: "Tables" };
export const dynamic = "force-dynamic";

export default async function TablesPage() {
  const [sessions, cameras] = await Promise.all([
    apiFetch<Paginated<TableSession>>("/api/v1/tables/sessions/"),
    apiFetch<Paginated<Camera>>("/api/v1/cameras/"),
  ]);

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <header>
        <h1 className="text-lg font-semibold tracking-tight text-ink">Tables</h1>
        <p className="mt-1 text-sm text-ink-muted">
          Occupancy derived from how much of each table&apos;s area a tracked person&apos;s box
          covers — no identity, just position over time.
        </p>
      </header>

      <TablesPageClient initialSessions={sessions.results} cameras={cameras.results} />
    </div>
  );
}
