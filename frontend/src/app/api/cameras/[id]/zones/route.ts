import { NextResponse } from "next/server";

import { ApiRequestError, apiFetch } from "@/lib/api";
import type { Zone } from "@/lib/types";

type RouteParams = { params: Promise<{ id: string }> };

export async function GET(_request: Request, { params }: RouteParams) {
  const { id } = await params;
  try {
    const zones = await apiFetch<Zone[]>(`/api/v1/cameras/${id}/zones/`);
    return NextResponse.json(zones);
  } catch (error) {
    if (error instanceof ApiRequestError) {
      return NextResponse.json({ error: { code: error.code, message: error.message } }, { status: error.status });
    }
    throw error;
  }
}

export async function POST(request: Request, { params }: RouteParams) {
  const { id } = await params;
  const body = await request.json();
  try {
    const zone = await apiFetch<Zone>(`/api/v1/cameras/${id}/zones/`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    return NextResponse.json(zone, { status: 201 });
  } catch (error) {
    if (error instanceof ApiRequestError) {
      return NextResponse.json({ error: { code: error.code, message: error.message, detail: error.detail } }, { status: error.status });
    }
    throw error;
  }
}
