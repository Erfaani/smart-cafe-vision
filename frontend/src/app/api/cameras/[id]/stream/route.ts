import { NextResponse } from "next/server";

import { apiFetchRaw } from "@/lib/api";

/**
 * Proxies the live MJPEG preview.
 *
 * The browser never talks to Django directly (see docs/architecture.md), so
 * an `<img>` tag pointed at the live view has to go through this route, which
 * attaches the access token server-side and pipes the multipart stream
 * straight through without buffering it -- buffering would turn a live view
 * into a slideshow that lags further behind with every frame.
 *
 * timeoutMs: 0 because this connection is meant to stay open for minutes,
 * unlike every other call through apiFetch.
 */
export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const response = await apiFetchRaw(`/api/v1/cameras/${id}/stream.mjpg/`, { timeoutMs: 0 });

  if (!response.ok || !response.body) {
    return NextResponse.json(
      { error: { code: "camera_stream_unavailable", message: "Could not open the camera stream." } },
      { status: response.status || 502 },
    );
  }

  return new NextResponse(response.body, {
    status: 200,
    headers: {
      "Content-Type": response.headers.get("Content-Type") ?? "multipart/x-mixed-replace",
      "Cache-Control": "no-cache, no-store",
    },
  });
}
