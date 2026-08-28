import { NextResponse } from "next/server";

import { ApiRequestError, apiFetch } from "@/lib/api";
import type { CustomerSession, Paginated } from "@/lib/types";

/** Lists customer sessions, forwarding `status`/`camera_id` filters straight
 * through to the backend. Used both for the customers page's initial
 * server-side render and for the client's periodic poll. */
export async function GET(request: Request) {
  const { search } = new URL(request.url);
  try {
    const page = await apiFetch<Paginated<CustomerSession>>(`/api/v1/sessions/${search}`);
    return NextResponse.json(page);
  } catch (error) {
    if (error instanceof ApiRequestError) {
      return NextResponse.json({ error: { code: error.code, message: error.message } }, { status: error.status });
    }
    throw error;
  }
}
