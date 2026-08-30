import type { Metadata } from "next";

import { StatusBadge } from "@/components/status-badge";
import { BACKEND_URL, apiFetch } from "@/lib/api";
import type { Cafe, HealthReport, Paginated } from "@/lib/types";

export const metadata: Metadata = { title: "Overview" };

// Health is a live reading; a cached one would be worse than none.
export const dynamic = "force-dynamic";

async function loadHealth(): Promise<HealthReport | null> {
  try {
    // /readyz answers 503 when a critical component is down, and the body is
    // the interesting part in exactly that case — so the status is not checked.
    const response = await fetch(`${BACKEND_URL}/readyz/`, { cache: "no-store" });
    return (await response.json()) as HealthReport;
  } catch {
    return null;
  }
}

async function loadCafe(): Promise<Cafe | null> {
  try {
    const page = await apiFetch<Paginated<Cafe>>("/api/v1/cafes/");
    return page.results[0] ?? null;
  } catch {
    return null;
  }
}

export default async function OverviewPage() {
  const [health, cafe] = await Promise.all([loadHealth(), loadCafe()]);

  return (
    <div className="mx-auto max-w-4xl space-y-8">
      <header>
        <h1 className="text-lg font-semibold tracking-tight text-ink">Overview</h1>
        <p className="mt-1 text-sm text-ink-muted">
          {cafe
            ? `${cafe.name} · ${cafe.timezone} · seats ${cafe.seating_capacity}`
            : "No café configured yet."}
        </p>
      </header>

      <section>
        <div className="mb-3 flex items-center gap-3">
          <h2 className="text-sm font-medium text-ink">System health</h2>
          {health ? <StatusBadge status={health.status} /> : <StatusBadge status="down" />}
        </div>

        {health ? (
          <div className="overflow-hidden rounded-lg border border-border-subtle">
            <table className="w-full text-sm">
              <tbody className="divide-y divide-border-subtle">
                {Object.entries(health.components).map(([name, component]) => (
                  <tr key={name}>
                    <td className="px-4 py-2.5 capitalize text-ink">{name.replace(/_/g, " ")}</td>
                    <td className="px-4 py-2.5 text-ink-muted">
                      {component.detail ??
                        (component.latency_ms !== undefined
                          ? `${component.latency_ms} ms`
                          : component.stream_length !== undefined
                            ? `${component.stream_length} events buffered`
                            : "—")}
                    </td>
                    <td className="w-24 px-4 py-2.5 text-right">
                      <StatusBadge status={component.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="rounded-lg border border-border-subtle px-4 py-3 text-sm text-ink-muted">
            Could not reach the backend health endpoint.
          </p>
        )}

        {health ? (
          <p className="mt-2 text-xs text-ink-muted">
            Version {health.version} · {health.environment}
          </p>
        ) : null}
      </section>

      <section className="rounded-lg border border-border-subtle bg-surface-raised px-4 py-4">
        <h2 className="text-sm font-medium text-ink">What is running</h2>
        <p className="mt-1.5 text-sm leading-relaxed text-ink-muted">
          Camera capture, person detection and tracking, entry/exit stay-time, table occupancy, the
          public display, staff and message management, and analytics are all live. The System
          section of the menu is the one part still marked <em>soon</em>.
        </p>
        {health?.components.ai_workers?.status === "degraded" ? (
          <p className="mt-3 text-sm text-ink-muted">
            No AI worker has connected yet — connect a camera to start tracking occupancy.
          </p>
        ) : null}
      </section>

      {cafe ? (
        <section>
          <h2 className="mb-2 text-sm font-medium text-ink">Privacy notice shown to customers</h2>
          <p className="rounded-lg border border-border-subtle px-4 py-3 text-sm leading-relaxed text-ink-muted">
            {cafe.privacy_notice}
          </p>
        </section>
      ) : null}
    </div>
  );
}
