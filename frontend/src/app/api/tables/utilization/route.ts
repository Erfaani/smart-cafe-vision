import { NextResponse } from "next/server";

import { ApiRequestError, apiFetch } from "@/lib/api";
import type { TableUtilization } from "@/lib/types";

/** Forwards `start`/`end` straight through -- see
 * apps/tables/views.py::TableUtilizationView. */
export async function GET(request: Request) {
  const { search } = new URL(request.url);
  try {
    const rows = await apiFetch<TableUtilization[]>(`/api/v1/tables/utilization/${search}`);
    return NextResponse.json(rows);
  } catch (error) {
    if (error instanceof ApiRequestError) {
      return NextResponse.json({ error: { code: error.code, message: error.message } }, { status: error.status });
    }
    throw error;
  }
}
