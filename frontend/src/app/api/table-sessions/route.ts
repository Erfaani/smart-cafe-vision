import { NextResponse } from "next/server";

import { ApiRequestError, apiFetch } from "@/lib/api";
import type { Paginated, TableSession } from "@/lib/types";

/** Lists table sessions, forwarding `status`/`camera_id`/`table_zone_id`
 * filters straight through. Used both for the Tables page's initial
 * server-side render and for the client's periodic poll -- same pattern as
 * /api/sessions for customer sessions (Phase 5). */
export async function GET(request: Request) {
  const { search } = new URL(request.url);
  try {
    const page = await apiFetch<Paginated<TableSession>>(`/api/v1/tables/sessions/${search}`);
    return NextResponse.json(page);
  } catch (error) {
    if (error instanceof ApiRequestError) {
      return NextResponse.json({ error: { code: error.code, message: error.message } }, { status: error.status });
    }
    throw error;
  }
}
