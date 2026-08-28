import { NextResponse } from "next/server";

import { ApiRequestError, apiFetch } from "@/lib/api";
import type { DisplayMessage, Paginated } from "@/lib/types";

export async function GET() {
  try {
    const page = await apiFetch<Paginated<DisplayMessage>>("/api/v1/display-messages/");
    return NextResponse.json(page.results);
  } catch (error) {
    if (error instanceof ApiRequestError) {
      return NextResponse.json({ error: { code: error.code, message: error.message } }, { status: error.status });
    }
    throw error;
  }
}

export async function POST(request: Request) {
  const body = await request.json();
  try {
    const message = await apiFetch<DisplayMessage>("/api/v1/display-messages/", {
      method: "POST",
      body: JSON.stringify(body),
    });
    return NextResponse.json(message, { status: 201 });
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
