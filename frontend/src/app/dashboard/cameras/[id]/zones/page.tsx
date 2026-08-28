import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ZoneEditor } from "@/components/zone-editor";
import { ApiRequestError, apiFetch } from "@/lib/api";
import type { Camera, Zone } from "@/lib/types";

export const metadata: Metadata = { title: "Entry/exit zones" };
export const dynamic = "force-dynamic";

export default async function CameraZonesPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  let camera: Camera;
  let zones: Zone[];
  try {
    [camera, zones] = await Promise.all([
      apiFetch<Camera>(`/api/v1/cameras/${id}/`),
      apiFetch<Zone[]>(`/api/v1/cameras/${id}/zones/`),
    ]);
  } catch (error) {
    if (error instanceof ApiRequestError && error.status === 404) notFound();
    throw error;
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <header>
        <Link href="/dashboard/cameras" className="text-xs text-ink-muted hover:text-ink">
          &larr; Cameras
        </Link>
        <h1 className="mt-1 text-lg font-semibold tracking-tight text-ink">
          Entry/exit zones — {camera.name}
        </h1>
        <p className="mt-1 text-sm text-ink-muted">
          Draw a line across the frame wherever customers cross into or out of view. Each crossing
          is anonymous: only a temporary track id, a position, and a timestamp are ever recorded.
        </p>
      </header>

      <ZoneEditor camera={camera} initialZones={zones} />
    </div>
  );
}
