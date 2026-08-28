import { NextResponse } from "next/server";

import { ApiRequestError, apiFetch } from "@/lib/api";

export async function POST(request: Request) {
  const body = await request.json();
  try {
    await apiFetch("/api/v1/auth/password/", { method: "POST", body: JSON.stringify(body) });
    return new NextResponse(null, { status: 204 });
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
