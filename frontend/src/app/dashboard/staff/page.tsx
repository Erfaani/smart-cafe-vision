import type { Metadata } from "next";

import { StaffPageClient } from "@/components/staff-page-client";
import { apiFetch } from "@/lib/api";
import type { Paginated, User } from "@/lib/types";

export const metadata: Metadata = { title: "Staff" };
export const dynamic = "force-dynamic";

export default async function StaffPage() {
  const [staff, me] = await Promise.all([
    apiFetch<Paginated<User>>("/api/v1/auth/users/"),
    apiFetch<User>("/api/v1/auth/me/"),
  ]);

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <header>
        <h1 className="text-lg font-semibold tracking-tight text-ink">Staff</h1>
        <p className="mt-1 text-sm text-ink-muted">
          Accounts that can sign in to this café&apos;s dashboard. Owners and managers can add,
          change the role of, and deactivate accounts here.
        </p>
      </header>

      <StaffPageClient initialStaff={staff.results} currentUserId={me.id} />
    </div>
  );
}
