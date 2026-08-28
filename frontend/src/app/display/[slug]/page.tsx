import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { DisplayClient } from "@/components/display/display-client";
import { ApiRequestError, apiFetch } from "@/lib/api";
import type { CameraLiveTracks, DisplayStats, PublicCafe, PublicDisplayMessage } from "@/lib/types";

export const dynamic = "force-dynamic";

type PageParams = { params: Promise<{ slug: string }> };

/** Every fetch on this page is unauthenticated (`authenticated: false`) --
 * the public display has no session to attach a token from, and every
 * endpoint it calls is designed to be called without one (spec: a kiosk
 * browser on a café TV, not a signed-in staff member). A failed fetch
 * degrades to `null` rather than throwing, so one missing piece (say, the
 * worker has never published a camera_stats and stats/live are momentarily
 * empty) never takes the whole page down. */
async function publicFetch<T>(path: string): Promise<T | null> {
  try {
    return await apiFetch<T>(path, { authenticated: false });
  } catch (error) {
    if (error instanceof ApiRequestError) return null;
    throw error;
  }
}

export async function generateMetadata({ params }: PageParams): Promise<Metadata> {
  const { slug } = await params;
  const cafe = await publicFetch<PublicCafe>(`/api/v1/cafes/public/${slug}/`);
  return { title: cafe ? cafe.name : "Smart Café Vision" };
}

export default async function DisplayPage({ params }: PageParams) {
  const { slug } = await params;
  const cafe = await publicFetch<PublicCafe>(`/api/v1/cafes/public/${slug}/`);
  if (!cafe) notFound();

  const [tracks, stats, messages] = await Promise.all([
    publicFetch<CameraLiveTracks[]>(`/api/v1/cafes/public/${slug}/live/`),
    publicFetch<DisplayStats>(`/api/v1/cafes/public/${slug}/stats/`),
    publicFetch<PublicDisplayMessage[]>(`/api/v1/cafes/public/${slug}/messages/`),
  ]);

  return (
    <DisplayClient
      slug={slug}
      initialCafe={cafe}
      initialTracks={tracks ?? []}
      initialStats={stats}
      initialMessages={messages ?? []}
    />
  );
}
