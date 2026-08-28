import { NextResponse } from "next/server";

import { ApiRequestError, apiFetch } from "@/lib/api";
import type { User } from "@/lib/types";

type RouteParams = { params: Promise<{ id: string }> };

export async function POST(_request: Request, { params }: RouteParams) {
  const { id } = await params;
  try {
    const user = await apiFetch<User>(`/api/v1/auth/users/${id}/deactivate/`, { method: "POST" });
    return NextResponse.json(user);
  } catch (error) {
    if (error instanceof ApiRequestError) {
      return NextResponse.json({ error: { code: error.code, message: error.message } }, { status: error.status });
    }
    throw error;
  }
}
