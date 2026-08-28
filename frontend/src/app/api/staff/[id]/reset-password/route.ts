import { NextResponse } from "next/server";

import { ApiRequestError, apiFetch } from "@/lib/api";

type RouteParams = { params: Promise<{ id: string }> };

export async function POST(_request: Request, { params }: RouteParams) {
  const { id } = await params;
  try {
    const body = await apiFetch<{ password: string }>(`/api/v1/auth/users/${id}/reset-password/`, {
      method: "POST",
    });
    return NextResponse.json(body);
  } catch (error) {
    if (error instanceof ApiRequestError) {
      return NextResponse.json({ error: { code: error.code, message: error.message } }, { status: error.status });
    }
    throw error;
  }
}
