import Link from "next/link";
import { redirect } from "next/navigation";

import { SignOutButton } from "@/components/sign-out-button";
import { ApiRequestError, apiFetch } from "@/lib/api";
import type { User } from "@/lib/types";

/**
 * Navigation for the whole admin area.
 *
 * `available` marks what is actually built. Showing a link that leads nowhere
 * is how café staff lose trust in a tool, so unbuilt sections are visible but
 * plainly labelled rather than hidden or fake.
 */
const NAV_SECTIONS = [
  {
    label: "Overview",
    items: [{ href: "/dashboard", label: "Overview", available: true }],
  },
  {
    label: "Live",
    items: [
      { href: "/dashboard/cameras/live", label: "Live cameras", available: true },
      { href: "/dashboard/customers", label: "Customers", available: true },
      { href: "/dashboard/tables", label: "Tables", available: true },
    ],
  },
  {
    label: "Insights",
    items: [{ href: "/dashboard/analytics", label: "Analytics", available: true }],
  },
  {
    label: "Configuration",
    items: [
      { href: "/dashboard/cameras", label: "Cameras", available: true },
      { href: "/dashboard/display", label: "Public display", available: true },
      { href: "/dashboard/messages", label: "Messages", available: true },
      { href: "/dashboard/staff", label: "Staff", available: true },
      { href: "/dashboard/cafe", label: "Café settings", available: true },
      { href: "/dashboard/system", label: "System", available: false },
    ],
  },
] as const;

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  let user: User;
  try {
    user = await apiFetch<User>("/api/v1/auth/me/");
  } catch (error) {
    // An expired session lands here; anything else is a backend problem the
    // overview page reports properly, so only 401 forces a sign-in.
    if (error instanceof ApiRequestError && error.status === 401) redirect("/login");
    throw error;
  }

  return (
    <div className="flex min-h-dvh bg-surface">
      <aside className="hidden w-60 shrink-0 border-r border-border-subtle bg-surface-raised md:block">
        <div className="px-5 py-5">
          <p className="text-sm font-semibold tracking-tight text-ink">Smart Café Vision</p>
          <p className="mt-0.5 truncate text-xs text-ink-muted">
            {user.cafe_name ?? "No café assigned"}
          </p>
        </div>

        <nav className="px-3 pb-6">
          {NAV_SECTIONS.map((section) => (
            <div key={section.label} className="mb-5">
              <p className="px-2 pb-1.5 text-[11px] font-medium uppercase tracking-wider text-ink-muted">
                {section.label}
              </p>
              <ul className="space-y-0.5">
                {section.items.map((item) => (
                  <li key={item.href}>
                    {item.available ? (
                      <Link
                        href={item.href}
                        className="block rounded-md px-2 py-1.5 text-sm text-ink hover:bg-surface"
                      >
                        {item.label}
                      </Link>
                    ) : (
                      <span
                        className="flex cursor-not-allowed items-center justify-between rounded-md px-2 py-1.5 text-sm text-ink-muted"
                        title="Not built yet"
                      >
                        {item.label}
                        <span className="text-[10px] uppercase tracking-wide">soon</span>
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-border-subtle px-6 py-3">
          <Link href="/dashboard/account" className="min-w-0 hover:opacity-80">
            <p className="truncate text-sm text-ink">{user.display_name}</p>
            <p className="text-xs capitalize text-ink-muted">{user.role}</p>
          </Link>
          <SignOutButton />
        </header>

        <main className="flex-1 px-6 py-6">{children}</main>
      </div>
    </div>
  );
}
