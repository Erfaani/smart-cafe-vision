import { NextResponse } from "next/server";

import { apiFetchRaw } from "@/lib/api";

/** A single current frame -- used for camera list thumbnails, cheaper than a
 * live MJPEG connection per row. */
export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const response = await apiFetchRaw(`/api/v1/cameras/${id}/snapshot.jpg/`);

  if (!response.ok || !response.body) {
    return NextResponse.json(
      { error: { code: "no_snapshot", message: "No frame has been captured yet." } },
      { status: response.status || 404 },
    );
  }

  return new NextResponse(response.body, {
    status: 200,
    headers: {
      "Content-Type": "image/jpeg",
      "Cache-Control": "no-cache, no-store",
    },
  });
}
