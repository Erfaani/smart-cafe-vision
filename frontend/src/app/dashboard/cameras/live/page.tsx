import type { Metadata } from "next";
import Link from "next/link";

import { CameraLiveTile } from "@/components/camera-live-tile";
import { apiFetch } from "@/lib/api";
import type { Camera, Paginated } from "@/lib/types";

export const metadata: Metadata = { title: "Live cameras" };
export const dynamic = "force-dynamic";

export default async function LiveCamerasPage() {
  const page = await apiFetch<Paginated<Camera>>("/api/v1/cameras/");
  const enabled = page.results.filter((camera) => camera.is_enabled);

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <header>
        <h1 className="text-lg font-semibold tracking-tight text-ink">Live cameras</h1>
        <p className="mt-1 text-sm text-ink-muted">
          A low-rate preview cached by the AI worker — not the detection feed itself.
        </p>
      </header>

      {enabled.length === 0 ? (
        <p className="rounded-lg border border-border-subtle px-4 py-6 text-center text-sm text-ink-muted">
          No enabled cameras.{" "}
          <Link href="/dashboard/cameras" className="text-accent underline">
            Add or enable one
          </Link>
          .
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {enabled.map((camera) => (
            <CameraLiveTile key={camera.id} camera={camera} />
          ))}
        </div>
      )}
    </div>
  );
}
