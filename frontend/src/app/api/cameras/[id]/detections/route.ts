import { NextResponse } from "next/server";

import { ApiRequestError, apiFetch } from "@/lib/api";
import type { CameraDetections } from "@/lib/types";

/** Near-real-time detection summary for a live-view badge. Small JSON, so
 * this uses apiFetch (not the raw streaming proxy the preview image uses). */
export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  try {
    const summary = await apiFetch<CameraDetections>(`/api/v1/cameras/${id}/detections/`);
    return NextResponse.json(summary);
  } catch (error) {
    if (error instanceof ApiRequestError) {
      return NextResponse.json(
        { error: { code: error.code, message: error.message } },
        { status: error.status },
      );
    }
    throw error;
  }
}
