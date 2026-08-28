import { NextResponse } from "next/server";

import { ApiRequestError, apiFetch } from "@/lib/api";
import type { Zone } from "@/lib/types";

type RouteParams = { params: Promise<{ id: string; zoneId: string }> };

export async function PATCH(request: Request, { params }: RouteParams) {
  const { id, zoneId } = await params;
  const body = await request.json();
  try {
    const zone = await apiFetch<Zone>(`/api/v1/cameras/${id}/zones/${zoneId}/`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
    return NextResponse.json(zone);
  } catch (error) {
    if (error instanceof ApiRequestError) {
      return NextResponse.json({ error: { code: error.code, message: error.message, detail: error.detail } }, { status: error.status });
    }
    throw error;
  }
}

export async function DELETE(_request: Request, { params }: RouteParams) {
  const { id, zoneId } = await params;
  try {
    await apiFetch(`/api/v1/cameras/${id}/zones/${zoneId}/`, { method: "DELETE" });
    return new NextResponse(null, { status: 204 });
  } catch (error) {
    if (error instanceof ApiRequestError) {
      return NextResponse.json({ error: { code: error.code, message: error.message } }, { status: error.status });
    }
    throw error;
  }
}
