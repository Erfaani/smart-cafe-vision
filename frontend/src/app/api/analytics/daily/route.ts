import { NextResponse } from "next/server";

import { ApiRequestError, apiFetch } from "@/lib/api";
import type { DailyStat } from "@/lib/types";

/** Forwards `start`/`end` straight through to the backend's own range filter
 * -- see apps/analytics/views.py::DailyStatFilterSet. */
export async function GET(request: Request) {
  const { search } = new URL(request.url);
  try {
    const stats = await apiFetch<DailyStat[]>(`/api/v1/analytics/daily/${search}`);
    return NextResponse.json(stats);
  } catch (error) {
    if (error instanceof ApiRequestError) {
      return NextResponse.json({ error: { code: error.code, message: error.message } }, { status: error.status });
    }
    throw error;
  }
}
