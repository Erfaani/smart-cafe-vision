import type { Metadata } from "next";

import { CamerasPageClient } from "@/components/cameras-page-client";
import { apiFetch } from "@/lib/api";
import type { Camera, Paginated } from "@/lib/types";

export const metadata: Metadata = { title: "Cameras" };
export const dynamic = "force-dynamic";

export default async function CamerasPage() {
  const page = await apiFetch<Paginated<Camera>>("/api/v1/cameras/");

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <header>
        <h1 className="text-lg font-semibold tracking-tight text-ink">Cameras</h1>
        <p className="mt-1 text-sm text-ink-muted">
          Connect the café&apos;s existing IP cameras over RTSP. Video stays on the local network.
        </p>
      </header>

      <CamerasPageClient cameras={page.results} />
    </div>
  );
}
