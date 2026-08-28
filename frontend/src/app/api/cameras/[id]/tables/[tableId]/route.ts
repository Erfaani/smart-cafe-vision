import { NextResponse } from "next/server";

import { ApiRequestError, apiFetch } from "@/lib/api";
import type { TableZone } from "@/lib/types";

type RouteParams = { params: Promise<{ id: string; tableId: string }> };

export async function PATCH(request: Request, { params }: RouteParams) {
  const { id, tableId } = await params;
  const body = await request.json();
  try {
    const table = await apiFetch<TableZone>(`/api/v1/cameras/${id}/tables/${tableId}/`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
    return NextResponse.json(table);
  } catch (error) {
    if (error instanceof ApiRequestError) {
      return NextResponse.json(
        { error: { code: error.code, message: error.message, detail: error.detail } },
        { status: error.status },
      );
    }
    throw error;
  }
}

export async function DELETE(_request: Request, { params }: RouteParams) {
  const { id, tableId } = await params;
  try {
    await apiFetch(`/api/v1/cameras/${id}/tables/${tableId}/`, { method: "DELETE" });
    return new NextResponse(null, { status: 204 });
  } catch (error) {
    if (error instanceof ApiRequestError) {
      return NextResponse.json({ error: { code: error.code, message: error.message } }, { status: error.status });
    }
    throw error;
  }
}
