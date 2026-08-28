import type { Metadata } from "next";

import { CustomersPageClient } from "@/components/customers-page-client";
import { apiFetch } from "@/lib/api";
import { DEFAULT_STAY_COLOR_STOPS } from "@/lib/stay-color";
import type { Cafe, Camera, CustomerSession, Paginated, User } from "@/lib/types";

export const metadata: Metadata = { title: "Customers" };
export const dynamic = "force-dynamic";

export default async function CustomersPage() {
  const user = await apiFetch<User>("/api/v1/auth/me/");
  const [sessions, cameras, cafe] = await Promise.all([
    apiFetch<Paginated<CustomerSession>>("/api/v1/sessions/"),
    apiFetch<Paginated<Camera>>("/api/v1/cameras/"),
    user.cafe_slug ? apiFetch<Cafe>(`/api/v1/cafes/${user.cafe_slug}/`) : Promise.resolve(null),
  ]);

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <header>
        <h1 className="text-lg font-semibold tracking-tight text-ink">Customers</h1>
        <p className="mt-1 text-sm text-ink-muted">
          Anonymous occupancy and stay time, derived from entry/exit line crossings. No faces,
          names, or images are ever recorded.
        </p>
      </header>

      <CustomersPageClient
        initialSessions={sessions.results}
        cameras={cameras.results}
        colorStops={cafe?.stay_color_stops ?? DEFAULT_STAY_COLOR_STOPS}
      />
    </div>
  );
}
