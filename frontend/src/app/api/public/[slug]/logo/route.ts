import { NextResponse } from "next/server";

import { BACKEND_URL } from "@/lib/api";
import type { PublicCafe } from "@/lib/types";

/**
 * Proxies a café's logo for the public display.
 *
 * The backend serialises `logo` as an absolute URL built from whatever host
 * the request arrived on -- when this route's own server-side fetch below
 * uses `BACKEND_INTERNAL_URL` (the Docker-internal hostname), that is the
 * host Django bakes into the URL, and a browser cannot resolve it. This
 * route fetches the image server-side, where that hostname *is* resolvable,
 * and streams the bytes back through Next's own origin -- the same pattern
 * as /api/cameras/[id]/snapshot for the same reason.
 */
export async function GET(_request: Request, { params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;

  const cafeResponse = await fetch(`${BACKEND_URL}/api/v1/cafes/public/${slug}/`, { cache: "no-store" });
  if (!cafeResponse.ok) return new NextResponse(null, { status: 404 });

  const cafe = (await cafeResponse.json()) as PublicCafe;
  if (!cafe.logo) return new NextResponse(null, { status: 404 });

  const imageResponse = await fetch(cafe.logo);
  if (!imageResponse.ok || !imageResponse.body) return new NextResponse(null, { status: 404 });

  return new NextResponse(imageResponse.body, {
    status: 200,
    headers: {
      "Content-Type": imageResponse.headers.get("Content-Type") ?? "image/png",
      "Cache-Control": "public, max-age=300",
    },
  });
}
