import { NextResponse } from "next/server";

import { ApiRequestError, apiFetch } from "@/lib/api";
import type { CameraTracks } from "@/lib/types";

/** Near-real-time tracking summary for a live-view badge. Small JSON, so
 * this uses apiFetch (not the raw streaming proxy the preview image uses). */
export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  try {
    const summary = await apiFetch<CameraTracks>(`/api/v1/cameras/${id}/tracks/`);
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
