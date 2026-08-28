import { NextResponse } from "next/server";

import { apiFetchRaw } from "@/lib/api";

/**
 * Proxies the RTSP connection test. Forwards the backend's status code
 * (200 for success, 502 for a reachable-but-failing camera) rather than
 * normalising it, so the client can distinguish "the test ran and failed"
 * from "the request itself failed".
 */
export async function POST(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const response = await apiFetchRaw(`/api/v1/cameras/${id}/test-connection/`, { method: "POST" });
  const body = await response.text();
  return new NextResponse(body, {
    status: response.status,
    headers: { "Content-Type": response.headers.get("Content-Type") ?? "application/json" },
  });
}
